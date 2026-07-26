"""Agent Loop — event-coalesced async loop with drift-gated resubmission.

Runs on Thread 2. Maintains a persistent policy dict and resubmits
proposals only when the deterministic controller drifts from targets.
LLM reasoning is triggered every ``reasoning_interval`` iterations.
"""

import time
import json
import queue
import hashlib
import logging
from datetime import datetime, timezone

from ecoagent.agent.context import ContextBuilder
from ecoagent.agent import prompts

logger = logging.getLogger(__name__)

# Minimum setpoint deviation to trigger resubmission (°C).
# Smaller than NORMAL_STEP (0.5) to catch the first controller adjustment.
DRIFT_THRESHOLD = 0.1


class AgentLoop:
    """Event-driven agent loop with drift-gated policy resubmission.

    The loop processes RuntimeSnapshot objects from a queue.Queue populated
    by an EventBus listener on Thread 1. On each iteration it:
      1. Drains the queue to the latest snapshot
      2. Checks drift between policy targets and snapshot setpoints
      3. Resubmits proposals only for zones with drift > DRIFT_THRESHOLD
      4. Triggers LLM reasoning every ``reasoning_interval`` iterations
    """

    def __init__(self, adapter, trace_logger, cycle_queue, shutdown_event,
                 llm_config, mcp_dispatcher=None):
        """
        Args:
            adapter: McpAdapter for direct calls (drift resubmission, context).
            trace_logger: AgentTraceLogger for writing JSONL traces.
            cycle_queue: queue.Queue receiving RuntimeSnapshot from EventBus.
            shutdown_event: threading.Event signaling shutdown.
            llm_config: dict with model, base_url, api_key, max_tokens,
                        temperature, reasoning_interval.
            mcp_dispatcher: McpToolDispatcher for LLM tool call execution.
                           If None, falls back to adapter direct calls.
        """
        self._adapter = adapter
        self._trace_logger = trace_logger
        self._queue = cycle_queue
        self._shutdown = shutdown_event
        self._config = llm_config
        self._mcp_dispatcher = mcp_dispatcher

        self._context_builder = ContextBuilder(adapter)
        self._reasoning_interval = llm_config.get("reasoning_interval", 16)

        # Policy state
        self.current_policy = {}  # {zone_name: (heating, cooling)}
        self._policy_version = 0
        self._cycles_since_reasoning = 0
        self._last_reasoning_ts = None
        self._last_reasoning_callback = None

        # System prompt hash for trace provenance
        self._prompt_hash = hashlib.sha256(
            prompts.SYSTEM_PROMPT.encode()
        ).hexdigest()[:8]

        # LLM client (lazy init)
        self._client = None

    def _get_client(self):
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(
                    base_url=self._config.get("base_url", "http://localhost:11434/v1"),
                    api_key=self._config.get("api_key", "ollama"),
                )
            except ImportError:
                raise ImportError(
                    "openai SDK is required for AgentLoop. "
                    "Install with: pip install openai"
                )
        return self._client

    def run(self):
        """Blocking loop. Call from threading.Thread(target=loop.run).

        Returns when shutdown_event is set or None sentinel is received.
        """
        logger.info("AgentLoop started. reasoning_interval=%d", self._reasoning_interval)

        # ── Warm the model so first real cycle isn't penalized ────
        try:
            client = self._get_client()
            client.chat.completions.create(
                model=self._config.get("model", "qwen2.5:7b"),
                messages=[{"role": "user", "content": "ready"}],
                max_tokens=1, timeout=30,
            )
            logger.info("Model warmed up successfully.")
        except Exception as e:
            logger.warning("Model warmup failed (non-fatal): %s", e)

        try:
            while not self._shutdown.is_set():
                try:
                    snapshot = self._queue.get(timeout=30)
                except queue.Empty:
                    continue

                if snapshot is None:
                    logger.info("AgentLoop received shutdown sentinel.")
                    break

                # Drain stale — keep latest snapshot
                while not self._queue.empty():
                    try:
                        newer = self._queue.get_nowait()
                        if newer is None:
                            logger.info("AgentLoop received shutdown sentinel during drain.")
                            return
                        snapshot = newer
                    except queue.Empty:
                        break

                try:
                    self._process_iteration(snapshot)
                except Exception as e:
                    logger.error("AgentLoop iteration error: %s", e, exc_info=True)
        finally:
            self._trace_logger.close()
            logger.info("AgentLoop stopped.")

    def _process_iteration(self, snapshot):
        """One loop iteration: drift check + optional reasoning."""

        # ── Drift check and resubmit ─────────────────────────────
        if self.current_policy:
            zones = snapshot.zones if hasattr(snapshot, "zones") else {}
            for zone_name, (target_h, target_c) in self.current_policy.items():
                zone_snap = zones.get(zone_name)
                if zone_snap is None:
                    continue
                h_drift = abs(zone_snap.heating_setpoint - target_h) > DRIFT_THRESHOLD
                c_drift = abs(zone_snap.cooling_setpoint - target_c) > DRIFT_THRESHOLD
                if h_drift or c_drift:
                    self._adapter.propose_setpoint(
                        zone_name, target_h, target_c, source="mcp_agent"
                    )

        # ── Reasoning cadence ────────────────────────────────────
        self._cycles_since_reasoning += 1

        if self._cycles_since_reasoning >= self._reasoning_interval:
            self._cycles_since_reasoning = 0
            self._run_reasoning(snapshot)

    def _run_reasoning(self, snapshot):
        """Execute a multi-turn LLM reasoning cycle: context → LLM → tools → LLM → ... → policy update.

        Implements a ReAct loop that feeds tool results back to the LLM so it
        can observe (e.g. get_building_summary) and then act (propose_setpoint)
        within a single reasoning cycle.

        Termination conditions (whichever comes first):
          1. Assistant returns no tool calls (finish_reason != "tool_calls")
          2. propose_setpoint executed successfully
          3. max_turns reached (configurable, default 4)
        """
        wall_start = time.time()
        reasoning_ts = datetime.now(timezone.utc).isoformat()
        callback_number = snapshot.callback_number if hasattr(snapshot, "callback_number") else None

        max_turns = self._config.get("max_turns", 4)

        error = None
        all_tool_calls_raw = []   # Accumulated across all turns
        all_tool_results = []     # Accumulated across all turns
        turns = []                # Per-turn records for trace
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_total_tokens = 0
        final_finish_reason = None
        final_content = None
        proposal_executed = False

        try:
            # Build context
            context = self._context_builder.build()
            user_message = prompts.build_user_message(context)

            # Build messages (grows across turns)
            messages = [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]

            # Build tool definitions for function calling
            openai_tools = self._build_openai_tools()

            for turn in range(max_turns):
                # ── LLM call with timeout and retry ──────────────
                response = None
                for attempt in range(2):
                    try:
                        client = self._get_client()
                        kwargs = {
                            "model": self._config.get("model", "qwen2.5:7b"),
                            "messages": messages,
                            "temperature": self._config.get("temperature", 0.0),
                            "max_tokens": self._config.get("max_tokens", 200),
                            "timeout": 30,
                        }
                        if openai_tools:
                            kwargs["tools"] = openai_tools
                        response = client.chat.completions.create(**kwargs)
                        break
                    except Exception as e:
                        if attempt == 0:
                            logger.warning("LLM attempt 1 failed: %s. Retrying in 2s.", e)
                            time.sleep(2)
                            continue
                        error = f"llm_timeout: {e}"
                        logger.error("LLM attempt 2 failed: %s", e)

                # If LLM failed completely, break out of the turn loop
                if response is None or not response.choices:
                    break

                choice = response.choices[0]
                msg = choice.message
                content = msg.content or ""
                finish_reason = choice.finish_reason
                final_finish_reason = finish_reason
                final_content = content

                # Token usage accumulation
                if response.usage:
                    total_prompt_tokens += response.usage.prompt_tokens or 0
                    total_completion_tokens += response.usage.completion_tokens or 0
                    total_total_tokens += response.usage.total_tokens or 0

                # ── No tool calls → terminal turn ────────────────
                if not msg.tool_calls:
                    turns.append({
                        "turn": turn,
                        "content": content[:500],
                        "tool_calls": [],
                        "tool_results": [],
                    })
                    break

                # ── Process tool calls for this turn ─────────────
                turn_tool_calls = []
                turn_tool_results = []

                # Append the assistant message (with tool_calls) to messages
                # so the LLM sees its own prior output on the next turn.
                assistant_msg = {"role": "assistant", "content": content}
                # Build tool_calls list for the message
                tc_list = []
                for tc in msg.tool_calls:
                    fn = tc.function
                    tc_list.append({
                        "id": tc.id if hasattr(tc, "id") and tc.id else f"call_{turn}_{fn.name}",
                        "type": "function",
                        "function": {
                            "name": fn.name,
                            "arguments": fn.arguments if isinstance(fn.arguments, str) else json.dumps(fn.arguments),
                        },
                    })
                assistant_msg["tool_calls"] = tc_list
                messages.append(assistant_msg)

                for tc in msg.tool_calls:
                    fn = tc.function
                    tc_id = tc.id if hasattr(tc, "id") and tc.id else f"call_{turn}_{fn.name}"
                    try:
                        args = json.loads(fn.arguments) if isinstance(fn.arguments, str) else fn.arguments
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    call_record = {"name": fn.name, "arguments": args}
                    turn_tool_calls.append(call_record)
                    all_tool_calls_raw.append(call_record)

                    # Execute via MCP dispatcher (hybrid) or direct adapter
                    result = self._execute_tool(fn.name, args)
                    result_record = {"tool": fn.name, "args": args, "result": result}
                    turn_tool_results.append(result_record)
                    all_tool_results.append(result_record)

                    # Append tool result as a message for the next LLM call
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(result, default=str),
                    })

                    # Check if propose_setpoint succeeded
                    if (fn.name == "propose_setpoint"
                            and isinstance(result, dict)
                            and result.get("status") == "pending"):
                        proposal_executed = True

                turns.append({
                    "turn": turn,
                    "content": content[:500],
                    "tool_calls": turn_tool_calls,
                    "tool_results": turn_tool_results,
                })

                # ── Early exit if proposal was submitted ─────────
                if proposal_executed:
                    break

        except Exception as e:
            error = str(e)
            logger.error("Reasoning error: %s", e, exc_info=True)

        # ── Policy update (Patch 1: mutation-safe) ───────────────
        old_policy = dict(self.current_policy)
        new_policy = {}
        for tr in all_tool_results:
            if (tr["tool"] == "propose_setpoint"
                    and isinstance(tr["result"], dict)
                    and tr["result"].get("status") == "pending"):
                zone = tr["args"].get("zone_name")
                h = tr["args"].get("heating")
                c = tr["args"].get("cooling")
                if zone and h is not None and c is not None:
                    new_policy[zone] = (float(h), float(c))

        # Only update policy if LLM actually made tool calls
        if all_tool_calls_raw:
            self.current_policy = new_policy
            self._policy_version += 1

        self._last_reasoning_ts = reasoning_ts
        self._last_reasoning_callback = callback_number

        # ── Build released zones (Patch 3: provenance) ───────────
        released_zones = {}
        if all_tool_calls_raw:
            for zone in old_policy:
                if zone not in new_policy:
                    released_zones[zone] = {
                        "release_reason": "zone_not_proposed",
                        "released_at_callback": callback_number,
                    }

        active_zones = {}
        for zone, (h, c) in self.current_policy.items():
            active_zones[zone] = {
                "heating": h,
                "cooling": c,
                "reasoning_wall_clock": reasoning_ts,
                "set_at_callback": callback_number,
                "policy_origin": "llm_reasoning",
            }

        # ── Trace entry ──────────────────────────────────────────
        wall_elapsed = time.time() - wall_start

        sim_ts = None
        if hasattr(snapshot, "simulated_timestamp"):
            ts = snapshot.simulated_timestamp
            sim_ts = {"month": ts[0], "day": ts[1], "hour": ts[2], "minute": ts[3]}

        entry = {
            "run_id": self._trace_logger.run_id,
            "cycle_callback": callback_number,
            "simulated_timestamp": sim_ts,
            "wall_clock_iso": reasoning_ts,
            "context_snapshot_callback": callback_number,
            "system_prompt_hash": self._prompt_hash,
            "llm_request": {
                "model": self._config.get("model", "qwen2.5:7b"),
                "temperature": self._config.get("temperature", 0.0),
                "message_count": len(messages),
            },
            "llm_response": {
                "content": (final_content or "")[:500],
                "tool_calls": all_tool_calls_raw,
                "finish_reason": final_finish_reason,
            },
            "tool_results": all_tool_results,
            "turns": turns,
            "turn_count": len(turns),
            "proposal_submitted": proposal_executed or any(
                tr["tool"] == "propose_setpoint" and
                isinstance(tr["result"], dict) and
                tr["result"].get("status") == "pending"
                for tr in all_tool_results
            ),
            "policy_state": {
                "policy_version": self._policy_version,
                "active_zones": active_zones,
                "released_zones": released_zones,
            },
            "metrics": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_total_tokens,
                "latency_seconds": round(wall_elapsed, 3),
            },
            "error": error,
        }

        self._trace_logger.log_cycle(entry)

    def _execute_tool(self, name, arguments):
        """Execute a tool call via MCP dispatcher (hybrid) or direct adapter.

        LLM-generated tool calls go through MCP dispatcher for protocol
        compliance. Falls back to direct adapter if dispatcher unavailable.
        """
        if self._mcp_dispatcher is not None:
            return self._mcp_dispatcher.call_tool(name, arguments)

        # Direct adapter fallback
        method = getattr(self._adapter, name, None)
        if method is None:
            return {"error": "unknown_tool", "name": name}
        try:
            return method(**arguments)
        except Exception as e:
            return {"error": "tool_error", "message": str(e)}

    def _build_openai_tools(self):
        """Convert adapter tool manifest to OpenAI function-calling format."""
        tools = self._adapter.list_tools()
        openai_tools = []
        for tool in tools:
            properties = {}
            required = []
            for arg in tool.get("arguments", []):
                prop = {}
                atype = arg.get("type", "string")
                if atype == "integer":
                    prop["type"] = "integer"
                elif atype == "float":
                    prop["type"] = "number"
                else:
                    prop["type"] = "string"
                if "default" in arg:
                    prop["default"] = arg["default"]
                properties[arg["name"]] = prop
                if arg.get("required", False):
                    required.append(arg["name"])

            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return openai_tools
