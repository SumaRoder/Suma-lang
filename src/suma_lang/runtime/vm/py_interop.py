"""Bridge between Suma values and host Python objects.

These helpers are pulled out of ``VM`` so they can be reused without going
through a method dispatch — they only need ``vm`` when constructing a
:class:`SumaCallable` for a lambda argument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from suma_lang.runtime.vm.errors import VMError
from suma_lang.runtime.vm.values import (
    SumaCallable,
    SumaLambda,
    SumaPyObject,
    _from_python_value,
    _to_python_value,
)

if TYPE_CHECKING:
    from suma_lang.runtime.vm.vm import VM


def python_member(obj: SumaPyObject, name: str) -> Any:
    value = obj.value
    try:
        if isinstance(value, dict) and name in value:
            return _from_python_value(value[name])
        return _from_python_value(getattr(value, name))
    except AttributeError as exc:
        raise VMError(f"No Python member '{name}' on {type(value).__name__}") from exc


def python_index(obj: SumaPyObject, index: Any) -> Any:
    value = obj.value
    py_index = _to_python_value(index)
    try:
        return _from_python_value(value[py_index])
    except Exception as exc:
        raise VMError(f"Cannot index Python object {type(value).__name__}: {exc}") from exc


def python_slice(obj: SumaPyObject, start: Any, end: Any) -> Any:
    value = obj.value
    try:
        return _from_python_value(value[_to_python_value(start) : _to_python_value(end)])
    except Exception as exc:
        raise VMError(f"Cannot slice Python object {type(value).__name__}: {exc}") from exc


def call_python(vm: VM, callee: SumaPyObject, args: list) -> Any:
    func = callee.value
    if not callable(func):
        raise VMError(f"Python object {type(func).__name__} is not callable")
    py_args = [
        _to_python_value(SumaCallable(vm, arg, "<arg>") if isinstance(arg, SumaLambda) else arg)
        for arg in args
    ]
    try:
        return _from_python_value(func(*py_args))
    except Exception as exc:
        name = getattr(func, "__name__", type(func).__name__)
        raise VMError(f"Python call '{name}' failed: {exc}") from exc
