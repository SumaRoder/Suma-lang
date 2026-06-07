from __future__ import annotations

from suma_lang.frontend.semantic.type_repr import (
    ANY,
    ERROR,
    INT,
    STR,
    Type,
    format_type,
    parse_type,
)
from suma_lang.frontend.semantic.types import (
    base_type,
    function_arg_types,
    function_return_type,
    nullable_inner_type,
    nullable_type,
    result_err_type,
    result_ok_type,
    split_type_args,
    substitute_type,
)


def test_primitive_roundtrip():
    assert parse_type("Int") == INT
    assert parse_type("Str") == STR
    assert parse_type("Any") == ANY
    assert format_type(INT) == "Int"
    assert format_type(None) is None
    assert parse_type(None) is None


def test_generic_roundtrip():
    t = parse_type("R<Int,Str>")
    assert t == Type("R", (INT, STR))
    assert str(t) == "R<Int,Str>"


def test_result_alias_normalizes_to_R():
    assert parse_type("Result").base == "R"
    assert parse_type("Result<Int,Str>") == Type("R", (INT, STR))


def test_nullable_marker():
    t = parse_type("Int?")
    assert t == Type("Nullable", (INT,))
    assert str(t) == "Nullable<Int>"


def test_nested_generics():
    t = parse_type("Function<List<Int>,R<Str,Bool>>")
    assert t == Type(
        "Function",
        (
            Type("List", (INT,)),
            Type("R", (STR, Type("Bool"))),
        ),
    )


def test_whitespace_tolerated():
    assert parse_type("R<Int, Str>") == Type("R", (INT, STR))


def test_string_helpers_still_work():
    # The string-facing API is the live surface; check it agrees with the ADT.
    assert base_type("R<Int,Str>") == "R"
    assert split_type_args("R<Int,Str>") == ["Int", "Str"]
    assert result_ok_type("R<Int,Str>") == "Int"
    assert result_err_type("R<Int,Str>") == "Str"
    assert function_arg_types("Function<Int,Str,Bool>") == ["Int", "Str"]
    assert function_return_type("Function<Int,Str,Bool>") == "Bool"


def test_nullable_helpers():
    assert nullable_type("Int") == "Nullable<Int>"
    assert nullable_type("Null") == "Null"
    assert nullable_type(None) is None
    assert nullable_inner_type("Nullable<Int>") == "Int"
    assert nullable_inner_type("Int") is None


def test_substitute_replaces_leaf_type_params():
    assert substitute_type("List<T>", {"T": "Int"}) == "List<Int>"
    assert substitute_type("R<T,E>", {"T": "Int", "E": "Str"}) == "R<Int,Str>"


def test_substitute_replaces_nested_type_params():
    assert substitute_type("Function<T,List<T>>", {"T": "Int"}) == "Function<Int,List<Int>>"


def test_substitute_missing_param_returns_error_marker():
    # The string layer used <error> to signal "type parameter unresolved";
    # the ADT path preserves that sentinel.
    assert substitute_type("List<T>", {"T": None}) == "List<<error>>"


def test_error_constant_stable():
    assert ERROR.base == "<error>"
    assert format_type(ERROR) == "<error>"
