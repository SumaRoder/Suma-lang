"""IR optimizer for Suma-lang.

Applies optimization passes on the IR:
  1. Constant folding — evaluate constant expressions at compile time
  2. Dead code elimination — remove unused computations
  3. Constant propagation — replace variables with known constants
  4. Peephole optimizations — algebraic identities, strength reduction
"""

from __future__ import annotations

from typing import Optional

from . import *


def _is_constant(op: Operand) -> bool:
    """Check if an operand is an immediate constant."""
    return isinstance(op, Immediate)


def _get_constant(op: Operand) -> Optional[object]:
    """Get the constant value if it's an immediate."""
    if isinstance(op, Immediate):
        return op.value
    return None


def _try_fold_binary(op: str, left: object, right: object) -> Optional[object]:
    """Try to fold a binary operation on two constants."""
    try:
        if op == "add":
            if isinstance(left, str) or isinstance(right, str):
                return str(left) + str(right)
            return left + right
        elif op == "sub":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left - right
        elif op == "mul":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left * right
        elif op == "div":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if right == 0:
                    return None
                return (
                    left // right
                    if isinstance(left, int) and isinstance(right, int)
                    else left / right
                )
        elif op == "mod":
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if right == 0:
                    return None
                return left % right
        elif op == "eq":
            return left == right
        elif op == "ne":
            return left != right
        elif op == "gt":
            return left > right
        elif op == "lt":
            return left < right
        elif op == "ge":
            return left >= right
        elif op == "le":
            return left <= right
        elif op == "and":
            return left and right
        elif op == "or":
            return left or right
        elif op == "bit_and":
            if isinstance(left, int) and isinstance(right, int):
                return left & right
        elif op == "bit_or":
            if isinstance(left, int) and isinstance(right, int):
                return left | right
        elif op == "bit_xor":
            if isinstance(left, int) and isinstance(right, int):
                return left ^ right
        elif op == "shl":
            if isinstance(left, int) and isinstance(right, int):
                return left << right
        elif op == "shr":
            if isinstance(left, int) and isinstance(right, int):
                return left >> right
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def _try_fold_unary(op: str, val: object) -> Optional[object]:
    """Try to fold a unary operation on a constant."""
    try:
        if op == "neg":
            if isinstance(val, (int, float)):
                return -val
        elif op == "not":
            if isinstance(val, bool):
                return not val
        elif op == "bit_not":
            if isinstance(val, int):
                return ~val
    except (TypeError, ValueError):
        return None
    return None


# Map IR instruction classes to operation names
_BINOP_MAP = {
    Add: "add",
    Sub: "sub",
    Mul: "mul",
    Div: "div",
    Mod: "mod",
    Eq: "eq",
    Ne: "ne",
    Gt: "gt",
    Lt: "lt",
    Ge: "ge",
    Le: "le",
    And: "and",
    Or: "or",
    BitAnd: "bit_and",
    BitOr: "bit_or",
    BitXor: "bit_xor",
    Shl: "shl",
    Shr: "shr",
}

_UNOP_MAP = {
    Neg: "neg",
    Not: "not",
    BitNot: "bit_not",
}


def _constant_fold(block: BasicBlock) -> bool:
    """Fold constant expressions within a basic block."""
    changed = False
    new_instrs = []

    for instr in block.instrs:
        # Binary constant folding
        if type(instr) in _BINOP_MAP:
            left_val = _get_constant(instr.left)
            right_val = _get_constant(instr.right)
            if left_val is not None and right_val is not None:
                result = _try_fold_binary(_BINOP_MAP[type(instr)], left_val, right_val)
                if result is not None:
                    new_instrs.append(LoadConst(dest=instr.dest, value=result))
                    changed = True
                    continue

        # Unary constant folding
        if type(instr) in _UNOP_MAP:
            val = _get_constant(instr.src)
            if val is not None:
                result = _try_fold_unary(_UNOP_MAP[type(instr)], val)
                if result is not None:
                    new_instrs.append(LoadConst(dest=instr.dest, value=result))
                    changed = True
                    continue

        new_instrs.append(instr)

    if changed:
        block.instrs = new_instrs
    return changed


