"""Opcode constants and per-opcode helpers used by the VM dispatch loop.

Pulling these out of ``vm.py`` keeps the main interpreter file focused on the
dispatch loop and frame management. The values here are imported back into
``vm`` and used directly — there is no extra indirection on the hot path.
"""

from __future__ import annotations

from typing import Any

from suma_lang.backend.codegen.opcodes import Op
from suma_lang.runtime.vm.errors import VMError
from suma_lang.runtime.vm.format import _to_str_fast
from suma_lang.runtime.vm.values import SumaList

__all__ = [
    "OC",
    "_apply_binop_fast",
    "_compare_values",
    "_CMP_METHODS",
    "_BINOP_METHODS",
]

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
