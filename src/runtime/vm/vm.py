"""Suma-lang Virtual Machine — executes .sumac bytecode."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Callable

from src.backend.codegen.opcodes import Function, Op, ProgramBytecode

# Runtime values


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


class SumaObject:
    __slots__ = ("class_name", "fields")

    def __init__(self, class_name: str, fields: dict) -> None:
        self.class_name = class_name
        self.fields = fields

    def __repr__(self) -> str:
        return f"{self.class_name}({self.fields!r})"


class SumaLambda:
    __slots__ = ("func_idx", "closure")

    def __init__(self, func_idx: int, closure: list) -> None:
        self.func_idx = func_idx
        self.closure = closure

    def __repr__(self) -> str:
        return f"<lambda@{self.func_idx}>"


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

    def _make_python_callable(self) -> Callable:
        if self.arity == 0:

            def callback():
                return self._invoke([])
        elif self.arity == 1:

            def callback(arg0):
                return self._invoke([arg0])
        elif self.arity == 2:

            def callback(arg0, arg1):
                return self._invoke([arg0, arg1])
        elif self.arity == 3:

            def callback(arg0, arg1, arg2):
                return self._invoke([arg0, arg1, arg2])
        else:

            def callback(*args):
                return self._invoke(list(args))

        callback.__name__ = self.name.replace(".", "_").replace("<", "_").replace(">", "_")
        callback.__suma_value__ = self.value
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
    if isinstance(value, (SumaLambda, str)):
        return value
    if isinstance(value, SumaList):
        return [_to_python_value(item) for item in value.items]
    if isinstance(value, SumaOk):
        return {"ok": _to_python_value(value.value)}
    if isinstance(value, SumaErr):
        return {"err": _to_python_value(value.value)}
    if isinstance(value, SumaObject):
        return {key: _to_python_value(val) for key, val in value.fields.items()}
    return value


def _from_python_value(value: Any) -> Any:
    suma_value = getattr(value, "__suma_value__", None)
    if suma_value is not None:
        return suma_value
    if isinstance(
        value, (SumaPyObject, SumaCallable, SumaLambda, SumaList, SumaOk, SumaErr, SumaObject)
    ):
        return value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return SumaList([_from_python_value(item) for item in value])
    return SumaPyObject(value)


# Call frame


class Frame:
    __slots__ = ("func", "ip", "slots", "stack_base", "this", "it")

    def __init__(self, func: Function, stack_base: int, this: Any = None) -> None:
        self.func = func
        self.ip = 0
        self.slots: list[Any] = [None] * max(func.locals_count, 1)
        self.stack_base = stack_base
        self.this = this
        self.it = None


# VM


class VMError(Exception):
    pass


_isinstance = isinstance


class OC:
    """Opcode int constants for match/case dispatch (must use dotted names)."""

    LOAD_CONST = int(Op.LOAD_CONST)
    LOAD_VAR = int(Op.LOAD_VAR)
    STORE_VAR = int(Op.STORE_VAR)
    LOAD_GLOBAL = int(Op.LOAD_GLOBAL)
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
    MAKE_OK = int(Op.MAKE_OK)
    MAKE_ERR = int(Op.MAKE_ERR)
    INDEX = int(Op.INDEX)
    SLICE = int(Op.SLICE)
    MEMBER = int(Op.MEMBER)
    SET_MEMBER = int(Op.SET_MEMBER)
    SET_INDEX = int(Op.SET_INDEX)
    MAKE_OBJECT = int(Op.MAKE_OBJECT)
    MAKE_LAMBDA = int(Op.MAKE_LAMBDA)
    IS_OK = int(Op.IS_OK)
    IS_ERR = int(Op.IS_ERR)
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


def _to_str_fast(val: Any) -> str:
    """Fast string conversion — inlined for hot path."""
    if val is None:
        return "null"
    if _isinstance(val, bool):
        return "true" if val else "false"
    if _isinstance(val, str):
        return val
    if _isinstance(val, int):
        return str(val)
    if _isinstance(val, float):
        return str(val)
    if _isinstance(val, SumaList):
        return val.__repr__()
    if _isinstance(val, SumaOk):
        return val.__repr__()
    if _isinstance(val, SumaErr):
        return val.__repr__()
    if _isinstance(val, SumaObject):
        return f"{val.class_name} instance"
    if _isinstance(val, SumaCallable):
        return repr(val)
    if _isinstance(val, SumaPyObject):
        return _py_repr(val.value)
    return str(val)


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


class VM:
    def __init__(self, program: ProgramBytecode) -> None:
        self.program = program
        self.stack: list[Any] = []
        self.frames: list[Frame] = []
        self.globals: dict[str, Any] = {}
        self._func_map: dict[str, int] = {}  # name -> function index
        for i, fn in enumerate(program.functions):
            self._func_map[fn.name] = i
        self._pending_push: Any = None  # object to push after init returns
        self._frame_pool: list[Frame] = []
        self._frame_pool_idx: int = 0
        self._init_builtins()
        self._init_python_imports()
        self._init_decorators()

    def _init_builtins(self) -> None:
        """Register built-in functions."""
        self._builtins: dict[str, Callable] = {
            "print": self._builtin_print,
            "to_str": self._builtin_str,
            "to_int": self._builtin_int,
            "to_float": self._builtin_float,
            "to_bool": self._builtin_bool,
            "List": self._builtin_list,
            "Ok": lambda args: SumaOk(args[0]),
            "Err": lambda args: SumaErr(args[0]),
            "is_ok": lambda args: isinstance(args[0], SumaOk),
            "is_err": lambda args: isinstance(args[0], SumaErr),
            "unwrap": self._builtin_unwrap,
            "unwrap_or": self._builtin_unwrap_or,
            "panic": self._builtin_panic,
            "assert": self._builtin_assert,
            "len": self._builtin_len,
            "type_of": self._builtin_typeof,
            "__suma_is_type": self._builtin_is_type,
            "parse_int": self._builtin_parseint,
            # math
            "abs": lambda args: abs(args[0]),
            "max": lambda args: max(args[0], args[1]),
            "min": lambda args: min(args[0], args[1]),
            "pow": lambda args: args[0] ** args[1],
            # list operations
            "add": self._builtin_list_add,
            "size": self._builtin_len,
            "get": self._builtin_list_get,
        }

    def _init_python_imports(self) -> None:
        """Import host Python modules declared by `import "py:..."`."""
        for alias, module_name in self.program.py_imports.items():
            try:
                self.globals[alias] = SumaPyObject(importlib.import_module(module_name))
            except Exception as exc:
                raise VMError(
                    f"Cannot import Python module '{module_name}' as '{alias}': {exc}"
                ) from exc

    def _init_decorators(self) -> None:
        """Apply top-level function decorators before `main` starts."""
        if not self.program.decorators:
            return
        self.stack = [None] * 10000
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
        fn = self.program.functions[func_idx]
        frame = self._alloc_frame(fn, 0)
        for i, arg in enumerate(args):
            if i < len(frame.slots):
                frame.slots[i] = arg
        old_frames = self.frames
        old_stack = self.stack
        old_sp = getattr(self, "_sp", 0)
        self.frames = [frame]
        self.stack = [None] * 10000
        self._sp = 0
        try:
            return self._execute()
        finally:
            self.frames = old_frames
            self.stack = old_stack
            self._sp = old_sp
            self._frame_pool_idx = max(self._frame_pool_idx - 1, 0)

    def _call_value(self, callee: Any, args: list[Any]) -> Any:
        if isinstance(callee, str):
            if callee in self.globals:
                callee = self.globals[callee]
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
            fn = self.program.functions[callee.func_idx]
            call_args = list(args)
            if fn.is_method and callee.closure:
                call_args = [callee.closure[0], *call_args]
            return self._call_function_index(callee.func_idx, call_args)
        if isinstance(callee, SumaPyObject):
            return self._call_python(callee, args)
        raise VMError(f"Cannot call {type(callee)}")

    def _alloc_frame(self, func: Function, stack_base: int) -> Frame:
        idx = self._frame_pool_idx
        pool = self._frame_pool
        if idx < len(pool):
            f = pool[idx]
            f.func = func
            f.ip = 0
            f.slots = [None] * max(func.locals_count, 1)
            f.stack_base = stack_base
            f.this = None
            f.it = None
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
        self.stack = [None] * 10000
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
        globals_ = self.globals
        func_map = self._func_map
        builtins = self._builtins
        py_member = self._python_member
        py_index = self._python_index
        py_slice = self._python_slice
        py_call = self._call_python
        pending_push = self._pending_push
        frame_pool = self._frame_pool
        fpi = self._frame_pool_idx

        # Cache type checks
        _SumaOk = SumaOk
        _SumaErr = SumaErr
        _SumaList = SumaList
        _SumaObject = SumaObject
        _SumaLambda = SumaLambda
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

        while ip < code_len:
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
                    if slot >= 0:
                        stack[sp] = slots[slot]
                    else:
                        stack[sp] = None
                    sp += 1
                case OC.STORE_VAR:
                    slot = code[ip]
                    ip += 1
                    if slot >= 0:
                        slots[slot] = stack[sp - 1]
                    else:
                        if sp >= 2 and _isinstance(stack[sp - 2], str):
                            val = stack[sp - 1]
                            name = stack[sp - 2]
                            globals_[name] = val
                            stack[sp - 2] = val
                            sp -= 1
                        else:
                            sp -= 1
                            globals_[stack[sp]] = stack[sp]
                case OC.LOAD_GLOBAL:
                    name = constants[code[ip]]
                    ip += 1
                    if name in globals_:
                        stack[sp] = globals_[name]
                    elif name in func_map:
                        stack[sp] = name
                    elif name in builtins:
                        stack[sp] = name
                    else:
                        stack[sp] = None
                    sp += 1
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
                    elif _isinstance(a, str) or _isinstance(b, str):
                        stack[sp - 2] = _to_str_fast(a) + _to_str_fast(b)
                    elif _isinstance(a, _SumaList) and _isinstance(b, _SumaList):
                        stack[sp - 2] = _SumaList(a.items + b.items)
                    else:
                        stack[sp - 2] = a + b
                    sp -= 1
                case OC.SUB:
                    stack[sp - 2] = stack[sp - 2] - stack[sp - 1]
                    sp -= 1
                case OC.MUL:
                    stack[sp - 2] = stack[sp - 2] * stack[sp - 1]
                    sp -= 1
                case OC.DIV:
                    b = stack[sp - 1]
                    a = stack[sp - 2]
                    if b == 0:
                        raise _VMError("Division by zero")
                    stack[sp - 2] = a // b if _isinstance(a, int) and _isinstance(b, int) else a / b
                    sp -= 1
                case OC.MOD:
                    stack[sp - 2] = stack[sp - 2] % stack[sp - 1]
                    sp -= 1
                case OC.NEG:
                    stack[sp - 1] = -stack[sp - 1]

                # Hot path: comparison
                case OC.EQ:
                    stack[sp - 2] = stack[sp - 2] == stack[sp - 1]
                    sp -= 1
                case OC.NE:
                    stack[sp - 2] = stack[sp - 2] != stack[sp - 1]
                    sp -= 1
                case OC.GT:
                    stack[sp - 2] = stack[sp - 2] > stack[sp - 1]
                    sp -= 1
                case OC.LT:
                    stack[sp - 2] = stack[sp - 2] < stack[sp - 1]
                    sp -= 1
                case OC.GE:
                    stack[sp - 2] = stack[sp - 2] >= stack[sp - 1]
                    sp -= 1
                case OC.LE:
                    stack[sp - 2] = stack[sp - 2] <= stack[sp - 1]
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
                    if cmp_code == 0:
                        test = left == right
                    elif cmp_code == 1:
                        test = left != right
                    elif cmp_code == 2:
                        test = left > right
                    elif cmp_code == 3:
                        test = left < right
                    elif cmp_code == 4:
                        test = left >= right
                    else:
                        test = left <= right
                    if not test:
                        ip = target
                case OC.JUMP_IF_VAR_CONST_CMP:
                    left = slots[code[ip]]
                    const_idx = code[ip + 1]
                    right = fc[const_idx] if const_idx < fc_len else constants[const_idx]
                    cmp_code = code[ip + 2]
                    target = code[ip + 3]
                    ip += 4
                    if cmp_code == 0:
                        test = left == right
                    elif cmp_code == 1:
                        test = left != right
                    elif cmp_code == 2:
                        test = left > right
                    elif cmp_code == 3:
                        test = left < right
                    elif cmp_code == 4:
                        test = left >= right
                    else:
                        test = left <= right
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
                    n = fn2.locals_count
                    if n < 1:
                        n = 1
                    new_slots = [None] * n
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
                    n = fn2.locals_count
                    if n < 1:
                        n = 1
                    new_slots = [None] * n
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
                        if callee in func_map:
                            fn2 = functions[func_map[callee]]
                            n = fn2.locals_count
                            if n < 1:
                                n = 1
                            new_slots = [None] * n
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
                        n = fn2.locals_count
                        if n < 1:
                            n = 1
                        new_slots = [None] * n
                        for ci, cv in enumerate(callee.closure):
                            if ci < n:
                                new_slots[ci] = cv
                        if fn2.is_method and callee.closure:
                            nf_this = callee.closure[0]
                        else:
                            nf_this = None
                        offset = 1 if fn2.is_method else 0
                        for i in range(nargs):
                            new_slots[i + offset] = args[i]
                        if fpi < len(frame_pool):
                            nf = frame_pool[fpi]
                            nf.func = fn2
                            nf.ip = 0
                            nf.slots = new_slots
                            nf.stack_base = sp
                            nf.this = nf_this
                            nf.it = None
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
                    frames.pop()
                    if not frames:
                        self._frame_pool_idx = fpi
                        return val
                    stack[sp] = val
                    sp += 1
                    if pending_push is not None:
                        stack[sp] = pending_push
                        sp += 1
                        self._pending_push = None
                        pending_push = None
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
                    stack[sp - 2] = stack[sp - 2] & stack[sp - 1]
                    sp -= 1
                case OC.BIT_OR:
                    stack[sp - 2] = stack[sp - 2] | stack[sp - 1]
                    sp -= 1
                case OC.BIT_XOR:
                    stack[sp - 2] = stack[sp - 2] ^ stack[sp - 1]
                    sp -= 1
                case OC.BIT_NOT:
                    stack[sp - 1] = ~stack[sp - 1]
                case OC.SHL:
                    stack[sp - 2] = stack[sp - 2] << stack[sp - 1]
                    sp -= 1
                case OC.SHR:
                    stack[sp - 2] = stack[sp - 2] >> stack[sp - 1]
                    sp -= 1

                # Logic
                case OC.NOT:
                    stack[sp - 1] = not stack[sp - 1]
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
                    slots[target_slot] = _apply_binop_fast(
                        op_code, slots[target_slot], slots[rhs_slot]
                    )
                case OC.INPLACE_VAR_CONST:
                    target_slot = code[ip]
                    const_idx = code[ip + 1]
                    op_code = code[ip + 2]
                    ip += 3
                    rhs = fc[const_idx] if const_idx < fc_len else constants[const_idx]
                    slots[target_slot] = _apply_binop_fast(op_code, slots[target_slot], rhs)
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
                        if cmp_code == 0:
                            test = left == right
                        elif cmp_code == 1:
                            test = left != right
                        elif cmp_code == 2:
                            test = left > right
                        elif cmp_code == 3:
                            test = left < right
                        elif cmp_code == 4:
                            test = left >= right
                        else:
                            test = left <= right
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
                            slots[target_slot] = _apply_binop_fast(op_code, slots[target_slot], rhs)

                # Data structures
                case OC.MAKE_LIST:
                    count = code[ip]
                    ip += 1
                    base = sp - count
                    stack[base] = _SumaList(stack[base:sp])
                    sp = base + 1
                case OC.MAKE_OK:
                    stack[sp - 1] = _SumaOk(stack[sp - 1])
                case OC.MAKE_ERR:
                    stack[sp - 1] = _SumaErr(stack[sp - 1])
                case OC.INDEX:
                    idx = stack[sp - 1]
                    obj = stack[sp - 2]
                    if _isinstance(obj, _SumaList):
                        if _isinstance(idx, int):
                            stack[sp - 2] = obj.items[idx if idx >= 0 else len(obj.items) + idx]
                        else:
                            raise _VMError(f"List index must be Int, got {type(idx)}")
                    elif _isinstance(obj, str):
                        stack[sp - 2] = obj[idx]
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
                        if name in obj.fields:
                            stack[sp - 1] = obj.fields[name]
                        else:
                            ci = program.classes.get(obj.class_name, {})
                            mths = ci.get("methods", {})
                            if name in mths:
                                stack[sp - 1] = _SumaLambda(mths[name], [obj])
                            else:
                                getter = f"get_{name}"
                                if getter in mths:
                                    getter_fn = functions[mths[getter]]
                                    n = getter_fn.locals_count
                                    if n < 1:
                                        n = 1
                                    new_slots = [None] * n
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
                                else:
                                    raise _VMError(f"No member '{name}' on {obj.class_name}")
                    elif _isinstance(obj, _SumaList):
                        if name == "size":
                            stack[sp - 1] = len(obj.items)
                        elif name == "add":
                            stack[sp - 1] = _SumaLambda(-1, [obj])
                        else:
                            raise _VMError(f"No member '{name}' on List")
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
                        obj.items[idx if idx >= 0 else len(obj.items) + idx] = val
                    elif _isinstance(obj, _SumaPyObject):
                        obj.value[idx] = _to_python_value(val)
                    else:
                        raise _VMError(f"Cannot set index on {type(obj)}")
                    stack[sp - 3] = val
                    sp -= 2

                # Object creation
                case OC.MAKE_OBJECT:
                    class_name = constants[code[ip]]
                    ip += 1
                    ci = classes.get(class_name, {})
                    obj = _SumaObject(class_name, {f: None for f in ci.get("fields", [])})
                    mths = ci.get("methods", {})
                    if "init" in mths:
                        init_fn = functions[mths["init"]]
                        nargs = init_fn.arity
                        base = sp - nargs
                        n = init_fn.locals_count
                        if n < 1:
                            n = 1
                        new_slots = [None] * n
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
                        else:
                            nf = Frame(init_fn, sp)
                            nf.slots = new_slots
                            nf.this = obj
                            frame_pool.append(nf)
                        fpi += 1
                        frames.append(nf)
                        self._pending_push = obj
                        pending_push = obj
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
                    stack[sp] = obj
                    sp += 1
                case OC.MAKE_LAMBDA:
                    func_idx = code[ip]
                    ip += 1
                    stack[sp] = _SumaLambda(func_idx, list(slots))
                    sp += 1

                # Pattern matching
                case OC.IS_OK:
                    stack[sp] = _isinstance(stack[sp - 1], _SumaOk)
                    sp += 1
                case OC.IS_ERR:
                    stack[sp] = _isinstance(stack[sp - 1], _SumaErr)
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
                    val = stack[sp]
                    if val is None:
                        print("null")
                    elif val is True:
                        print("true")
                    elif val is False:
                        print("false")
                    elif _isinstance(val, int):
                        print(val)
                    elif _isinstance(val, float):
                        print(val)
                    elif _isinstance(val, str):
                        print(val)
                    elif _isinstance(val, _SumaList):
                        print(val.__repr__())
                    elif _isinstance(val, _SumaOk):
                        print(val.__repr__())
                    elif _isinstance(val, _SumaErr):
                        print(val.__repr__())
                    elif _isinstance(val, _SumaObject):
                        print(f"{val.class_name} instance")
                    else:
                        print(val)

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
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, SumaList):
            return val.__repr__()
        if isinstance(val, SumaOk):
            return val.__repr__()
        if isinstance(val, SumaErr):
            return val.__repr__()
        if isinstance(val, SumaObject):
            return f"{val.class_name} instance"
        if isinstance(val, SumaCallable):
            return repr(val)
        if isinstance(val, SumaPyObject):
            return _py_repr(val.value)
        return str(val)

    def _index(self, obj: Any, idx: Any) -> Any:
        if isinstance(obj, SumaList):
            if isinstance(idx, int):
                if idx < 0:
                    idx += len(obj.items)
                return obj.items[idx]
            raise VMError(f"List index must be Int, got {type(idx)}")
        if isinstance(obj, str):
            if isinstance(idx, int):
                return obj[idx]
            raise VMError(f"Str index must be Int, got {type(idx)}")
        if isinstance(obj, SumaPyObject):
            return self._python_index(obj, idx)
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
            return self._python_slice(obj, start, end)
        raise VMError(f"Cannot slice {type(obj)}")

    def _python_member(self, obj: SumaPyObject, name: str) -> Any:
        value = obj.value
        try:
            if isinstance(value, dict) and name in value:
                return _from_python_value(value[name])
            return _from_python_value(getattr(value, name))
        except AttributeError as exc:
            raise VMError(f"No Python member '{name}' on {type(value).__name__}") from exc

    def _python_index(self, obj: SumaPyObject, index: Any) -> Any:
        value = obj.value
        py_index = _to_python_value(index)
        try:
            return _from_python_value(value[py_index])
        except Exception as exc:
            raise VMError(f"Cannot index Python object {type(value).__name__}: {exc}") from exc

    def _python_slice(self, obj: SumaPyObject, start: Any, end: Any) -> Any:
        value = obj.value
        try:
            return _from_python_value(value[_to_python_value(start) : _to_python_value(end)])
        except Exception as exc:
            raise VMError(f"Cannot slice Python object {type(value).__name__}: {exc}") from exc

    def _call_python(self, callee: SumaPyObject, args: list) -> Any:
        func = callee.value
        if not callable(func):
            raise VMError(f"Python object {type(func).__name__} is not callable")
        py_args = [
            _to_python_value(
                SumaCallable(self, arg, "<arg>") if isinstance(arg, SumaLambda) else arg
            )
            for arg in args
        ]
        try:
            return _from_python_value(func(*py_args))
        except Exception as exc:
            name = getattr(func, "__name__", type(func).__name__)
            raise VMError(f"Python call '{name}' failed: {exc}") from exc

    def _member(self, obj: Any, name: str) -> Any:
        if isinstance(obj, SumaObject):
            if name in obj.fields:
                return obj.fields[name]
            # Look for method
            class_info = self.program.classes.get(obj.class_name, {})
            methods = class_info.get("methods", {})
            if name in methods:
                func_idx = methods[name]
                return SumaLambda(func_idx, [obj])  # bind 'this'
            # Getter
            getter = f"get_{name}"
            if getter in methods:
                func_idx = methods[getter]
                return SumaLambda(func_idx, [obj])
            raise VMError(f"No member '{name}' on {obj.class_name}")
        if isinstance(obj, SumaList):
            if name == "size":
                return len(obj.items)
            if name == "add":
                return SumaLambda(-1, [obj])  # special built-in
            raise VMError(f"No member '{name}' on List")
        if isinstance(obj, str):
            if name == "size":
                return len(obj)
            raise VMError(f"No member '{name}' on Str")
        if isinstance(obj, SumaOk):
            if name == "value":
                return obj.value
        if isinstance(obj, SumaErr):
            if name == "value":
                return obj.value
        if isinstance(obj, SumaPyObject):
            return self._python_member(obj, name)
        raise VMError(f"Cannot access member '{name}' on {type(obj)}")

    def _set_member(self, obj: Any, name: str, val: Any) -> None:
        if isinstance(obj, SumaObject):
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

    # built-in functions

    def _builtin_print(self, args: list) -> None:
        print(self._to_str(args[0]))
        return None

    def _builtin_str(self, args: list) -> str:
        return self._to_str(args[0])

    def _builtin_int(self, args: list) -> int:
        val = args[0]
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        if isinstance(val, str):
            return int(val)
        if isinstance(val, bool):
            return 1 if val else 0
        raise VMError(f"Cannot convert {type(val)} to Int")

    def _builtin_float(self, args: list) -> float:
        val = args[0]
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            return float(val)
        raise VMError(f"Cannot convert {type(val)} to Float")

    def _builtin_bool(self, args: list) -> bool:
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

    def _builtin_list(self, args: list) -> SumaList:
        return SumaList(list(args))

    def _builtin_unwrap(self, args: list) -> Any:
        val = args[0]
        if isinstance(val, SumaOk):
            return val.value
        raise VMError(f"Unwrap on Err: {val}")

    def _builtin_unwrap_or(self, args: list) -> Any:
        val, default = args[0], args[1]
        if isinstance(val, SumaOk):
            return val.value
        return default

    def _builtin_panic(self, args: list) -> None:
        raise VMError(f"Panic: {self._to_str(args[0])}")

    def _builtin_assert(self, args: list) -> None:
        cond = args[0]
        msg = self._to_str(args[1]) if len(args) > 1 else "Assertion failed"
        if not cond:
            raise VMError(f"Assert: {msg}")

    def _builtin_len(self, args: list) -> int:
        val = args[0]
        if isinstance(val, SumaList):
            return len(val.items)
        if isinstance(val, str):
            return len(val)
        raise VMError(f"len() not supported for {type(val)}")

    def _builtin_typeof(self, args: list) -> str:
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
        if isinstance(val, SumaOk):
            return "R"
        if isinstance(val, SumaErr):
            return "R"
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

    def _builtin_is_type(self, args: list) -> bool:
        return self._builtin_typeof([args[0]]) == args[1]

    def _builtin_parseint(self, args: list) -> Any:
        try:
            return SumaOk(int(args[0]))
        except (ValueError, TypeError) as e:
            return SumaErr(str(e))

    def _builtin_list_add(self, args: list) -> None:
        lst, val = args[0], args[1]
        if isinstance(lst, SumaList):
            lst.items.append(val)
        return None

    def _builtin_list_get(self, args: list) -> Any:
        lst, idx = args[0], args[1]
        if isinstance(lst, SumaList) and isinstance(idx, int):
            return lst.items[idx]
        raise VMError("get() requires List and Int")
