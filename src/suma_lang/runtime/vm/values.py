"""Runtime value types for the Suma VM.

These classes are the in-memory representation of Suma values during
execution. They are kept intentionally small (with ``__slots__``) since the
interpreter creates large numbers of them per program run.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from suma_lang.runtime.vm.vm import VM


class SumaOk:
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"Ok({self.value!r})"


class SumaErr:
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"Err({self.value!r})"


class SumaList:
    __slots__ = ("items",)

    def __init__(self, items: list) -> None:
        self.items = items

    def __repr__(self) -> str:
        return f"List({', '.join(repr(i) for i in self.items)})"

    def __len__(self) -> int:
        return len(self.items)


class SumaTuple:
    __slots__ = ("items",)

    def __init__(self, items: list | tuple) -> None:
        self.items = tuple(items)

    def __repr__(self) -> str:
        return f"Tuple({', '.join(repr(i) for i in self.items)})"

    def __len__(self) -> int:
        return len(self.items)


class SumaRange:
    __slots__ = ("start", "end", "inclusive")

    def __init__(self, start: int, end: int, inclusive: bool = False) -> None:
        self.start = start
        self.end = end
        self.inclusive = inclusive

    def __len__(self) -> int:
        stop = self.end + (1 if self.inclusive else 0)
        return max(0, stop - self.start)

    def __getitem__(self, index: int) -> int:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self.start + index

    def __repr__(self) -> str:
        op = "..=" if self.inclusive else ".."
        return f"Range({self.start}{op}{self.end})"


class SumaObject:
    __slots__ = ("class_name", "fields")

    def __init__(self, class_name: str, fields: dict) -> None:
        self.class_name = class_name
        self.fields = fields

    def __repr__(self) -> str:
        return f"{self.class_name}({self.fields!r})"


class SumaEnum:
    __slots__ = ("enum_name", "variant_name", "value")

    def __init__(self, enum_name: str, variant_name: str, value: Any = None) -> None:
        self.enum_name = enum_name
        self.variant_name = variant_name
        self.value = value

    def __repr__(self) -> str:
        if self.value is None:
            return f"{self.enum_name}.{self.variant_name}"
        return f"{self.enum_name}.{self.variant_name}({self.value!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SumaEnum)
            and self.enum_name == other.enum_name
            and self.variant_name == other.variant_name
            and self.value == other.value
        )


class SumaLambda:
    __slots__ = ("func_idx", "closure")

    def __init__(self, func_idx: int, closure: list) -> None:
        self.func_idx = func_idx
        self.closure = closure

    def __repr__(self) -> str:
        return f"<lambda@{self.func_idx}>"


class SumaOverload:
    __slots__ = ("name", "candidates", "bound_this")

    def __init__(self, name: str, candidates: list[int], bound_this: Any = None) -> None:
        self.name = name
        self.candidates = candidates
        self.bound_this = bound_this

    def __repr__(self) -> str:
        return f"<overload {self.name}>"


class SumaCallable:
    __slots__ = ("vm", "value", "name", "arity", "python_callable")

    def __init__(self, vm: VM, value: Any, name: str = "<suma callable>") -> None:
        self.vm = vm
        self.value = value
        self.name = name
        self.arity = self._infer_arity()
        self.python_callable = self._make_python_callable()

    def _infer_arity(self) -> int:
        if isinstance(self.value, SumaLambda):
            fn = self.vm.program.functions[self.value.func_idx]
            return max(0, fn.arity)
        if isinstance(self.value, str) and self.value in self.vm._func_map:
            fn = self.vm.program.functions[self.vm._func_map[self.value]]
            return max(0, fn.arity)
        return 1

    def _invoke(self, args: list[Any]) -> Any:
        return _to_python_value(
            self.vm._call_value(self.value, [_from_python_value(arg) for arg in args])
        )

    def _make_python_callable(self) -> Callable[..., Any]:
        if 0 <= self.arity <= 32:
            params = ", ".join(f"arg{i}" for i in range(self.arity))
            args = ", ".join(f"arg{i}" for i in range(self.arity))
            body_args = f"[{args}]" if args else "[]"
            namespace: dict[str, Any] = {"invoke": self._invoke}
            exec(f"def callback({params}):\n    return invoke({body_args})", namespace)
            callback = namespace["callback"]
        else:

            def callback_any(*args: Any) -> Any:
                return self._invoke(list(args))

            callback = callback_any

        callback.__name__ = self.name.replace(".", "_").replace("<", "_").replace(">", "_")
        setattr(callback, "__suma_value__", self.value)  # noqa: B010 — dynamic attr
        return callback

    def __call__(self, *args: Any) -> Any:
        return self._invoke(list(args))

    def __repr__(self) -> str:
        return f"<suma callable {self.name}>"


class SumaPyObject:
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:
        return _py_repr(self.value)


def _py_repr(value: Any) -> str:
    if isinstance(value, ModuleType):
        return f"<py module {value.__name__}>"
    if callable(value):
        name = getattr(value, "__name__", type(value).__name__)
        return f"<py callable {name}>"
    return repr(value)


def _to_python_value(value: Any) -> Any:
    if isinstance(value, SumaPyObject):
        return value.value
    if isinstance(value, SumaCallable):
        return value.python_callable
    if isinstance(value, (SumaLambda, SumaOverload, str)):
        return value
    if isinstance(value, SumaList):
        return [_to_python_value(item) for item in value.items]
    if isinstance(value, SumaTuple):
        return tuple(_to_python_value(item) for item in value.items)
    if isinstance(value, SumaRange):
        return range(value.start, value.end + (1 if value.inclusive else 0))
    if isinstance(value, SumaOk):
        return {"ok": _to_python_value(value.value)}
    if isinstance(value, SumaErr):
        return {"err": _to_python_value(value.value)}
    if isinstance(value, SumaObject):
        return {key: _to_python_value(val) for key, val in value.fields.items()}
    if isinstance(value, SumaEnum):
        return {
            "enum": value.enum_name,
            "variant": value.variant_name,
            "value": _to_python_value(value.value),
        }
    return value


def _from_python_value(value: Any) -> Any:
    suma_value = getattr(value, "__suma_value__", None)
    if suma_value is not None:
        return suma_value
    if isinstance(
        value,
        (
            SumaPyObject,
            SumaCallable,
            SumaLambda,
            SumaOverload,
            SumaList,
            SumaTuple,
            SumaRange,
            SumaOk,
            SumaErr,
            SumaObject,
            SumaEnum,
        ),
    ):
        return value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return SumaList([_from_python_value(item) for item in value])
    if isinstance(value, tuple):
        return SumaTuple([_from_python_value(item) for item in value])
    return SumaPyObject(value)
