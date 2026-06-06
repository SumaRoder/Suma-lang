"""Built-in functions exposed to Suma programs.

Each builtin takes a single ``args`` list and returns the result (or ``None``).
They are pure with respect to the VM — they only touch their arguments —
which is why they can live outside the ``VM`` class.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

from suma_lang.runtime.vm.errors import VMError
from suma_lang.runtime.vm.format import _format_value
from suma_lang.runtime.vm.values import (
    SumaCallable,
    SumaEnum,
    SumaErr,
    SumaLambda,
    SumaList,
    SumaObject,
    SumaOk,
    SumaPyObject,
    SumaRange,
    SumaTuple,
)


def builtin_print(args: list) -> None:
    print(*(_format_value(a) for a in args))
    return None


def builtin_str(args: list) -> str:
    return _format_value(args[0])


def builtin_int(args: list) -> int:
    val = args[0]
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        return int(val)
    raise VMError(f"Cannot convert {type(val)} to Int")


def builtin_float(args: list) -> float:
    val = args[0]
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return float(val)
    raise VMError(f"Cannot convert {type(val)} to Float")


def builtin_bool(args: list) -> bool:
    val = args[0]
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, int):
        return val != 0
    if isinstance(val, str):
        return len(val) > 0
    return True


def builtin_list(args: list) -> SumaList:
    return SumaList(list(args))


def builtin_unwrap(args: list) -> Any:
    val = args[0]
    if isinstance(val, SumaOk):
        return val.value
    raise VMError(f"Unwrap on Err: {val}")


def builtin_unwrap_or(args: list) -> Any:
    val, default = args[0], args[1]
    if isinstance(val, SumaOk):
        return val.value
    return default


def builtin_panic(args: list) -> None:
    raise VMError(f"Panic: {_format_value(args[0])}")


def builtin_assert(args: list) -> None:
    cond = args[0]
    msg = _format_value(args[1]) if len(args) > 1 else "Assertion failed"
    if not cond:
        raise VMError(f"Assert: {msg}")


def builtin_len(args: list) -> int:
    val = args[0]
    if isinstance(val, SumaList):
        return len(val.items)
    if isinstance(val, SumaTuple):
        return len(val.items)
    if isinstance(val, SumaRange):
        return len(val)
    if isinstance(val, str):
        return len(val)
    raise VMError(f"len() not supported for {type(val)}")


def builtin_typeof(args: list) -> str:
    val = args[0]
    if val is None:
        return "Null"
    if isinstance(val, bool):
        return "Bool"
    if isinstance(val, int):
        return "Int"
    if isinstance(val, float):
        return "Float"
    if isinstance(val, str):
        return "Str"
    if isinstance(val, SumaList):
        return "List"
    if isinstance(val, SumaTuple):
        return "Tuple"
    if isinstance(val, SumaRange):
        return "Range"
    if isinstance(val, SumaOk):
        return "R"
    if isinstance(val, SumaErr):
        return "R"
    if isinstance(val, SumaEnum):
        return val.enum_name
    if isinstance(val, SumaObject):
        return val.class_name
    if isinstance(val, (SumaCallable, SumaLambda)):
        return "Function"
    if isinstance(val, SumaPyObject):
        if isinstance(val.value, ModuleType):
            return "PyModule"
        if callable(val.value):
            return "PyCallable"
        return "PyObject"
    return "Unknown"


def builtin_is_type(args: list) -> bool:
    return builtin_typeof([args[0]]) == args[1]


def builtin_parseint(args: list) -> Any:
    try:
        return SumaOk(int(args[0]))
    except (ValueError, TypeError) as e:
        return SumaErr(str(e))


def builtin_list_add(args: list) -> None:
    lst, val = args[0], args[1]
    if isinstance(lst, SumaList):
        lst.items.append(val)
    return None


def builtin_list_get(args: list) -> Any:
    lst, idx = args[0], args[1]
    if isinstance(lst, SumaList) and isinstance(idx, int):
        return lst.items[idx]
    raise VMError("get() requires List and Int")


def build_builtin_registry() -> dict[str, Any]:
    """Return the name → callable map registered on every VM instance."""
    return {
        "print": builtin_print,
        "to_str": builtin_str,
        "to_int": builtin_int,
        "to_float": builtin_float,
        "to_bool": builtin_bool,
        "List": builtin_list,
        "Ok": lambda args: SumaOk(args[0]),
        "Err": lambda args: SumaErr(args[0]),
        "is_ok": lambda args: isinstance(args[0], SumaOk),
        "is_err": lambda args: isinstance(args[0], SumaErr),
        "unwrap": builtin_unwrap,
        "unwrap_or": builtin_unwrap_or,
        "panic": builtin_panic,
        "assert": builtin_assert,
        "len": builtin_len,
        "type_of": builtin_typeof,
        "__suma_is_type": builtin_is_type,
        "parse_int": builtin_parseint,
        "abs": lambda args: abs(args[0]),
        "max": lambda args: max(args[0], args[1]),
        "min": lambda args: min(args[0], args[1]),
        "pow": lambda args: args[0] ** args[1],
        "add": builtin_list_add,
        "size": builtin_len,
        "get": builtin_list_get,
    }
