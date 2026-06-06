"""Runtime-overload resolution for Suma.

Suma supports multiple functions / methods sharing the same name and
discriminated by argument types. This module owns the scoring logic. The
:class:`VM` class still drives the actual call — it provides
``program.functions`` and dispatches to ``_call_function_index`` /
``_call_lambda`` — but the type checks live here as pure functions for
testability and clarity.
"""

from __future__ import annotations

from typing import Any

from suma_lang.backend.codegen.opcodes import Function
from suma_lang.runtime.vm.errors import VMError
from suma_lang.runtime.vm.values import (
    SumaCallable,
    SumaEnum,
    SumaErr,
    SumaLambda,
    SumaList,
    SumaObject,
    SumaOk,
    SumaOverload,
    SumaPyObject,
    SumaRange,
    SumaTuple,
)


def base_type(type_name: str | None) -> str | None:
    if type_name is None or "<" not in type_name:
        return type_name
    return type_name.split("<", 1)[0]


def runtime_type_name(value: Any) -> str:
    if value is None:
        return "Null"
    if type(value) is bool:
        return "Bool"
    if type(value) is int:
        return "Int"
    if type(value) is float:
        return "Float"
    if isinstance(value, str):
        return "Str"
    if isinstance(value, SumaList):
        return "List"
    if isinstance(value, SumaTuple):
        return "Tuple"
    if isinstance(value, SumaRange):
        return "Range"
    if isinstance(value, SumaOk):
        return "Ok"
    if isinstance(value, SumaErr):
        return "Err"
    if isinstance(value, SumaEnum):
        return value.enum_name
    if isinstance(value, SumaObject):
        return value.class_name
    if isinstance(value, SumaPyObject):
        return "PyObject"
    if isinstance(value, (SumaLambda, SumaOverload, SumaCallable)):
        return "Function"
    return type(value).__name__


def score_overload_arg(
    expected: str | None,
    value: Any,
    type_params: list[str],
    bindings: dict[str, str],
) -> int | None:
    if expected is None or expected == "Any":
        return 1
    if expected in type_params:
        actual = runtime_type_name(value)
        bound = bindings.get(expected)
        if bound is None:
            bindings[expected] = actual
            return 2
        return 2 if bound == actual else None
    expected_base = base_type(expected)
    actual = runtime_type_name(value)
    if expected_base == actual:
        return 4
    if expected_base == "Float" and actual == "Int":
        return 2
    if expected_base == "R" and actual in ("Ok", "Err"):
        return 2
    return None


def select_overload(candidates: list[int], args: list[Any], functions: list[Function]) -> int:
    matches: list[tuple[int, int]] = []
    for func_idx in candidates:
        fn = functions[func_idx]
        if fn.arity != len(args):
            continue
        bindings: dict[str, str] = {}
        score = 0
        param_types = fn.param_types or [None] * fn.arity
        for expected, value in zip(param_types, args, strict=False):
            arg_score = score_overload_arg(expected, value, fn.type_params, bindings)
            if arg_score is None:
                break
            score += arg_score
        else:
            matches.append((score, func_idx))
    if not matches:
        arg_types = [runtime_type_name(arg) for arg in args]
        raise VMError(f"No overload matches runtime argument types {arg_types}")
    matches.sort(reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        arg_types = [runtime_type_name(arg) for arg in args]
        raise VMError(f"Ambiguous overload for runtime argument types {arg_types}")
    return matches[0][1]
