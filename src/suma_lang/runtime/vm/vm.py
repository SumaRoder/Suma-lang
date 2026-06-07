"""Suma-lang Virtual Machine — executes .sumac bytecode."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from typing import Any

from suma_lang.backend.codegen.opcodes import Function, Op, ProgramBytecode
from suma_lang.frontend.imports.resolver import is_python_import_allowed
from suma_lang.runtime.vm.builtins import build_builtin_registry
from suma_lang.runtime.vm.errors import VMError
from suma_lang.runtime.vm.format import _format_value, _to_str_fast
from suma_lang.runtime.vm.overloads import select_overload
from suma_lang.runtime.vm.py_interop import (
    call_python,
    python_index,
    python_member,
    python_slice,
)
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
    _from_python_value,
    _to_python_value,
)

__all__ = [
    "VM",
    "VMError",
    "SumaOk",
    "SumaErr",
    "SumaList",
    "SumaTuple",
    "SumaRange",
    "SumaObject",
    "SumaLambda",
    "SumaOverload",
    "SumaCallable",
    "SumaEnum",
    "SumaPyObject",
]

_MISSING = object()


def _slot_count(func: Function) -> int:
    return max(func.locals_count, 1)


def _reset_slots(slots: list[Any], count: int) -> list[Any]:
    if len(slots) < count:
        slots.extend([None] * (count - len(slots)))
    elif len(slots) > count:
        del slots[count:]
    for index in range(count):
        slots[index] = None
    return slots


class Frame:
    __slots__ = ("func", "ip", "slots", "stack_base", "this", "it", "pending_push")

    def __init__(self, func: Function, stack_base: int, this: Any = None) -> None:
        self.func = func
        self.ip = 0
        self.slots: list[Any] = [None] * _slot_count(func)
        self.stack_base = stack_base
        self.this = this
        self.it = None
        self.pending_push: Any = None


_isinstance = isinstance


class OC:
    """Opcode int constants for match/case dispatch (must use dotted names)."""

    LOAD_CONST = int(Op.LOAD_CONST)
    LOAD_VAR = int(Op.LOAD_VAR)
    STORE_VAR = int(Op.STORE_VAR)
    LOAD_GLOBAL = int(Op.LOAD_GLOBAL)
    STORE_GLOBAL = int(Op.STORE_GLOBAL)
    CALL_GLOBAL = int(Op.CALL_GLOBAL)
    LOAD_FUNC = int(Op.LOAD_FUNC)
    LOAD_TRUE = int(Op.LOAD_TRUE)
    LOAD_FALSE = int(Op.LOAD_FALSE)
    LOAD_NULL = int(Op.LOAD_NULL)
    LOAD_THIS = int(Op.LOAD_THIS)
    LOAD_IT = int(Op.LOAD_IT)
    SET_IT = int(Op.SET_IT)
    POP = int(Op.POP)
    DUP = int(Op.DUP)
    ADD = int(Op.ADD)
    SUB = int(Op.SUB)
    MUL = int(Op.MUL)
    DIV = int(Op.DIV)
    MOD = int(Op.MOD)
    NEG = int(Op.NEG)
    BIT_AND = int(Op.BIT_AND)
    BIT_OR = int(Op.BIT_OR)
    BIT_XOR = int(Op.BIT_XOR)
    BIT_NOT = int(Op.BIT_NOT)
    SHL = int(Op.SHL)
    SHR = int(Op.SHR)
    NOT = int(Op.NOT)
    AND = int(Op.AND)
    OR = int(Op.OR)
    EQ = int(Op.EQ)
    NE = int(Op.NE)
    GT = int(Op.GT)
    LT = int(Op.LT)
    GE = int(Op.GE)
    LE = int(Op.LE)
    JUMP = int(Op.JUMP)
    JUMP_IF_FALSE = int(Op.JUMP_IF_FALSE)
    JUMP_IF_TRUE = int(Op.JUMP_IF_TRUE)
    CALL = int(Op.CALL)
    RETURN = int(Op.RETURN)
    MAKE_LIST = int(Op.MAKE_LIST)
    MAKE_RANGE = int(Op.MAKE_RANGE)
    MAKE_TUPLE = int(Op.MAKE_TUPLE)
    MAKE_OK = int(Op.MAKE_OK)
    MAKE_ERR = int(Op.MAKE_ERR)
    MAKE_ENUM = int(Op.MAKE_ENUM)
    INDEX = int(Op.INDEX)
    SLICE = int(Op.SLICE)
    MEMBER = int(Op.MEMBER)
    SET_MEMBER = int(Op.SET_MEMBER)
    SET_INDEX = int(Op.SET_INDEX)
    MAKE_OBJECT = int(Op.MAKE_OBJECT)
    MAKE_LAMBDA = int(Op.MAKE_LAMBDA)
    IS_OK = int(Op.IS_OK)
    IS_ERR = int(Op.IS_ERR)
    IS_ENUM_VARIANT = int(Op.IS_ENUM_VARIANT)
    UNWRAP_OK = int(Op.UNWRAP_OK)
    PRINT = int(Op.PRINT)
    NOP = int(Op.NOP)
    HALT = int(Op.HALT)
    JUMP_IF_VAR_CMP = int(Op.JUMP_IF_VAR_CMP)
    JUMP_IF_VAR_CONST_CMP = int(Op.JUMP_IF_VAR_CONST_CMP)
    INPLACE_VAR_VAR = int(Op.INPLACE_VAR_VAR)
    INPLACE_VAR_CONST = int(Op.INPLACE_VAR_CONST)
    TAIL_CALL_GLOBAL = int(Op.TAIL_CALL_GLOBAL)
    LOOP_GENERIC = int(Op.LOOP_GENERIC)


def _apply_binop_fast(op_code: int, a: Any, b: Any) -> Any:
    if op_code == OC.ADD:
        if _isinstance(a, int) and _isinstance(b, int):
            return a + b
        if _isinstance(a, str) or _isinstance(b, str):
            return _to_str_fast(a) + _to_str_fast(b)
        if _isinstance(a, SumaList) and _isinstance(b, SumaList):
            return SumaList(a.items + b.items)
        return a + b
    if op_code == OC.SUB:
        return a - b
    if op_code == OC.MUL:
        return a * b
    if op_code == OC.DIV:
        if b == 0:
            raise VMError("Division by zero")
        return a // b if _isinstance(a, int) and _isinstance(b, int) else a / b
    return a % b


def _compare_values(left: Any, right: Any, cmp_code: int) -> bool:
    if cmp_code == 0:
        return left == right
    if cmp_code == 1:
        return left != right
    if cmp_code == 2:
        return left > right
    if cmp_code == 3:
        return left < right
    if cmp_code == 4:
        return left >= right
    return left <= right


_CMP_METHODS = ("op_eq", "op_ne", "op_gt", "op_lt", "op_ge", "op_le")
_BINOP_METHODS = {
    OC.ADD: "op_add",
    OC.SUB: "op_sub",
    OC.MUL: "op_mul",
    OC.DIV: "op_div",
    OC.MOD: "op_mod",
}


class VM:
    _INITIAL_STACK_SIZE = 1024
    _STACK_HEADROOM = 64

    def __init__(self, program: ProgramBytecode) -> None:
        self.program = program
        self.stack: list[Any] = []
        self.frames: list[Frame] = []
        self.globals: dict[str, Any] = {}
        self._func_map: dict[str, int] = {}  # name -> function index
        self._frame_pool: list[Frame] = []
        self._frame_pool_idx: int = 0
        self._index_functions()
        self._init_builtins()
        self._init_python_imports()
        self._init_decorators()

    def _index_functions(self) -> None:
        self._func_map.clear()
        for i, fn in enumerate(self.program.functions):
            self._func_map[fn.name] = i

    def load_program(self, program: ProgramBytecode, *, reset_globals: bool = False) -> None:
        """Replace the executable program while keeping host-injected globals by default."""
        self.program = program
        self.stack.clear()
        self.frames.clear()
        self._frame_pool.clear()
        self._frame_pool_idx = 0
        if reset_globals:
            self.globals.clear()
        self._index_functions()
        self._init_builtins()
        self._init_python_imports()
        self._init_decorators()

    def inject(self, name: str, value: Any) -> None:
        """Set a host-provided global value for Suma code."""
        self.globals[name] = _from_python_value(value)

    def inject_many(self, values: dict[str, Any]) -> None:
        """Set multiple host-provided global values for Suma code."""
        for name, value in values.items():
            self.inject(name, value)

    def get_global(self, name: str, default: Any = _MISSING) -> Any:
        """Return a global value converted back to a host Python value."""
        if name in self.globals:
            return _to_python_value(self.globals[name])
        if default is not _MISSING:
            return default
        raise KeyError(name)

    def environment(self) -> dict[str, Any]:
        """Return a snapshot of host-visible Suma globals."""
        return {name: _to_python_value(value) for name, value in self.globals.items()}

    def _new_stack(self) -> list[Any]:
        return [None] * self._INITIAL_STACK_SIZE

    def _init_builtins(self) -> None:
        """Register built-in functions."""
        self._builtins: dict[str, Callable] = build_builtin_registry()

    def _init_python_imports(self) -> None:
        """Import host Python modules declared by `import "py:..."`."""
        for alias, module_name in self.program.py_imports.items():
            if not is_python_import_allowed(module_name):
                raise VMError(
                    f"Python import '{module_name}' is not allowed; "
                    "set SUMA_PY_IMPORTS to allow trusted modules"
                )
            old_dont_write_bytecode = sys.dont_write_bytecode
            try:
                sys.dont_write_bytecode = True
                self.globals[alias] = SumaPyObject(importlib.import_module(module_name))
            except Exception as exc:
                raise VMError(
                    f"Cannot import Python module '{module_name}' as '{alias}': {exc}"
                ) from exc
            finally:
                sys.dont_write_bytecode = old_dont_write_bytecode

    def _init_decorators(self) -> None:
        """Apply global function/class decorators before `main` starts."""
        if not self.program.decorators:
            return
        self.stack = self._new_stack()
        self._sp = 0
        saved_frames = self.frames
        self.frames = []
        try:
            for name, init_idx in self.program.decorators.items():
                result = self._call_function_index(init_idx, [])
                if result is not None:
                    self.globals[name] = result
        finally:
            self.frames = saved_frames
            self._sp = 0

    def _call_function_index(self, func_idx: int, args: list[Any]) -> Any:
        old_frame_pool_idx = self._frame_pool_idx
        fn = self.program.functions[func_idx]
        frame = self._alloc_frame(fn, 0)
        for i, arg in enumerate(args):
            if i < len(frame.slots):
                frame.slots[i] = arg
        old_frames = self.frames
        old_stack = self.stack
        old_sp = getattr(self, "_sp", 0)
        self.frames = [frame]
        self.stack = self._new_stack()
        self._sp = 0
        try:
            return self._execute()
        finally:
            self.frames = old_frames
            self.stack = old_stack
            self._sp = old_sp
            self._frame_pool_idx = old_frame_pool_idx

    def _call_lambda(self, callee: SumaLambda, args: list[Any]) -> Any:
        old_frame_pool_idx = self._frame_pool_idx
        fn = self.program.functions[callee.func_idx]
        frame = self._alloc_frame(fn, 0)
        for i, value in enumerate(callee.closure):
            if i < len(frame.slots):
                frame.slots[i] = value
        offset = len(callee.closure)
        for i, arg in enumerate(args):
            slot = i + offset
            if slot < len(frame.slots):
                frame.slots[slot] = arg
        if fn.is_method and callee.closure:
            frame.this = callee.closure[0]
        old_frames = self.frames
        old_stack = self.stack
        old_sp = getattr(self, "_sp", 0)
        self.frames = [frame]
        self.stack = self._new_stack()
        self._sp = 0
        try:
            return self._execute()
        finally:
            self.frames = old_frames
            self.stack = old_stack
            self._sp = old_sp
            self._frame_pool_idx = old_frame_pool_idx

    def _call_value(self, callee: Any, args: list[Any]) -> Any:
        if isinstance(callee, str):
            if callee in self.globals:
                callee = self.globals[callee]
            elif callee in self.program.overloads:
                return self._call_overload(
                    SumaOverload(callee, self.program.overloads[callee]), args
                )
            elif callee in self._func_map:
                return self._call_function_index(self._func_map[callee], args)
            elif callee in self._builtins:
                return self._builtins[callee](args)
            else:
                raise VMError(f"Undefined function: {callee}")
        if isinstance(callee, SumaLambda):
            if callee.func_idx == -1:
                obj = callee.closure[0] if callee.closure else None
                if isinstance(obj, SumaList):
                    if args:
                        obj.items.append(args[0])
                    return None
                raise VMError("Unknown special lambda")
            return self._call_lambda(callee, args)
        if isinstance(callee, SumaOverload):
            return self._call_overload(callee, args)
        if isinstance(callee, SumaPyObject):
            return call_python(self, callee, args)
        raise VMError(f"Cannot call {type(callee)}")

    def _decorate_bound_method(self, class_name: str, method_name: str, bound: SumaLambda) -> Any:
        init_idx = self.program.method_decorators.get(f"{class_name}.{method_name}")
        if init_idx is None:
            return bound
        return self._call_function_index(init_idx, [bound])

    def _select_overload(self, candidates: list[int], args: list[Any]) -> int:
        return select_overload(candidates, args, self.program.functions)

    def _call_overload(self, overload: SumaOverload, args: list[Any]) -> Any:
        func_idx = self._select_overload(overload.candidates, args)
        if overload.bound_this is not None:
            return self._call_lambda(SumaLambda(func_idx, [overload.bound_this]), args)
        return self._call_function_index(func_idx, args)

    def _call_operator_method(self, left: Any, method_name: str, args: list[Any]) -> Any:
        if not isinstance(left, SumaObject):
            return _MISSING
        class_info = self.program.classes.get(left.class_name, {})
        method_overloads = class_info.get("method_overloads", {})
        candidates = method_overloads.get(method_name)
        if candidates:
            return self._call_overload(SumaOverload(method_name, candidates, left), args)
        methods = class_info.get("methods", {})
        if method_name in methods:
            return self._call_lambda(SumaLambda(methods[method_name], [left]), args)
        return _MISSING

    def _alloc_frame(self, func: Function, stack_base: int) -> Frame:
        idx = self._frame_pool_idx
        pool = self._frame_pool
        if idx < len(pool):
            f = pool[idx]
            f.func = func
            f.ip = 0
            f.slots = _reset_slots(f.slots, _slot_count(func))
            f.stack_base = stack_base
            f.this = None
            f.it = None
            f.pending_push = None
        else:
            f = Frame(func, stack_base)
            pool.append(f)
        self._frame_pool_idx = idx + 1
        return f

    def _free_frame(self) -> None:
        self._frame_pool_idx -= 1

    def run(self) -> Any:
        """Execute the program starting from entry point."""
        entry_fn = self.program.functions[self.program.entry]
        frame = self._alloc_frame(entry_fn, 0)
        self.frames.append(frame)
        self.stack = self._new_stack()
        self._sp = 0
        return self._execute()

    def _execute(self) -> Any:
        """Main execution loop — optimized with match/case dispatch."""
        # Cache everything as locals for speed
        stack = self.stack
        sp = self._sp
        frames = self.frames
        program = self.program
        functions = program.functions
        constants = program.constants
        classes = program.classes
        method_decorators = program.method_decorators
        overloads = program.overloads
        globals_ = self.globals
        func_map = self._func_map
        builtins = self._builtins
        py_member = python_member
        py_index = python_index
        py_slice = python_slice
        py_call = lambda callee, args: call_python(self, callee, args)  # noqa: E731
        call_overload = self._call_overload
        select_overload = self._select_overload
        frame_pool = self._frame_pool
        fpi = self._frame_pool_idx

        # Cache type checks
        _SumaOk = SumaOk
        _SumaErr = SumaErr
        _SumaEnum = SumaEnum
        _SumaList = SumaList
        _SumaTuple = SumaTuple
        _SumaRange = SumaRange
        _SumaObject = SumaObject
        _SumaLambda = SumaLambda
        _SumaOverload = SumaOverload
        _SumaCallable = SumaCallable
        _SumaPyObject = SumaPyObject
        _VMError = VMError

        frame = frames[-1]
        fn = frame.func
        code = fn.code
        code_len = len(code)
        ip = frame.ip
        slots = frame.slots
        fc = fn.constants
        fc_len = len(fc)

        def call_operator(left: Any, method_name: str, args: list[Any]) -> Any:
            nonlocal fpi, sp
            frame.ip = ip
            self._sp = sp
            self._frame_pool_idx = fpi
            result = self._call_operator_method(left, method_name, args)
            fpi = self._frame_pool_idx
            return result

        def compare_with_operator(left: Any, right: Any, cmp_code: int) -> bool:
            if _isinstance(left, _SumaObject):
                result = call_operator(left, _CMP_METHODS[cmp_code], [right])
                if result is not _MISSING:
                    return bool(result)
            return _compare_values(left, right, cmp_code)

        def apply_binop_with_operator(op_code: int, left: Any, right: Any) -> Any:
            if _isinstance(left, _SumaObject):
                method_name = _BINOP_METHODS.get(op_code)
                if method_name is not None:
                    result = call_operator(left, method_name, [right])
                    if result is not _MISSING:
                        return result
            return _apply_binop_fast(op_code, left, right)

        def frame_slots_for(func: Function, existing: list[Any] | None = None) -> list[Any]:
            count = _slot_count(func)
            if existing is None:
                return [None] * count
            return _reset_slots(existing, count)

        while ip < code_len:
            if sp + self._STACK_HEADROOM >= len(stack):
                stack.extend([None] * len(stack))
            op = code[ip]
            ip += 1

            match op:
                # Hot path: loads & stores
                case OC.LOAD_CONST:
                    idx = code[ip]
                    ip += 1
                    stack[sp] = fc[idx] if idx < fc_len else constants[idx]
                    sp += 1
                case OC.LOAD_VAR:
                    slot = code[ip]
                    ip += 1
                    if slot < 0:
                        raise _VMError(f"Invalid local slot: {slot}")
                    stack[sp] = slots[slot]
                    sp += 1
                case OC.STORE_VAR:
                    slot = code[ip]
                    ip += 1
                    if slot < 0:
                        raise _VMError(f"Invalid local slot: {slot}")
                    slots[slot] = stack[sp - 1]
                case OC.LOAD_GLOBAL:
                    name = constants[code[ip]]
                    ip += 1
                    if name in globals_:  # noqa: SIM108
                        stack[sp] = globals_[name]
                    elif name in overloads or name in func_map or name in builtins:
                        stack[sp] = name
                    else:
                        stack[sp] = None
                    sp += 1
                case OC.STORE_GLOBAL:
                    name = constants[code[ip]]
                    ip += 1
                    globals_[name] = stack[sp - 1]
                case OC.LOAD_FUNC:
                    func_idx = code[ip]
                    ip += 1
                    stack[sp] = _SumaLambda(func_idx, [])
                    sp += 1

                # Hot path: arithmetic
                case OC.ADD:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, int) and _isinstance(b, int):
                        stack[sp - 2] = a + b
                    elif _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_add", [b])
                        stack[sp - 2] = result if result is not _MISSING else a + b
                    elif _isinstance(a, str) or _isinstance(b, str):
                        stack[sp - 2] = _to_str_fast(a) + _to_str_fast(b)
                    elif _isinstance(a, _SumaList) and _isinstance(b, _SumaList):
                        stack[sp - 2] = _SumaList(a.items + b.items)
                    else:
                        stack[sp - 2] = a + b
                    sp -= 1
                case OC.SUB:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_sub", [b])
                        stack[sp - 2] = result if result is not _MISSING else a - b
                    else:
                        stack[sp - 2] = a - b
                    sp -= 1
                case OC.MUL:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_mul", [b])
                        stack[sp - 2] = result if result is not _MISSING else a * b
                    else:
                        stack[sp - 2] = a * b
                    sp -= 1
                case OC.DIV:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_div", [b])
                        if result is not _MISSING:
                            stack[sp - 2] = result
                        else:
                            if b == 0:
                                raise _VMError("Division by zero")
                            stack[sp - 2] = (
                                a // b if _isinstance(a, int) and _isinstance(b, int) else a / b
                            )
                    else:
                        if b == 0:
                            raise _VMError("Division by zero")
                        stack[sp - 2] = (
                            a // b if _isinstance(a, int) and _isinstance(b, int) else a / b
                        )
                    sp -= 1
                case OC.MOD:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_mod", [b])
                        stack[sp - 2] = result if result is not _MISSING else a % b
                    else:
                        stack[sp - 2] = a % b
                    sp -= 1
                case OC.NEG:
                    value = stack[sp - 1]
                    if _isinstance(value, _SumaObject):
                        result = call_operator(value, "op_neg", [])
                        fallback: Any = value
                        stack[sp - 1] = result if result is not _MISSING else -fallback
                    else:
                        stack[sp - 1] = -value

                # Hot path: comparison
                case OC.EQ:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_eq", [b])
                        stack[sp - 2] = result if result is not _MISSING else a == b
                    else:
                        stack[sp - 2] = a == b
                    sp -= 1
                case OC.NE:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_ne", [b])
                        stack[sp - 2] = result if result is not _MISSING else a != b
                    else:
                        stack[sp - 2] = a != b
                    sp -= 1
                case OC.GT:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_gt", [b])
                        stack[sp - 2] = result if result is not _MISSING else a > b
                    else:
                        stack[sp - 2] = a > b
                    sp -= 1
                case OC.LT:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_lt", [b])
                        stack[sp - 2] = result if result is not _MISSING else a < b
                    else:
                        stack[sp - 2] = a < b
                    sp -= 1
                case OC.GE:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_ge", [b])
                        stack[sp - 2] = result if result is not _MISSING else a >= b
                    else:
                        stack[sp - 2] = a >= b
                    sp -= 1
                case OC.LE:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_le", [b])
                        stack[sp - 2] = result if result is not _MISSING else a <= b
                    else:
                        stack[sp - 2] = a <= b
                    sp -= 1

                # Hot path: control flow
                case OC.JUMP:
                    ip = code[ip]
                case OC.JUMP_IF_FALSE:
                    target = code[ip]
                    ip += 1
                    if not stack[sp - 1]:
                        ip = target
                    sp -= 1
                case OC.JUMP_IF_TRUE:
                    target = code[ip]
                    ip += 1
                    if stack[sp - 1]:
                        ip = target
                    sp -= 1
                case OC.JUMP_IF_VAR_CMP:
                    left = slots[code[ip]]
                    right = slots[code[ip + 1]]
                    cmp_code = code[ip + 2]
                    target = code[ip + 3]
                    ip += 4
                    test = compare_with_operator(left, right, cmp_code)
                    if not test:
                        ip = target
                case OC.JUMP_IF_VAR_CONST_CMP:
                    left = slots[code[ip]]
                    const_idx = code[ip + 1]
                    right = fc[const_idx] if const_idx < fc_len else constants[const_idx]
                    cmp_code = code[ip + 2]
                    target = code[ip + 3]
                    ip += 4
                    test = compare_with_operator(left, right, cmp_code)
                    if not test:
                        ip = target

                # Hot path: function calls
                case OC.CALL_GLOBAL:
                    arg = code[ip]
                    ip += 1
                    func_idx = arg & 0xFFFF
                    nargs = arg >> 16
                    fn2 = functions[func_idx]
                    base = sp - nargs
                    new_slots = (
                        frame_slots_for(fn2, frame_pool[fpi].slots)
                        if fpi < len(frame_pool)
                        else frame_slots_for(fn2)
                    )
                    # Direct copy from stack to slots
                    j = base
                    for i in range(nargs):
                        new_slots[i] = stack[j]
                        j += 1
                    sp = base
                    # Inline frame switch
                    if fpi < len(frame_pool):
                        nf = frame_pool[fpi]
                        nf.func = fn2
                        nf.ip = 0
                        nf.slots = new_slots
                        nf.stack_base = sp
                        nf.this = None
                        nf.it = None
                        nf.pending_push = None
                    else:
                        nf = Frame(fn2, sp)
                        nf.slots = new_slots
                        frame_pool.append(nf)
                    fpi += 1
                    frames.append(nf)
                    frame.ip = ip
                    frame = nf
                    fn = fn2
                    code = fn.code
                    code_len = len(code)
                    ip = 0
                    slots = new_slots
                    fc = fn.constants
                    fc_len = len(fc)
                    continue
                case OC.TAIL_CALL_GLOBAL:
                    arg = code[ip]
                    ip += 1
                    func_idx = arg & 0xFFFF
                    nargs = arg >> 16
                    fn2 = functions[func_idx]
                    base = sp - nargs
                    new_slots = frame_slots_for(fn2, frame.slots)
                    j = base
                    for i in range(nargs):
                        new_slots[i] = stack[j]
                        j += 1
                    sp = base
                    frame.func = fn2
                    frame.ip = 0
                    frame.slots = new_slots
                    frame.this = None
                    frame.it = None
                    frame.pending_push = None
                    fn = fn2
                    code = fn.code
                    code_len = len(code)
                    ip = 0
                    slots = new_slots
                    fc = fn.constants
                    fc_len = len(fc)
                    continue
                case OC.CALL:
                    nargs = code[ip]
                    ip += 1
                    base = sp - nargs
                    callee = stack[base - 1]
                    if _isinstance(callee, str):
                        if callee in overloads:
                            args = stack[base:sp]
                            sp = base - 1
                            frame.ip = ip
                            self._sp = sp
                            self._frame_pool_idx = fpi
                            stack[sp] = call_overload(
                                _SumaOverload(callee, overloads[callee]), args
                            )
                            fpi = self._frame_pool_idx
                            sp += 1
                            continue
                        if callee in func_map:
                            fn2 = functions[func_map[callee]]
                            new_slots = (
                                frame_slots_for(fn2, frame_pool[fpi].slots)
                                if fpi < len(frame_pool)
                                else frame_slots_for(fn2)
                            )
                            j = base
                            for i in range(nargs):
                                new_slots[i] = stack[j]
                                j += 1
                            sp = base - 1
                            if fpi < len(frame_pool):
                                nf = frame_pool[fpi]
                                nf.func = fn2
                                nf.ip = 0
                                nf.slots = new_slots
                                nf.stack_base = sp
                                nf.this = None
                                nf.it = None
                                nf.pending_push = None
                            else:
                                nf = Frame(fn2, sp)
                                nf.slots = new_slots
                                frame_pool.append(nf)
                            fpi += 1
                            frames.append(nf)
                            frame.ip = ip
                            frame = nf
                            fn = fn2
                            code = fn.code
                            code_len = len(code)
                            ip = 0
                            slots = new_slots
                            fc = fn.constants
                            fc_len = len(fc)
                            continue
                        elif callee in builtins:
                            args = stack[base:sp]
                            sp = base - 1
                            stack[sp] = builtins[callee](args)
                            sp += 1
                            continue
                        elif callee in globals_:
                            callee = globals_[callee]
                            args = stack[base:sp]
                            sp = base - 1
                        else:
                            raise _VMError(f"Undefined function: {callee}")
                    else:
                        args = stack[base:sp]
                        sp = base - 1
                    if _isinstance(callee, _SumaLambda):
                        if callee.func_idx == -1:
                            self._sp = sp
                            self._call_special_lambda(callee, args)
                            sp = self._sp
                            continue
                        fn2 = functions[callee.func_idx]
                        new_slots = (
                            frame_slots_for(fn2, frame_pool[fpi].slots)
                            if fpi < len(frame_pool)
                            else frame_slots_for(fn2)
                        )
                        n = len(new_slots)
                        for ci, cv in enumerate(callee.closure):
                            if ci < n:
                                new_slots[ci] = cv
                        nf_this = callee.closure[0] if (fn2.is_method and callee.closure) else None
                        offset = len(callee.closure)
                        for i in range(nargs):
                            slot = i + offset
                            if slot >= n:
                                raise _VMError(f"Too many arguments for lambda: {nargs}")
                            new_slots[slot] = args[i]
                        if fpi < len(frame_pool):
                            nf = frame_pool[fpi]
                            nf.func = fn2
                            nf.ip = 0
                            nf.slots = new_slots
                            nf.stack_base = sp
                            nf.this = nf_this
                            nf.it = None
                            nf.pending_push = None
                        else:
                            nf = Frame(fn2, sp)
                            nf.slots = new_slots
                            nf.this = nf_this
                            frame_pool.append(nf)
                        fpi += 1
                        frames.append(nf)
                        frame.ip = ip
                        frame = nf
                        fn = fn2
                        code = fn.code
                        code_len = len(code)
                        ip = 0
                        slots = new_slots
                        fc = fn.constants
                        fc_len = len(fc)
                        continue
                    if _isinstance(callee, _SumaOverload):
                        frame.ip = ip
                        self._sp = sp
                        self._frame_pool_idx = fpi
                        stack[sp] = call_overload(callee, args)
                        fpi = self._frame_pool_idx
                        sp += 1
                        continue
                    if _isinstance(callee, _SumaPyObject):
                        wrapped_args = [
                            _SumaCallable(self, arg, "<arg>")
                            if _isinstance(arg, _SumaLambda)
                            else arg
                            for arg in args
                        ]
                        stack[sp] = py_call(callee, wrapped_args)
                        sp += 1
                        continue
                    raise _VMError(f"Cannot call {type(callee)}")
                case OC.RETURN:
                    val = stack[sp - 1]
                    sp = frame.stack_base
                    fpi -= 1
                    completed_frame = frame
                    frames.pop()
                    if not frames:
                        self._frame_pool_idx = fpi
                        return val
                    if completed_frame.pending_push is not None:
                        stack[sp] = completed_frame.pending_push
                        sp += 1
                    else:
                        stack[sp] = val
                        sp += 1
                    frame = frames[-1]
                    fn = frame.func
                    code = fn.code
                    code_len = len(code)
                    ip = frame.ip
                    slots = frame.slots
                    fc = fn.constants
                    fc_len = len(fc)

                # Constants
                case OC.LOAD_TRUE:
                    stack[sp] = True
                    sp += 1
                case OC.LOAD_FALSE:
                    stack[sp] = False
                    sp += 1
                case OC.LOAD_NULL:
                    stack[sp] = None
                    sp += 1
                case OC.LOAD_THIS:
                    stack[sp] = frame.this
                    sp += 1
                case OC.LOAD_IT:
                    stack[sp] = frame.it
                    sp += 1
                case OC.SET_IT:
                    sp -= 1
                    frame.it = stack[sp]
                case OC.POP:
                    sp -= 1
                case OC.DUP:
                    stack[sp] = stack[sp - 1]
                    sp += 1

                # Bitwise
                case OC.BIT_AND:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_bit_and", [b])
                        stack[sp - 2] = result if result is not _MISSING else a & b
                    else:
                        stack[sp - 2] = a & b
                    sp -= 1
                case OC.BIT_OR:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_bit_or", [b])
                        stack[sp - 2] = result if result is not _MISSING else a | b
                    else:
                        stack[sp - 2] = a | b
                    sp -= 1
                case OC.BIT_XOR:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_bit_xor", [b])
                        stack[sp - 2] = result if result is not _MISSING else a ^ b
                    else:
                        stack[sp - 2] = a ^ b
                    sp -= 1
                case OC.BIT_NOT:
                    value = stack[sp - 1]
                    if _isinstance(value, _SumaObject):
                        result = call_operator(value, "op_bit_not", [])
                        fallback: Any = value
                        stack[sp - 1] = result if result is not _MISSING else ~fallback
                    else:
                        stack[sp - 1] = ~value
                case OC.SHL:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_shl", [b])
                        stack[sp - 2] = result if result is not _MISSING else a << b
                    else:
                        stack[sp - 2] = a << b
                    sp -= 1
                case OC.SHR:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if _isinstance(a, _SumaObject):
                        result = call_operator(a, "op_shr", [b])
                        stack[sp - 2] = result if result is not _MISSING else a >> b
                    else:
                        stack[sp - 2] = a >> b
                    sp -= 1

                # Logic
                case OC.NOT:
                    value = stack[sp - 1]
                    if _isinstance(value, _SumaObject):
                        result = call_operator(value, "op_not", [])
                        stack[sp - 1] = result if result is not _MISSING else not value
                    else:
                        stack[sp - 1] = not value
                case OC.AND:
                    stack[sp - 2] = stack[sp - 2] and stack[sp - 1]
                    sp -= 1
                case OC.OR:
                    stack[sp - 2] = stack[sp - 2] or stack[sp - 1]
                    sp -= 1
                case OC.INPLACE_VAR_VAR:
                    target_slot = code[ip]
                    rhs_slot = code[ip + 1]
                    op_code = code[ip + 2]
                    ip += 3
                    slots[target_slot] = apply_binop_with_operator(
                        op_code, slots[target_slot], slots[rhs_slot]
                    )
                case OC.INPLACE_VAR_CONST:
                    target_slot = code[ip]
                    const_idx = code[ip + 1]
                    op_code = code[ip + 2]
                    ip += 3
                    rhs = fc[const_idx] if const_idx < fc_len else constants[const_idx]
                    slots[target_slot] = apply_binop_with_operator(
                        op_code, slots[target_slot], rhs
                    )
                case OC.LOOP_GENERIC:
                    arg_count = code[ip]
                    left_slot = code[ip + 1]
                    right_slot = code[ip + 2]
                    cmp_code = code[ip + 3]
                    op_count = code[ip + 4]
                    ops_base = ip + 5
                    ip += 1 + arg_count
                    while True:
                        left = slots[left_slot]
                        right = slots[right_slot]
                        test = compare_with_operator(left, right, cmp_code)
                        if test:
                            break
                        j = ops_base
                        for _ in range(op_count):
                            target_slot = code[j]
                            rhs_ref = code[j + 1]
                            op_code = code[j + 2]
                            j += 3
                            if rhs_ref < 0:
                                const_idx = ~rhs_ref
                                rhs = fc[const_idx] if const_idx < fc_len else constants[const_idx]
                            else:
                                rhs = slots[rhs_ref]
                            slots[target_slot] = apply_binop_with_operator(
                                op_code, slots[target_slot], rhs
                            )

                # Data structures
                case OC.MAKE_LIST:
                    count = code[ip]
                    ip += 1
                    base = sp - count
                    stack[base] = _SumaList(stack[base:sp])
                    sp = base + 1
                case OC.MAKE_TUPLE:
                    count = code[ip]
                    ip += 1
                    base = sp - count
                    stack[base] = _SumaTuple(stack[base:sp])
                    sp = base + 1
                case OC.MAKE_RANGE:
                    inclusive = bool(code[ip])
                    ip += 1
                    end = stack[sp - 1]
                    start = stack[sp - 2]
                    if not _isinstance(start, int) or not _isinstance(end, int):
                        raise _VMError("Range bounds must be Int")
                    stack[sp - 2] = _SumaRange(start, end, inclusive)
                    sp -= 1
                case OC.MAKE_OK:
                    stack[sp - 1] = _SumaOk(stack[sp - 1])
                case OC.MAKE_ERR:
                    stack[sp - 1] = _SumaErr(stack[sp - 1])
                case OC.MAKE_ENUM:
                    tag = constants[code[ip]]
                    nargs = code[ip + 1]
                    ip += 2
                    enum_name, variant_name = tag.split(".", 1)
                    base = sp - nargs
                    value = stack[base] if nargs else None
                    stack[base] = _SumaEnum(enum_name, variant_name, value)
                    sp = base + 1
                case OC.INDEX:
                    idx = stack[sp - 1]
                    obj = stack[sp - 2]
                    if _isinstance(obj, _SumaList):
                        if _isinstance(idx, int):
                            normalized = idx if idx >= 0 else len(obj.items) + idx
                            if normalized < 0 or normalized >= len(obj.items):
                                raise _VMError(f"List index {idx} out of range")
                            stack[sp - 2] = obj.items[normalized]
                        else:
                            raise _VMError(f"List index must be Int, got {type(idx)}")
                    elif _isinstance(obj, _SumaTuple):
                        if _isinstance(idx, int):
                            normalized = idx if idx >= 0 else len(obj.items) + idx
                            if normalized < 0 or normalized >= len(obj.items):
                                raise _VMError(f"Tuple index {idx} out of range")
                            stack[sp - 2] = obj.items[normalized]
                        else:
                            raise _VMError(f"Tuple index must be Int, got {type(idx)}")
                    elif _isinstance(obj, _SumaRange):
                        if _isinstance(idx, int):
                            try:
                                stack[sp - 2] = obj[idx]
                            except IndexError as err:
                                raise _VMError(f"Range index {idx} out of range") from err
                        else:
                            raise _VMError(f"Range index must be Int, got {type(idx)}")
                    elif _isinstance(obj, str):
                        if not _isinstance(idx, int):
                            raise _VMError(f"Str index must be Int, got {type(idx)}")
                        normalized = idx if idx >= 0 else len(obj) + idx
                        if normalized < 0 or normalized >= len(obj):
                            raise _VMError(f"Str index {idx} out of range")
                        stack[sp - 2] = obj[normalized]
                    elif _isinstance(obj, _SumaPyObject):
                        stack[sp - 2] = py_index(obj, idx)
                    else:
                        raise _VMError(f"Cannot index {type(obj)}")
                    sp -= 1
                case OC.SLICE:
                    mask = code[ip]
                    ip += 1
                    end = None
                    start = None
                    if mask & 2:
                        sp -= 1
                        end = stack[sp]
                    if mask & 1:
                        sp -= 1
                        start = stack[sp]
                    sp -= 1
                    obj = stack[sp]
                    if _isinstance(obj, _SumaList):
                        s = start if start is not None else 0
                        e = end if end is not None else len(obj.items)
                        stack[sp] = _SumaList(obj.items[s:e])
                    elif _isinstance(obj, str):
                        s = start if start is not None else 0
                        e = end if end is not None else len(obj)
                        stack[sp] = obj[s:e]
                    elif _isinstance(obj, _SumaPyObject):
                        stack[sp] = py_slice(obj, start, end)
                    else:
                        raise _VMError(f"Cannot slice {type(obj)}")
                    sp += 1
                case OC.MEMBER:
                    name = constants[code[ip]]
                    ip += 1
                    obj = stack[sp - 1]
                    if _isinstance(obj, _SumaObject):
                        ci = program.classes.get(obj.class_name, {})
                        mths = ci.get("methods", {})
                        getters = ci.get("getters", {})
                        getter_idx = getters.get(name)
                        if getter_idx is not None:
                            getter_fn = functions[getter_idx]
                            new_slots = (
                                frame_slots_for(getter_fn, frame_pool[fpi].slots)
                                if fpi < len(frame_pool)
                                else frame_slots_for(getter_fn)
                            )
                            new_slots[0] = obj
                            sp -= 1
                            if fpi < len(frame_pool):
                                nf = frame_pool[fpi]
                                nf.func = getter_fn
                                nf.ip = 0
                                nf.slots = new_slots
                                nf.stack_base = sp
                                nf.this = obj
                                nf.it = None
                                nf.pending_push = None
                            else:
                                nf = Frame(getter_fn, sp)
                                nf.slots = new_slots
                                nf.this = obj
                                frame_pool.append(nf)
                            fpi += 1
                            frames.append(nf)
                            frame.ip = ip
                            frame = nf
                            fn = getter_fn
                            code = fn.code
                            code_len = len(code)
                            ip = 0
                            slots = new_slots
                            fc = fn.constants
                            fc_len = len(fc)
                            continue
                        if name in obj.fields:
                            stack[sp - 1] = obj.fields[name]
                        else:
                            method_overloads = ci.get("method_overloads", {})
                            if name in method_overloads:
                                stack[sp - 1] = _SumaOverload(name, method_overloads[name], obj)
                            elif name in mths:
                                bound_method = _SumaLambda(mths[name], [obj])
                                decorator_idx = method_decorators.get(f"{obj.class_name}.{name}")
                                if decorator_idx is not None:
                                    frame.ip = ip
                                    self._sp = sp
                                    self._frame_pool_idx = fpi
                                    bound_method = self._call_function_index(
                                        decorator_idx, [bound_method]
                                    )
                                    fpi = self._frame_pool_idx
                                stack[sp - 1] = bound_method
                            else:
                                raise _VMError(f"No member '{name}' on {obj.class_name}")
                    elif _isinstance(obj, _SumaList):
                        if name == "size":
                            stack[sp - 1] = len(obj.items)
                        elif name == "add":
                            stack[sp - 1] = _SumaLambda(-1, [obj])
                        else:
                            raise _VMError(f"No member '{name}' on List")
                    elif _isinstance(obj, _SumaTuple):
                        if name == "size":
                            stack[sp - 1] = len(obj.items)
                        else:
                            raise _VMError(f"No member '{name}' on Tuple")
                    elif _isinstance(obj, _SumaRange):
                        if name == "size":
                            stack[sp - 1] = len(obj)
                        elif name == "start":
                            stack[sp - 1] = obj.start
                        elif name == "end":
                            stack[sp - 1] = obj.end
                        elif name == "inclusive":
                            stack[sp - 1] = obj.inclusive
                        else:
                            raise _VMError(f"No member '{name}' on Range")
                    elif _isinstance(obj, str):
                        if name == "size":
                            stack[sp - 1] = len(obj)
                        else:
                            raise _VMError(f"No member '{name}' on Str")
                    elif _isinstance(obj, _SumaOk):
                        if name == "value":
                            stack[sp - 1] = obj.value
                        else:
                            raise _VMError(f"Cannot access member '{name}' on Ok")
                    elif _isinstance(obj, _SumaErr):
                        if name == "value":
                            stack[sp - 1] = obj.value
                        else:
                            raise _VMError(f"Cannot access member '{name}' on Err")
                    elif _isinstance(obj, _SumaEnum):
                        if name == "value":
                            stack[sp - 1] = obj.value
                        elif name == "variant":
                            stack[sp - 1] = obj.variant_name
                        elif name == "enum":
                            stack[sp - 1] = obj.enum_name
                        else:
                            raise _VMError(f"Cannot access member '{name}' on {obj.enum_name}")
                    elif _isinstance(obj, _SumaPyObject):
                        stack[sp - 1] = py_member(obj, name)
                    else:
                        raise _VMError(f"Cannot access member '{name}' on {type(obj)}")
                case OC.SET_MEMBER:
                    name = constants[code[ip]]
                    ip += 1
                    val = stack[sp - 1]
                    obj = stack[sp - 2]
                    if _isinstance(obj, _SumaObject):
                        ci = program.classes.get(obj.class_name, {})
                        setters = ci.get("setters", {})
                        setter_idx = setters.get(name)
                        if setter_idx is not None:
                            sp -= 2
                            frame.ip = ip
                            self._sp = sp
                            self._frame_pool_idx = fpi
                            self._call_lambda(_SumaLambda(setter_idx, [obj]), [val])
                            fpi = self._frame_pool_idx
                            stack = self.stack
                            stack[sp] = val
                            sp += 1
                            continue
                        obj.fields[name] = val
                    else:
                        raise _VMError(f"Cannot set member on {type(obj)}")
                    stack[sp - 2] = val
                    sp -= 1
                case OC.SET_INDEX:
                    val = stack[sp - 1]
                    idx = stack[sp - 2]
                    obj = stack[sp - 3]
                    if _isinstance(obj, _SumaList):
                        if not _isinstance(idx, int):
                            raise _VMError(f"List index must be Int, got {type(idx)}")
                        normalized = idx if idx >= 0 else len(obj.items) + idx
                        if normalized < 0 or normalized >= len(obj.items):
                            raise _VMError(f"List index {idx} out of range")
                        obj.items[normalized] = val
                    elif _isinstance(obj, _SumaPyObject):
                        obj.value[idx] = _to_python_value(val)
                    else:
                        raise _VMError(f"Cannot set index on {type(obj)}")
                    stack[sp - 3] = val
                    sp -= 2

                # Object creation
                case OC.MAKE_OBJECT:
                    class_name = constants[code[ip]]
                    nargs = code[ip + 1]
                    ip += 2
                    ci = classes.get(class_name, {})
                    obj = _SumaObject(class_name, {f: None for f in ci.get("fields", [])})
                    mths = ci.get("methods", {})
                    method_overloads = ci.get("method_overloads", {})
                    init_idx = mths.get("init")
                    if init_idx is None and method_overloads.get("init"):
                        init_args = stack[sp - nargs : sp]
                        init_idx = select_overload(method_overloads["init"], init_args)
                    if init_idx is not None:
                        init_fn = functions[init_idx]
                        base = sp - nargs
                        new_slots = (
                            frame_slots_for(init_fn, frame_pool[fpi].slots)
                            if fpi < len(frame_pool)
                            else frame_slots_for(init_fn)
                        )
                        new_slots[0] = obj
                        j = base
                        for i in range(nargs):
                            new_slots[i + 1] = stack[j]
                            j += 1
                        sp = base
                        if fpi < len(frame_pool):
                            nf = frame_pool[fpi]
                            nf.func = init_fn
                            nf.ip = 0
                            nf.slots = new_slots
                            nf.stack_base = sp
                            nf.this = obj
                            nf.it = None
                            nf.pending_push = None
                        else:
                            nf = Frame(init_fn, sp)
                            nf.slots = new_slots
                            nf.this = obj
                            frame_pool.append(nf)
                        fpi += 1
                        frames.append(nf)
                        nf.pending_push = obj
                        frame.ip = ip
                        frame = nf
                        fn = init_fn
                        code = fn.code
                        code_len = len(code)
                        ip = 0
                        slots = new_slots
                        fc = fn.constants
                        fc_len = len(fc)
                        continue
                    sp -= nargs
                    stack[sp] = obj
                    sp += 1
                case OC.MAKE_LAMBDA:
                    func_idx = code[ip]
                    ip += 1
                    target_fn = functions[func_idx]
                    capture_slots = target_fn.capture_slots or list(range(target_fn.capture_count))
                    stack[sp] = _SumaLambda(func_idx, [slots[slot] for slot in capture_slots])
                    sp += 1

                # Pattern matching
                case OC.IS_OK:
                    stack[sp] = _isinstance(stack[sp - 1], _SumaOk)
                    sp += 1
                case OC.IS_ERR:
                    stack[sp] = _isinstance(stack[sp - 1], _SumaErr)
                    sp += 1
                case OC.IS_ENUM_VARIANT:
                    tag = constants[code[ip]]
                    ip += 1
                    value = stack[sp - 1]
                    stack[sp] = (
                        _isinstance(value, _SumaEnum)
                        and f"{value.enum_name}.{value.variant_name}" == tag
                    )
                    sp += 1
                case OC.UNWRAP_OK:
                    val = stack[sp - 1]
                    if _isinstance(val, _SumaOk):
                        stack[sp - 1] = val.value
                    else:
                        raise _VMError(f"Unwrap on Err: {val}")

                # I/O
                case OC.PRINT:
                    sp -= 1
                    print(_format_value(stack[sp]))

                # Misc
                case OC.NOP:
                    pass
                case OC.HALT:
                    self._frame_pool_idx = fpi
                    return stack[sp - 1]
                case _:
                    raise _VMError(f"Unknown opcode: {op}")

        # Fell off end of code (shouldn't happen with proper RETURN)
        self._frame_pool_idx = fpi
        return None

    # stack helpers

    def _push(self, val: Any) -> None:
        if self._sp >= len(self.stack):
            self.stack.extend([None] * max(len(self.stack), 1))
        self.stack[self._sp] = val
        self._sp += 1

    def _pop(self) -> Any:
        self._sp -= 1
        return self.stack[self._sp]

    def _peek(self) -> Any:
        return self.stack[self._sp - 1]

    # operations

    def _add(self, a: Any, b: Any) -> Any:
        if isinstance(a, str) or isinstance(b, str):
            return self._to_str(a) + self._to_str(b)
        if isinstance(a, SumaList) and isinstance(b, SumaList):
            return SumaList(a.items + b.items)
        return a + b

    def _to_str(self, val: Any) -> str:
        return _format_value(val)

    def _index(self, obj: Any, idx: Any) -> Any:
        if isinstance(obj, SumaList):
            if isinstance(idx, int):
                if idx < 0:
                    idx += len(obj.items)
                if idx < 0 or idx >= len(obj.items):
                    raise VMError(f"List index {idx} out of range")
                return obj.items[idx]
            raise VMError(f"List index must be Int, got {type(idx)}")
        if isinstance(obj, SumaTuple):
            if isinstance(idx, int):
                if idx < 0:
                    idx += len(obj.items)
                if idx < 0 or idx >= len(obj.items):
                    raise VMError(f"Tuple index {idx} out of range")
                return obj.items[idx]
            raise VMError(f"Tuple index must be Int, got {type(idx)}")
        if isinstance(obj, SumaRange):
            if isinstance(idx, int):
                try:
                    return obj[idx]
                except IndexError as err:
                    raise VMError(f"Range index {idx} out of range") from err
            raise VMError(f"Range index must be Int, got {type(idx)}")
        if isinstance(obj, str):
            if isinstance(idx, int):
                if idx < 0:
                    idx += len(obj)
                if idx < 0 or idx >= len(obj):
                    raise VMError(f"Str index {idx} out of range")
                return obj[idx]
            raise VMError(f"Str index must be Int, got {type(idx)}")
        if isinstance(obj, SumaPyObject):
            return python_index(obj, idx)
        raise VMError(f"Cannot index {type(obj)}")

    def _slice(self, obj: Any, start: Any, end: Any) -> Any:
        if isinstance(obj, SumaList):
            s = start if start is not None else 0
            e = end if end is not None else len(obj.items)
            return SumaList(obj.items[s:e])
        if isinstance(obj, str):
            s = start if start is not None else 0
            e = end if end is not None else len(obj)
            return obj[s:e]
        if isinstance(obj, SumaPyObject):
            return python_slice(obj, start, end)
        raise VMError(f"Cannot slice {type(obj)}")

    def _member(self, obj: Any, name: str) -> Any:
        if isinstance(obj, SumaObject):
            class_info = self.program.classes.get(obj.class_name, {})
            getters = class_info.get("getters", {})
            getter_idx = getters.get(name)
            if getter_idx is not None:
                return self._call_lambda(SumaLambda(getter_idx, [obj]), [])
            methods = class_info.get("methods", {})
            if name in obj.fields:
                return obj.fields[name]
            # Look for method
            method_overloads = class_info.get("method_overloads", {})
            if name in method_overloads:
                return SumaOverload(name, method_overloads[name], obj)
            if name in methods:
                func_idx = methods[name]
                return self._decorate_bound_method(
                    obj.class_name, name, SumaLambda(func_idx, [obj])
                )
            raise VMError(f"No member '{name}' on {obj.class_name}")
        if isinstance(obj, SumaList):
            if name == "size":
                return len(obj.items)
            if name == "add":
                return SumaLambda(-1, [obj])  # special built-in
            raise VMError(f"No member '{name}' on List")
        if isinstance(obj, SumaTuple):
            if name == "size":
                return len(obj.items)
            raise VMError(f"No member '{name}' on Tuple")
        if isinstance(obj, SumaRange):
            if name == "size":
                return len(obj)
            if name == "start":
                return obj.start
            if name == "end":
                return obj.end
            if name == "inclusive":
                return obj.inclusive
            raise VMError(f"No member '{name}' on Range")
        if isinstance(obj, str):
            if name == "size":
                return len(obj)
            raise VMError(f"No member '{name}' on Str")
        if isinstance(obj, SumaOk) and name == "value":
            return obj.value
        if isinstance(obj, SumaErr) and name == "value":
            return obj.value
        if isinstance(obj, SumaEnum):
            if name == "value":
                return obj.value
            if name == "variant":
                return obj.variant_name
            if name == "enum":
                return obj.enum_name
            raise VMError(f"Cannot access member '{name}' on {obj.enum_name}")
        if isinstance(obj, SumaPyObject):
            return python_member(obj, name)
        raise VMError(f"Cannot access member '{name}' on {type(obj)}")

    def _set_member(self, obj: Any, name: str, val: Any) -> None:
        if isinstance(obj, SumaObject):
            class_info = self.program.classes.get(obj.class_name, {})
            method_idx = class_info.get("setters", {}).get(name)
            if method_idx is not None:
                self._call_lambda(SumaLambda(method_idx, [obj]), [val])
                return
            obj.fields[name] = val
            return
        raise VMError(f"Cannot set member on {type(obj)}")

    def _call_special_lambda(self, lam: SumaLambda, args: list) -> None:
        """Handle special built-in lambdas."""
        obj = lam.closure[0] if lam.closure else None
        if isinstance(obj, SumaList):
            # list.add(item)
            if args:
                obj.items.append(args[0])
            self._push(None)
            return
        raise VMError("Unknown special lambda")
