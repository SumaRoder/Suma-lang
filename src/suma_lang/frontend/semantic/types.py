"""Pure type-name string helpers used by the semantic analyzer.

These functions all operate on the textual representation of types
(``"R<Int, Str>"``, ``"Function<Int,Str,Bool>"``, ``"List<Int>"`` and so on)
and have no dependency on the rest of the analyzer state, which is why they
live here rather than as methods on :class:`Analyzer`.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from suma_lang.frontend.parser.ast_nodes import Param

ERROR_TYPE = "<error>"


@lru_cache(maxsize=8192)
def normalize_type_name(type_name: str | None) -> str | None:
    if type_name is None:
        return None
    if type_name == "Result":
        return "R"
    if type_name.startswith("Result<"):
        return "R<" + type_name[len("Result<") :]
    return type_name


def nullable_type(inner: str | None) -> str | None:
    inner = normalize_type_name(inner)
    if inner is None:
        return None
    if inner == "Null" or base_type(inner) == "Nullable":
        return inner
    return f"Nullable<{inner}>"


@lru_cache(maxsize=8192)
def nullable_inner_type(type_name: str | None) -> str | None:
    if base_type(type_name) != "Nullable":
        return None
    args = split_type_args(type_name)
    return args[0] if args else None


@lru_cache(maxsize=8192)
def base_type(type_name: str | None) -> str | None:
    type_name = normalize_type_name(type_name)
    if type_name is None:
        return None
    if "<" not in type_name:
        return type_name
    return type_name.split("<", 1)[0]


def split_type_args(type_name: str | None) -> list[str]:
    return list(_split_type_args_tuple(type_name))


@lru_cache(maxsize=8192)
def _split_type_args_tuple(type_name: str | None) -> tuple[str, ...]:
    type_name = normalize_type_name(type_name)
    if type_name is None or "<" not in type_name or not type_name.endswith(">"):
        return ()
    inner = type_name[type_name.index("<") + 1 : -1]
    args: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(inner):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(inner[start:index])
            start = index + 1
    if inner:
        args.append(inner[start:])
    return tuple(args)


@lru_cache(maxsize=8192)
def result_ok_type(type_name: str | None) -> str | None:
    base = base_type(type_name)
    args = split_type_args(type_name)
    if base in ("R", "Ok") and args:
        return args[0]
    if base == "Ok":
        return None
    return None


@lru_cache(maxsize=8192)
def result_err_type(type_name: str | None) -> str | None:
    base = base_type(type_name)
    args = split_type_args(type_name)
    if base == "R" and len(args) >= 2:
        return args[1]
    if base == "Err" and args:
        return args[0]
    if base == "Err":
        return None
    return None


def function_arg_types(type_name: str | None) -> list[str]:
    return list(_function_arg_types_tuple(type_name))


@lru_cache(maxsize=8192)
def _function_arg_types_tuple(type_name: str | None) -> tuple[str, ...]:
    if base_type(type_name) != "Function":
        return ()
    args = split_type_args(type_name)
    return tuple(args[:-1]) if args else ()


@lru_cache(maxsize=8192)
def function_return_type(type_name: str | None) -> str | None:
    if base_type(type_name) != "Function":
        return None
    args = split_type_args(type_name)
    return args[-1] if args else None


def lambda_type(params: Sequence[Param], return_type: str | None, result_type: str | None) -> str:
    arg_types = [normalize_type_name(param.type_annotation) or "Any" for param in params]
    resolved_return = normalize_type_name(return_type or result_type) or "Null"
    return f"Function<{','.join([*arg_types, resolved_return])}>"


@lru_cache(maxsize=8192)
def erase_type(type_name: str | None) -> str | None:
    type_name = normalize_type_name(type_name)
    if type_name is None:
        return None
    return base_type(type_name)


@lru_cache(maxsize=8192)
def is_error_type(type_name: str | None) -> bool:
    type_name = normalize_type_name(type_name)
    if type_name is None:
        return False
    if type_name == ERROR_TYPE:
        return True
    return any(is_error_type(arg) for arg in split_type_args(type_name))


def substitute_type(type_name: str | None, mapping: dict[str, str | None]) -> str | None:
    type_name = normalize_type_name(type_name)
    if type_name is None:
        return None
    if type_name in mapping:
        return mapping[type_name] if mapping[type_name] is not None else ERROR_TYPE
    args = split_type_args(type_name)
    if not args:
        return type_name
    base = base_type(type_name) or type_name
    substituted = [substitute_type(arg, mapping) or arg for arg in args]
    return f"{base}<{','.join(substituted)}>"
