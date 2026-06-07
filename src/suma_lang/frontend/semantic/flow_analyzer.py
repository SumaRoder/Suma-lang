"""Flow-sensitive semantic analysis state.

This component owns loop depth and transient type narrowings. Analyzer still
decides *when* to enter loop/narrowing contexts; the mutable stacks live here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from suma_lang.frontend.parser.ast_nodes import BinaryExpr, Expr, Identifier, NullLiteral
from suma_lang.frontend.semantic.symbol_table import Symbol
from suma_lang.frontend.semantic.types import nullable_inner_type


class FlowAnalyzer:
    def __init__(self, analyzer: Any) -> None:
        object.__setattr__(self, "_analyzer", analyzer)
        self.loop_depth = 0
        self.narrowed_types: list[dict[int, str | None]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._analyzer, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_analyzer", "loop_depth", "narrowed_types"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._analyzer, name, value)

    @contextmanager
    def loop(self) -> Iterator[None]:
        self.loop_depth += 1
        try:
            yield
        finally:
            self.loop_depth -= 1

    def _push_narrowing(self, narrowings: dict[int, str | None] | None = None) -> None:
        self.narrowed_types.append(dict(narrowings or {}))

    def _pop_narrowing(self) -> None:
        if self.narrowed_types:
            self.narrowed_types.pop()

    def _narrowed_type(self, sym: Symbol) -> str | None:
        key = id(sym)
        for scope in reversed(self.narrowed_types):
            if key in scope:
                return scope[key]
        return None

    def _clear_narrowing(self, sym: Symbol) -> None:
        key = id(sym)
        for scope in self.narrowed_types:
            scope.pop(key, None)

    def _condition_narrowings(
        self, condition: Expr
    ) -> tuple[dict[int, str | None], dict[int, str | None]]:
        if not isinstance(condition, BinaryExpr) or condition.op not in ("==", "!="):
            return {}, {}
        target = self._null_check_target(condition.left, condition.right)
        if target is None:
            target = self._null_check_target(condition.right, condition.left)
        if target is None:
            return {}, {}
        sym, inner_type = target
        not_null: dict[int, str | None] = {id(sym): inner_type}
        is_null: dict[int, str | None] = {id(sym): "Null"}
        return (is_null, not_null) if condition.op == "==" else (not_null, is_null)

    def _null_check_target(
        self, maybe_identifier: Expr, maybe_null: Expr
    ) -> tuple[Symbol, str] | None:
        if not isinstance(maybe_identifier, Identifier) or not isinstance(maybe_null, NullLiteral):
            return None
        sym = self.current_scope.resolve(maybe_identifier.name)
        if sym is None:
            return None
        inner_type = nullable_inner_type(self._narrowed_type(sym) or sym.type_name)
        if inner_type is None:
            return None
        return sym, inner_type
