from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Symbol:
    name: str
    type_name: Optional[str]
    kind: str  # "var", "func", "class", "param", "builtin"
    decl: object = None  # reference to AST node
    is_pub: bool = False
    index: int = 0  # slot index in VM


@dataclass
class Scope:
    parent: Optional[Scope]
    symbols: dict[str, Symbol] = field(default_factory=dict)
    scope_type: str = "block"  # "global", "function", "class", "block"
    class_name: Optional[str] = None

    def define(self, sym: Symbol) -> Optional[str]:
        """Define a symbol. Returns error message if already defined."""
        if sym.name in self.symbols:
            return f"'{sym.name}' is already defined in this scope"
        self.symbols[sym.name] = sym
        return None

    def resolve(self, name: str) -> Optional[Symbol]:
        """Resolve a symbol walking up the scope chain."""
        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None

    def resolve_local(self, name: str) -> Optional[Symbol]:
        """Resolve in current scope only."""
        return self.symbols.get(name)
