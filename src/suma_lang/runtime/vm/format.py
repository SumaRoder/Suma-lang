"""Canonical string-formatting for Suma runtime values.

`_format_value` is the single authority used by the ``PRINT`` opcode, the
``str()`` builtin, panic / assertion messages, and the slow path of string
concatenation. ``_to_str_fast`` is a hot-path stub that short-circuits the
most common primitive types before falling through to ``_format_value``.
"""

from __future__ import annotations

from typing import Any

from suma_lang.runtime.vm.values import (
    SumaCallable,
    SumaEnum,
    SumaErr,
    SumaList,
    SumaObject,
    SumaOk,
    SumaOverload,
    SumaPyObject,
    SumaRange,
    SumaTuple,
    _py_repr,
)

_isinstance = isinstance


def _format_value(val: Any) -> str:
    """Canonical string representation of a Suma runtime value."""
    if val is None:
        return "null"
    if _isinstance(val, bool):
        return "true" if val else "false"
    if _isinstance(val, str):
        return val
    if _isinstance(val, (int, float)):
        return str(val)
    if _isinstance(val, SumaList):
        return val.__repr__()
    if _isinstance(val, SumaTuple):
        return val.__repr__()
    if _isinstance(val, SumaRange):
        return val.__repr__()
    if _isinstance(val, SumaOk):
        return val.__repr__()
    if _isinstance(val, SumaErr):
        return val.__repr__()
    if _isinstance(val, SumaEnum):
        return val.__repr__()
    if _isinstance(val, SumaObject):
        return f"{val.class_name} instance"
    if _isinstance(val, SumaOverload):
        return repr(val)
    if _isinstance(val, SumaCallable):
        return repr(val)
    if _isinstance(val, SumaPyObject):
        return _py_repr(val.value)
    return str(val)


def _to_str_fast(val: Any) -> str:
    """Hot-path string conversion: short-circuits the most common types."""
    if _isinstance(val, str):
        return val
    if val is None:
        return "null"
    if _isinstance(val, bool):
        return "true" if val else "false"
    if _isinstance(val, int):
        return str(val)
    return _format_value(val)
