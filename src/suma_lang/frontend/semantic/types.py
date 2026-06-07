"""Type-name string helpers used by the semantic analyzer.

These functions operate on the textual representation of types
(``"R<Int, Str>"``, ``"Function<Int,Str,Bool>"``, ``"List<Int>"``) for
backwards compatibility with the rest of the analyzer and runtime.
Internally they delegate to :mod:`type_repr`, which carries a structured
:class:`Type` ADT — new code should prefer the ADT form directly because
it is hashable, pattern-matchable, and free of whitespace/normalization
quirks. The string layer will stay until the analyzer migration completes.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from suma_lang.frontend.parser.ast_nodes import Param
from suma_lang.frontend.semantic.type_repr import Type, format_type, parse_type

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
    parsed = parse_type(normalize_type_name(type_name))
    return parsed.base if parsed is not None else None


def split_type_args(type_name: str | None) -> list[str]:
    return list(_split_type_args_tuple(type_name))


@lru_cache(maxsize=8192)
def _split_type_args_tuple(type_name: str | None) -> tuple[str, ...]:
    parsed = parse_type(normalize_type_name(type_name))
    if parsed is None or not parsed.args:
        return ()
    return tuple(str(a) for a in parsed.args)


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
    if not mapping:
        return normalize_type_name(type_name)
    return _substitute_type_cached(type_name, tuple(sorted(mapping.items())))


@lru_cache(maxsize=8192)
def _substitute_type_cached(
    type_name: str | None, mapping_items: tuple[tuple[str, str | None], ...]
) -> str | None:
    parsed = parse_type(normalize_type_name(type_name))
    if parsed is None:
        return None
    mapping = dict(mapping_items)
    result = _substitute_node(parsed, mapping)
    return format_type(result)


def _substitute_node(node: Type, mapping: dict[str, str | None]) -> Type:
    # When the entire node matches a binding key (e.g. type-param "T"),
    # swap the whole subtree out so generic parameters substitute correctly.
    key = str(node)
    if key in mapping:
        replacement = mapping[key]
        if replacement is None:
            return Type(ERROR_TYPE)
        parsed = parse_type(replacement)
        return parsed if parsed is not None else Type(ERROR_TYPE)
    if not node.args:
        return node
    new_args = tuple(_substitute_node(arg, mapping) for arg in node.args)
    return Type(node.base, new_args)
