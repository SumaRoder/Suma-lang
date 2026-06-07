"""IR optimizer for Suma-lang.

Applies optimization passes on the IR:
  1. Constant folding — evaluate constant expressions at compile time
  2. Dead code elimination — remove unused computations
  3. Constant propagation — replace variables with known constants
  4. Peephole optimizations — algebraic identities, strength reduction
"""

from __future__ import annotations

from .ir import (
    Add,
    And,
    BasicBlock,
    BitAnd,
    BitNot,
    BitOr,
    BitXor,
    Branch,
    BranchFalse,
    Call,
    CallGlobal,
    Div,
    Eq,
    Ge,
    Gt,
    Immediate,
    IRFunction,
    IRInstr,
    IRProgram,
    IsErr,
    IsOk,
    Jump,
    Le,
    LoadConst,
    LoadGlobal,
    LoadIndex,
    LoadIt,
    LoadMember,
    LoadSlice,
    LoadThis,
    LoadVar,
    Lt,
    MakeErr,
    MakeLambda,
    MakeList,
    MakeObject,
    MakeOk,
    MakeRange,
    MakeTuple,
    Mod,
    Mul,
    Ne,
    Neg,
    Not,
    Operand,
    Or,
    Pop,
    Print,
    Return,
    SetIt,
    Shl,
    Shr,
    StoreGlobal,
    StoreIndex,
    StoreMember,
    StoreVar,
    Sub,
    UnwrapOk,
    VirtualReg,
)

_BINARY_INSTRS = (
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Eq,
    Ne,
    Gt,
    Lt,
    Ge,
    Le,
    And,
    Or,
    BitAnd,
    BitOr,
    BitXor,
    Shl,
    Shr,
)

_UNARY_INSTRS = (Neg, Not, BitNot)
_SRC_INSTRS = (StoreVar, SetIt, Pop, Print, Neg, Not, BitNot)
_DEST_INSTRS = (
    LoadConst,
    LoadVar,
    LoadGlobal,
    LoadThis,
    LoadIt,
    Call,
    CallGlobal,
    MakeList,
    MakeTuple,
    MakeRange,
    MakeOk,
    MakeErr,
    MakeLambda,
    MakeObject,
    LoadMember,
    LoadIndex,
    LoadSlice,
    IsOk,
    IsErr,
    UnwrapOk,
    *_BINARY_INSTRS,
    *_UNARY_INSTRS,
)
_PURE_DEST_INSTRS = (
    LoadConst,
    LoadVar,
    LoadGlobal,
    LoadThis,
    LoadIt,
    MakeLambda,
    MakeRange,
    LoadMember,
    LoadIndex,
    LoadSlice,
    IsOk,
    IsErr,
    UnwrapOk,
    *_BINARY_INSTRS,
    *_UNARY_INSTRS,
)


def _get_constant(op: Operand) -> object | None:
    """Get the constant value if it's an immediate."""
    if isinstance(op, Immediate):
        return op.value
    return None


def _try_fold_binary(op: str, left: object, right: object) -> object | None:
    """Try to fold a binary operation on two constants."""
    try:
        if op == "add":
            if isinstance(left, str) or isinstance(right, str):
                return str(left) + str(right)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
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
            if isinstance(left, str) and isinstance(right, str):
                return left > right
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left > right
        elif op == "lt":
            if isinstance(left, str) and isinstance(right, str):
                return left < right
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left < right
        elif op == "ge":
            if isinstance(left, str) and isinstance(right, str):
                return left >= right
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return left >= right
        elif op == "le":
            if isinstance(left, str) and isinstance(right, str):
                return left <= right
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
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
        elif op == "shl" and isinstance(left, int) and isinstance(right, int):
            return left << right
        elif op == "shr" and isinstance(left, int) and isinstance(right, int):
            return left >> right
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def _try_fold_unary(op: str, val: object) -> object | None:
    """Try to fold a unary operation on a constant."""
    try:
        if op == "neg":
            if isinstance(val, (int, float)):
                return -val
        elif op == "not" and isinstance(val, bool):
            return not val
        elif op == "bit_not" and isinstance(val, int):
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
        if isinstance(instr, _BINARY_INSTRS):
            left_val = _get_constant(instr.left)
            right_val = _get_constant(instr.right)
            if left_val is not None and right_val is not None:
                result = _try_fold_binary(_BINOP_MAP[type(instr)], left_val, right_val)
                if result is not None:
                    new_instrs.append(LoadConst(dest=instr.dest, value=result))
                    changed = True
                    continue

        # Unary constant folding
        if isinstance(instr, _UNARY_INSTRS):
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
        if isinstance(instr, _BINARY_INSTRS) and instr.left in reg_constants:
            instr = _replace_operand(instr, "left", Immediate(reg_constants[instr.left]))
            modified = True
        if isinstance(instr, _BINARY_INSTRS) and instr.right in reg_constants:
            instr = _replace_operand(instr, "right", Immediate(reg_constants[instr.right]))
            modified = True
        if (
            isinstance(instr, _SRC_INSTRS)
            and isinstance(instr.src, VirtualReg)
            and instr.src in reg_constants
        ):
            instr = _replace_operand(instr, "src", Immediate(reg_constants[instr.src]))
            modified = True
        if isinstance(instr, (Branch, BranchFalse)) and instr.cond in reg_constants:
            instr = _replace_operand(instr, "cond", Immediate(reg_constants[instr.cond]))
            modified = True

        if modified:
            changed = True

        # If this instruction writes to a register, invalidate it
        if isinstance(instr, _DEST_INSTRS):
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
    for attr in ("left", "right", "src", "cond", "obj", "index", "value", "callee", "start", "end"):
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
        MakeTuple,
        MakeRange,
        MakeOk,
        MakeErr,
    )

    new_instrs = []
    removed = False
    for instr in block.instrs:
        if isinstance(instr, side_effect_ops):
            new_instrs.append(instr)
        elif isinstance(instr, _PURE_DEST_INSTRS) and instr.dest not in used_regs:
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
