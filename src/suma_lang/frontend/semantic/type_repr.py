"""Algebraic representation of Suma types.

This module is the canonical home for the :class:`Type` data class — a
frozen, hashable tree mirroring the string form used elsewhere in the
semantic analyzer. The string layer lives in
:mod:`suma_lang.frontend.semantic.types`; new code should prefer the
algebraic form because it is structurally safe (no whitespace/normalization
quirks, no accidental string splitting) and composes with pattern matching.

The two representations are interconvertible:

    parse_type("R<Int, Str>")     # Type(base="R", args=(Int, Str))
    str(Type("R", (Int, Str)))     # "R<Int,Str>"

Both layers will be kept in sync as the migration progresses — the string
helpers in :mod:`.types` currently still drive the analyzer; converting
hot paths is tracked separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Type:
    """A type node: a base name plus zero or more generic arguments.

    Tuple types are encoded as ``Type("Tuple", (e1, e2, ...))``; nullable
    types as ``Type("Nullable", (inner,))``; Result/R as
    ``Type("R", (ok, err))``; Function as ``Type("Function", (a1, ..., an, ret))``.
    These conventions match the existing string form used by the analyzer.
    """

    base: str
    args: tuple[Type, ...] = ()

    def __str__(self) -> str:
        if not self.args:
            return self.base
        return f"{self.base}<{','.join(str(a) for a in self.args)}>"

    @property
    def is_generic(self) -> bool:
        return bool(self.args)


# Common primitives — kept as module-level constants so equality comparisons
# go through the dataclass __eq__ without re-allocating instances.
INT = Type("Int")
FLOAT = Type("Float")
STR = Type("Str")
BOOL = Type("Bool")
NULL = Type("Null")
ANY = Type("Any")
ERROR = Type("<error>")


def _normalize_base(name: str) -> str:
    return "R" if name == "Result" else name


@lru_cache(maxsize=8192)
def parse_type(text: str | None) -> Type | None:
    """Parse a type string into a :class:`Type` tree.

    Mirrors the textual form produced by ``Parser._parse_type_name`` /
    ``types.normalize_type_name``: whitespace is permitted around commas
    but not inside identifiers, and ``Result`` is normalized to ``R``.
    Returns ``None`` for ``None`` (preserving the existing string-helper
    convention of treating missing type info as ``None``).
    """
    if text is None:
        return None
    parsed, end = _parse(text, 0)
    # Trailing junk would mean we accepted a malformed type; the existing
    # string layer silently returns the original text in that case, so we
    # mirror that and surface the original as a base-only Type so callers
    # are not forced to handle yet another error path.
    if end < len(text):
        return Type(text)
    return parsed


def format_type(t: Type | None) -> str | None:
    """Render a :class:`Type` back into its canonical string form."""
    return None if t is None else str(t)


def _parse(text: str, index: int) -> tuple[Type, int]:
    start = index
    n = len(text)
    while index < n and (text[index].isalnum() or text[index] == "_"):
        index += 1
    base = _normalize_base(text[start:index])

    args: tuple[Type, ...] = ()
    if index < n and text[index] == "<":
        index += 1
        collected: list[Type] = []
        while index < n and text[index] != ">":
            # Allow optional whitespace between args.
            while index < n and text[index] == " ":
                index += 1
            arg, index = _parse(text, index)
            collected.append(arg)
            while index < n and text[index] == " ":
                index += 1
            if index < n and text[index] == ",":
                index += 1
                continue
            break
        if index < n and text[index] == ">":
            index += 1
        args = tuple(collected)

    if index < n and text[index] == "?":
        index += 1
        return Type("Nullable", (Type(base, args),)), index
    return Type(base, args), index
