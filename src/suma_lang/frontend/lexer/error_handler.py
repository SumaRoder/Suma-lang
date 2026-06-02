class ErrorHandler:
    @staticmethod
    def report(info, reason: str, source_line: str | None = None) -> None:
        location = f"{info.file or '<unknown>'}:{info.line}:{info.column}"
        msg = f"[Error] {location} — {reason}"
        if source_line:
            msg += f"\n  | {source_line}"
        raise SyntaxError(msg)