def _constant_propagation(block: BasicBlock) -> bool:
    """Propagate known constants through the block."""
    changed = False
    # Track which virtual registers hold constants
    reg_constants: dict[VirtualReg, object] = {}
    new_instrs = []

    for instr in block.instrs:
        # If this is a LoadConst, record the constant
        if isinstance(instr, LoadConst):
            reg_constants[instr.dest] = instr.value
            new_instrs.append(instr)
            continue

        # Try to replace operands with constants
        modified = False
        if (
            hasattr(instr, "left")
            and isinstance(instr.left, VirtualReg)
            and instr.left in reg_constants
        ):
            instr = _replace_operand(instr, "left", Immediate(reg_constants[instr.left]))
            modified = True
        if (
            hasattr(instr, "right")
            and isinstance(instr.right, VirtualReg)
            and instr.right in reg_constants
        ):
            instr = _replace_operand(instr, "right", Immediate(reg_constants[instr.right]))
            modified = True
        if (
            hasattr(instr, "src")
            and isinstance(instr.src, VirtualReg)
            and instr.src in reg_constants
        ):
            instr = _replace_operand(instr, "src", Immediate(reg_constants[instr.src]))
            modified = True
        if (
            hasattr(instr, "cond")
            and isinstance(instr.cond, VirtualReg)
            and instr.cond in reg_constants
        ):
            instr = _replace_operand(instr, "cond", Immediate(reg_constants[instr.cond]))
            modified = True

        if modified:
            changed = True

        # If this instruction writes to a register, invalidate it
        if hasattr(instr, "dest"):
            reg_constants.pop(instr.dest, None)

        new_instrs.append(instr)

    if changed:
        block.instrs = new_instrs
    return changed


def _replace_operand(instr: IRInstr, attr: str, new_val: Operand) -> IRInstr:
    """Replace an operand attribute on an instruction."""
    # Create a shallow copy and replace
    import copy

    new_instr = copy.copy(instr)
    setattr(new_instr, attr, new_val)
    return new_instr


def _collect_used_regs(func: IRFunction) -> set[VirtualReg]:
    used_regs: set[VirtualReg] = set()
    for block in func.blocks:
        for instr in block.instrs:
            _add_used_regs(instr, used_regs)
    return used_regs


def _add_used_regs(instr: IRInstr, used_regs: set[VirtualReg]) -> None:
    for attr in ("left", "right", "src", "cond", "obj", "index", "value", "callee"):
        operand = getattr(instr, attr, None)
        if isinstance(operand, VirtualReg):
            used_regs.add(operand)
    for attr in ("args", "elements", "captures"):
        for operand in getattr(instr, attr, ()):
            if isinstance(operand, VirtualReg):
                used_regs.add(operand)


def _dead_code_elimination(block: BasicBlock, used_regs: set[VirtualReg]) -> bool:
    """Remove instructions whose results are never used."""
    side_effect_ops = (
        StoreVar,
        StoreGlobal,
        StoreMember,
        StoreIndex,
        Print,
        Return,
        Jump,
        Branch,
        BranchFalse,
        Pop,
        SetIt,
        Call,
        CallGlobal,
        MakeObject,
        MakeList,
        MakeOk,
        MakeErr,
    )

    new_instrs = []
    removed = False
    for instr in block.instrs:
        if isinstance(instr, side_effect_ops):
            new_instrs.append(instr)
        elif hasattr(instr, "dest") and instr.dest not in used_regs:
            removed = True
        else:
            new_instrs.append(instr)

    if removed:
        block.instrs = new_instrs
    return removed


def _peephole(block: BasicBlock) -> bool:
    """Apply peephole optimizations."""
    changed = False
    new_instrs = []
    i = 0

    while i < len(block.instrs):
        instr = block.instrs[i]

        # x * 1 = x
        if isinstance(instr, Mul) and _get_constant(instr.right) == 1:
            new_instrs.append(instr)
            i += 1
            continue

        # x * 0 = 0
        if isinstance(instr, Mul) and _get_constant(instr.right) == 0:
            new_instrs.append(LoadConst(dest=instr.dest, value=0))
            changed = True
            i += 1
            continue

        new_instrs.append(instr)
        i += 1

    if changed:
        block.instrs = new_instrs
    return changed


def optimize_ir(program: IRProgram) -> IRProgram:
    """Optimize all functions in the IR program."""
    for func in program.functions:
        _optimize_function(func)
    return program


def _optimize_function(func: IRFunction) -> None:
    """Run optimization passes on a single function."""
    for _pass in range(10):
        changed = False

        for block in func.blocks:
            if _constant_fold(block):
                changed = True
            if _constant_propagation(block):
                changed = True
            if _peephole(block):
                changed = True

        used_regs = _collect_used_regs(func)
        for block in func.blocks:
            if _dead_code_elimination(block, used_regs):
                changed = True

        if not changed:
            break
