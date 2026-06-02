"""Bytecode opcodes for the Suma-lang VM."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any


class Op(IntEnum):
    # Stack
    LOAD_CONST = auto()  # arg: const index
    LOAD_VAR = auto()  # arg: variable slot
    STORE_VAR = auto()  # arg: variable slot
    LOAD_GLOBAL = auto()  # arg: const index (global name) — replaces LOAD_VAR -1
    CALL_GLOBAL = auto()  # arg: (nargs << 16) | func_idx — direct call, no string lookup
    LOAD_TRUE = auto()
    LOAD_FALSE = auto()
    LOAD_NULL = auto()
    LOAD_THIS = auto()
    LOAD_IT = auto()
    SET_IT = auto()
    POP = auto()
    DUP = auto()

    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    NEG = auto()

    # Bitwise
    BIT_AND = auto()
    BIT_OR = auto()
    BIT_XOR = auto()
    BIT_NOT = auto()
    SHL = auto()
    SHR = auto()

    # Logic
    NOT = auto()
    AND = auto()
    OR = auto()

    # Comparison
    EQ = auto()
    NE = auto()
    GT = auto()
    LT = auto()
    GE = auto()
    LE = auto()

    # Control flow
    JUMP = auto()  # arg: absolute offset
    JUMP_IF_FALSE = auto()  # arg: absolute offset
    JUMP_IF_TRUE = auto()  # arg: absolute offset

    # Functions
    CALL = auto()  # arg: nargs
    RETURN = auto()

    # Data structures
    MAKE_LIST = auto()  # arg: element count
    MAKE_OK = auto()
    MAKE_ERR = auto()
    INDEX = auto()
    SLICE = auto()  # arg: bitmask (1=has_start, 2=has_end)
    MEMBER = auto()  # arg: const index (member name)
    SET_MEMBER = auto()  # arg: const index (member name)

    # Object creation
    MAKE_OBJECT = auto()  # arg: const index (class name)
    MAKE_LAMBDA = auto()  # arg: function index

    # Pattern matching
    IS_OK = auto()
    IS_ERR = auto()
    UNWRAP_OK = auto()

    # I/O
    PRINT = auto()

    # Misc
    NOP = auto()
    HALT = auto()
    LOAD_FUNC = auto()  # arg: function index — push function value without lookup

    # Superinstructions emitted by the optimizer for hot paths.
    JUMP_IF_VAR_CMP = auto()  # args: left slot, right slot, cmp code, target
    JUMP_IF_VAR_CONST_CMP = auto()  # args: left slot, const index, cmp code, target
    INPLACE_VAR_VAR = auto()  # args: target slot, rhs slot, binary opcode
    INPLACE_VAR_CONST = auto()  # args: target slot, const index, binary opcode
    TAIL_CALL_GLOBAL = auto()  # arg: (nargs << 16) | func_idx — tail-call frame reuse
    LOOP_GENERIC = auto()  # variable args: condition descriptor + generic in-place ops
    SET_INDEX = auto()
    STORE_GLOBAL = auto()  # arg: const index (global name)
    MAKE_RANGE = auto()  # arg: 1 if inclusive, else 0


@dataclass
class Function:
    """Compiled function bytecode."""

    name: str
    arity: int
    code: list[int] = field(default_factory=list)
    constants: list[Any] = field(default_factory=list)
    locals_count: int = 0
    is_method: bool = False
    class_name: str | None = None
    capture_count: int = 0
    param_types: list[str | None] = field(default_factory=list)
    type_params: list[str] = field(default_factory=list)


@dataclass
class ProgramBytecode:
    """Top-level compiled program."""

    functions: list[Function] = field(default_factory=list)
    constants: list[Any] = field(default_factory=list)
    classes: dict[str, dict] = field(default_factory=dict)
    py_imports: dict[str, str] = field(default_factory=dict)  # alias -> Python module
    decorators: dict[str, int] = field(default_factory=dict)  # global name -> init function index
    method_decorators: dict[str, int] = field(default_factory=dict)  # Class.method -> init index
    overloads: dict[str, list[int]] = field(default_factory=dict)  # global name -> function indices
    entry: int = 0  # index of main function
