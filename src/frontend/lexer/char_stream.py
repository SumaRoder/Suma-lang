from typing import Optional


class CharStream:
    def __init__(self, src: str) -> None:
        self._src = src
        self._len = len(src)
        self._idx = 0
        self.line = 1
        self.column = 1

        self._line_starts = [0]
        for i, ch in enumerate(src):
            if ch == "\n":
                self._line_starts.append(i + 1)

    def has_next(self) -> bool:
        return self._idx < self._len

    def peek(self) -> str:
        return self._src[self._idx] if self.has_next() else "\0"

    def peek_at(self, offset: int) -> str:
        idx = self._idx + offset
        return self._src[idx] if idx < self._len else "\0"

    def next(self) -> str:
        if not self.has_next():
            return "\0"

        c = self._src[self._idx]
        self._idx += 1

        if c == "\n":
            self.line += 1
            self.column = 1
        elif c == "\r":
            if self.has_next() and self.peek() == "\n":
                self._idx += 1
            self.line += 1
            self.column = 1
        else:
            self.column += 1

        return c

    def get_source_line(self, target_line: int) -> Optional[str]:
        line_index = target_line - 1
        if line_index < 0 or line_index >= len(self._line_starts):
            return None

        start_pos = self._line_starts[line_index]
        end_pos = (
            self._line_starts[line_index + 1]
            if line_index + 1 < len(self._line_starts)
            else self._len
        )
        return self._src[start_pos:end_pos].rstrip("\n\r")
