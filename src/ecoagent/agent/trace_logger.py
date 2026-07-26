"""Agent Trace Logger — append-only JSONL writer for LLM reasoning traces.

Each line is one JSON object representing a single agent reasoning cycle,
including policy provenance (Patch 3) for attribution and evaluation.
"""

import json
from pathlib import Path


class AgentTraceLogger:
    """Appends structured reasoning traces to a JSONL file."""

    def __init__(self, output_dir, run_id):
        """Create output directory and open trace file.

        Args:
            output_dir: Directory for trace file. Created if missing.
            run_id: Run identifier included in every trace entry.
        """
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id
        self._log_path = self._output_dir / "trace.jsonl"
        self._file = open(self._log_path, "a", encoding="utf-8")

    def log_cycle(self, entry):
        """Serialize entry as JSON and append one line.

        Args:
            entry: dict conforming to the trace entry schema.
                   Must include ``run_id``, ``cycle_callback``,
                   ``policy_state`` (with provenance), and other fields.
        """
        line = json.dumps(entry, default=str, ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self):
        """Close file handle. Safe to call multiple times."""
        if self._file and not self._file.closed:
            self._file.close()

    @property
    def log_path(self):
        """Return Path to the trace file."""
        return self._log_path

    @property
    def run_id(self):
        """Return the run identifier."""
        return self._run_id
