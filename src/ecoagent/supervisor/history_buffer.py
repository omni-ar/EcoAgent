from collections import deque


class HistoryBuffer:
    def __init__(self, max_size=96):
        self._buffer = deque(maxlen=max_size)
        self._max_size = max_size

    def append(self, snapshot):
        self._buffer.append(snapshot)

    def latest(self):
        if not self._buffer:
            return None
        return self._buffer[-1]

    def get(self, offset):
        if offset < 0 or offset >= len(self._buffer):
            return None
        return self._buffer[-(offset + 1)]

    def get_range(self, start, count):
        result = []
        for i in range(start, start + count):
            entry = self.get(i)
            if entry is None:
                break
            result.append(entry)
        return result

    def size(self):
        return len(self._buffer)

    def capacity(self):
        return self._max_size

    def clear(self):
        self._buffer.clear()
