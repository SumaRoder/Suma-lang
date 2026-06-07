"""Scope-tree management for the semantic analyzer.

Owns the live ``Scope`` chain (global scope at the root, blocks/functions/
classes pushed on top) and the small amount of state that goes with it:
local-slot numbering, the implicit-shadow diagnostic, and the synthetic
match-arm scope counter that the analyzer uses to suppress false
shadow warnings on expression-bodied match arms.

The class is intentionally a plain object — no dataclass, no caching —
because every ``Analyzer.analyze`` call constructs a fresh resolver.
"""

from __future__ import annotations

from suma_lang.frontend.lexer.token_types import TokenInfo
from suma_lang.frontend.semantic.symbol_table import Scope, Symbol


class ScopeResolver:
    def __init__(self) -> None:
        self.global_scope: Scope = Scope(parent=None, scope_type="global")
        self.current_scope: Scope = self.global_scope
        self._slot_counter: int = 0
        # Synthetic scopes — pushed by the analyzer purely to bind a
        # match-arm-local `it` without leaking — should not trigger the
        # implicit-shadow diagnostic, because the compiler does not push
        # a scope there. The counter is incremented while inside such a
        # scope and inspected by ``check_implicit_shadow``.
        self._synthetic_depth: int = 0

    def next_slot(self) -> int:
        s = self._slot_counter
        self._slot_counter += 1
        return s

    def push(self, scope_type: str = "block", class_name: str | None = None) -> Scope:
        self.current_scope = Scope(
            parent=self.current_scope, scope_type=scope_type, class_name=class_name
        )
        return self.current_scope

    def pop(self) -> None:
        if self.current_scope.parent is not None:
            self.current_scope = self.current_scope.parent

    def enter_synthetic(self) -> None:
        self._synthetic_depth += 1

    def leave_synthetic(self) -> None:
        self._synthetic_depth -= 1

    def in_synthetic_scope(self) -> bool:
        return self._synthetic_depth > 0

    def resolve_outer(self, name: str) -> Symbol | None:
        if self.current_scope.parent is None:
            return None
        return self.current_scope.parent.resolve(name)

    def implicit_shadow_target(self, name: str) -> Symbol | None:
        """Return the outer binding that a bare ``name = expr`` would shadow.

        Returns ``None`` when the assignment is in a top-level, function-, or
        class-introducing scope (where re-declarations are explicitly
        allowed), when we are in a synthetic match-arm scope, or when no
        outer var/param is shadowed.
        """
        if self.current_scope.scope_type in ("global", "function", "class"):
            return None
        if self.in_synthetic_scope():
            return None
        outer = self.resolve_outer(name)
        if outer is None or outer.kind not in ("var", "param"):
            return None
        return outer


def format_location(info: TokenInfo | None) -> str:
    return f"{info.file or '<unknown>'}:{info.line}:{info.column}: " if info else "<program>:0:0: "
