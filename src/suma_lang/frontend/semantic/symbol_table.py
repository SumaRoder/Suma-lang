from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from suma_lang.frontend.parser.ast_nodes import (
        ClassDecl,
        FunctionDecl,
        GetterDecl,
        ImportDecl,
        Param,
        SetterDecl,
        VarDecl,
    )

    SymbolDecl: TypeAlias = (
        ClassDecl | FunctionDecl | GetterDecl | ImportDecl | Param | SetterDecl | VarDecl | str
    )
else:
    SymbolDecl = object


@dataclass
class Symbol:
    name: str
    type_name: str | None
    kind: str  # "var", "func", "class", "param", "builtin"
    decl: SymbolDecl | None = None  # reference to AST node
    is_pub: bool = False
    index: int = 0  # slot index in VM


@dataclass
class Scope:
    parent: Scope | None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    scope_type: str = "block"  # "global", "function", "class", "block"
    class_name: str | None = None

    def define(self, sym: Symbol) -> str | None:
        """Define a symbol. Returns error message if already defined."""
        if sym.name in self.symbols:
            return f"'{sym.name}' is already defined in this scope"
        self.symbols[sym.name] = sym
        return None

    def resolve(self, name: str) -> Symbol | None:
        """Resolve a symbol walking up the scope chain."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None

    def resolve_local(self, name: str) -> Symbol | None:
        """Resolve in current scope only."""
        return self.symbols.get(name)
