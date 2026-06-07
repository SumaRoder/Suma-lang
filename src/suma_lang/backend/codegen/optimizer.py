"""Bytecode optimizer for Suma-lang.

Applies multiple optimization passes on compiled bytecode:
  1. Constant folding  — evaluate constant expressions at compile time
  2. Dead code elimination — remove unreachable code after JUMP/RETURN
  3. Peephole optimizations — algebraic identities, constant conditions, NOPs
  4. Constant propagation — replace LOAD_VAR with LOAD_CONST when slot is known
"""

from __future__ import annotations

from dataclasses import dataclass, field

from suma_lang.backend.codegen.opcodes import Function, Op, ProgramBytecode

# Instruction representation

# Opcodes that take a single argument (the next int in code[])
_ARG_OPS = frozenset(
    {
        Op.LOAD_CONST,
        Op.LOAD_VAR,
        Op.STORE_VAR,
        Op.LOAD_GLOBAL,
        Op.STORE_GLOBAL,
        Op.CALL_GLOBAL,
        Op.LOAD_FUNC,
        Op.JUMP,
        Op.JUMP_IF_FALSE,
        Op.JUMP_IF_TRUE,
        Op.CALL,
        Op.MAKE_LIST,
        Op.MAKE_TUPLE,
        Op.MAKE_OBJECT,
        Op.MAKE_LAMBDA,
        Op.MAKE_RANGE,
        Op.IS_ENUM_VARIANT,
        Op.MEMBER,
        Op.SET_MEMBER,
        Op.SLICE,
        Op.TAIL_CALL_GLOBAL,
    }
)

_ARG_COUNTS = {op: 1 for op in _ARG_OPS}
_ARG_COUNTS[Op.MAKE_OBJECT] = 2
_ARG_COUNTS[Op.MAKE_ENUM] = 2
_ARG_COUNTS.update(
    {
        Op.JUMP_IF_VAR_CMP: 4,
        Op.JUMP_IF_VAR_CONST_CMP: 4,
        Op.INPLACE_VAR_VAR: 3,
        Op.INPLACE_VAR_CONST: 3,
    }
)

_JUMP_OPS = frozenset(
    {
        Op.JUMP,
        Op.JUMP_IF_FALSE,
        Op.JUMP_IF_TRUE,
        Op.JUMP_IF_VAR_CMP,
        Op.JUMP_IF_VAR_CONST_CMP,
    }
)

_CMP_TO_CODE = {
    Op.EQ: 0,
    Op.NE: 1,
    Op.GT: 2,
    Op.LT: 3,
    Op.GE: 4,
    Op.LE: 5,
}

_CMP_CODE_TO_NAME = {
    0: "==",
    1: "!=",
    2: ">",
    3: "<",
    4: ">=",
    5: "<=",
}

_OP_CODE_TO_NAME = {
    int(Op.ADD): "+",
    int(Op.SUB): "-",
    int(Op.MUL): "*",
    int(Op.DIV): "/",
    int(Op.MOD): "%",
}

_INPLACE_OPS = frozenset({Op.ADD, Op.SUB, Op.MUL, Op.DIV, Op.MOD})
_STACK_BINARY_OPS = frozenset(
    {
        Op.ADD,
        Op.SUB,
        Op.MUL,
        Op.DIV,
        Op.MOD,
        Op.BIT_AND,
        Op.BIT_OR,
        Op.BIT_XOR,
        Op.SHL,
        Op.SHR,
        Op.EQ,
        Op.NE,
        Op.GT,
        Op.LT,
        Op.GE,
        Op.LE,
    }
)


@dataclass
class Instr:
    """One decoded bytecode instruction."""

    op: Op
    arg: int | None = None
    args: tuple[int, ...] = field(default_factory=tuple)
    # Bookkeeping — original index in the flat code list (set during decode)
    orig_idx: int = 0


def _instr_len(instr: Instr) -> int:
    if instr.args:
        return 1 + len(instr.args)
    if instr.arg is not None:
        return 2
    return 1


def _arg(instr: Instr) -> int:
    if instr.arg is None:
        raise ValueError(f"Instruction {instr.op.name} has no argument")
    return instr.arg


def _const_at(constants: list[object], instr: Instr) -> object:
    return constants[_arg(instr)]


def decode(code: list[int]) -> list[Instr]:
    """Decode a flat code list into a list of Instr objects."""
    instrs: list[Instr] = []
    i = 0
    while i < len(code):
        op = Op(code[i])
        if op == Op.LOOP_GENERIC:
            arg_count = code[i + 1]
            args = tuple(code[i + 1 : i + 2 + arg_count])
            instrs.append(Instr(op=op, arg=arg_count, args=args, orig_idx=i))
            i += 2 + arg_count
            continue
        arg_count = _ARG_COUNTS.get(op, 0)
        if arg_count == 1:
            instrs.append(Instr(op=op, arg=code[i + 1], orig_idx=i))
            i += 1 + arg_count
        elif arg_count:
            args = tuple(code[i + 1 : i + 1 + arg_count])
            instrs.append(Instr(op=op, arg=args[0], args=args, orig_idx=i))
            i += 1 + arg_count
        else:
            instrs.append(Instr(op=op, orig_idx=i))
            i += 1
    return instrs


def encode(instrs: list[Instr]) -> list[int]:
    """Encode a list of Instr objects back to a flat code list."""
    code: list[int] = []
    for instr in instrs:
        code.append(int(instr.op))
        if instr.args:
            code.extend(instr.args)
        elif instr.arg is not None:
            code.append(instr.arg)
    return code


def format_instr(instr: Instr) -> str:
    """Return a compact pseudo-code representation of an optimized instruction."""
    if instr.op == Op.JUMP_IF_VAR_CMP and instr.args:
        left, right, cmp_code, target = instr.args
        return f"if !(local[{left}] {_CMP_CODE_TO_NAME.get(cmp_code, '?')} local[{right}]) jump {target}"
    if instr.op == Op.JUMP_IF_VAR_CONST_CMP and instr.args:
        left, const_idx, cmp_code, target = instr.args
        return f"if !(local[{left}] {_CMP_CODE_TO_NAME.get(cmp_code, '?')} const[{const_idx}]) jump {target}"
    if instr.op == Op.INPLACE_VAR_VAR and instr.args:
        target, rhs, op_code = instr.args
        return (
            f"local[{target}] = local[{target}] {_OP_CODE_TO_NAME.get(op_code, '?')} local[{rhs}]"
        )
    if instr.op == Op.INPLACE_VAR_CONST and instr.args:
        target, const_idx, op_code = instr.args
        return f"local[{target}] = local[{target}] {_OP_CODE_TO_NAME.get(op_code, '?')} const[{const_idx}]"
    if instr.op == Op.TAIL_CALL_GLOBAL and instr.arg is not None:
        func_idx = instr.arg & 0xFFFF
        nargs = instr.arg >> 16
        return f"tailcall function[{func_idx}] argc={nargs}"
    if instr.op == Op.LOOP_GENERIC and instr.args:
        arg_count, left, right, cmp_code, op_count, *ops = instr.args
        parts = [
            f"loop while !(local[{left}] {_CMP_CODE_TO_NAME.get(cmp_code, '?')} local[{right}])"
        ]
        for op_index in range(op_count):
            start = op_index * 3
            target, rhs, op_code = ops[start : start + 3]
            rhs_text = f"const[{~rhs}]" if rhs < 0 else f"local[{rhs}]"
            parts.append(
                f"local[{target}] = local[{target}] {_OP_CODE_TO_NAME.get(op_code, '?')} {rhs_text}"
            )
        return "; ".join(parts) + f"  # args={arg_count}"
    if instr.args:
        return f"{instr.op.name} {', '.join(str(arg) for arg in instr.args)}"
    if instr.arg is not None:
        return f"{instr.op.name} {instr.arg}"
    return instr.op.name


def format_program(program: ProgramBytecode) -> str:
    """Format optimized bytecode as readable pseudo-code for diagnostics."""
    lines: list[str] = []
    for index, fn in enumerate(program.functions):
        lines.append(f"function[{index}] {fn.name}/{fn.arity} locals={fn.locals_count}")
        for instr in decode(fn.code):
            lines.append(f"  @{instr.orig_idx:04d} {format_instr(instr)}")
    return "\n".join(lines)


# Jump target analysis


def _find_jump_targets(instrs: list[Instr]) -> set[int]:
    """Return the set of *encoded* offsets that are jump targets."""
    targets: set[int] = set()
    for instr in instrs:
        if instr.op in (Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE) and instr.arg is not None:
            targets.add(instr.arg)
        elif instr.op in (Op.JUMP_IF_VAR_CMP, Op.JUMP_IF_VAR_CONST_CMP) and instr.args:
            targets.add(instr.args[3])
    return targets


def _has_jump_target(
    instrs: list[Instr],
    jump_targets: set[int],
    start: int,
    length: int,
) -> bool:
    """Return True when any instruction in a slice is a jump target."""
    end = min(len(instrs), start + length)
    return any(instrs[idx].orig_idx in jump_targets for idx in range(start, end))


def _build_offset_map(instrs: list[Instr]) -> dict[int, int]:
    """Map encoded offset → index in the instrs list."""
    return {instr.orig_idx: i for i, instr in enumerate(instrs)}


def _remap_jumps(instrs: list[Instr]) -> list[Instr]:
    """After instructions are removed/reordered, fix all jump targets.

    Strategy: build old-offset → new-offset mapping, then patch.
    """
    # Build new encoded offsets
    new_offsets: list[int] = []
    pos = 0
    for instr in instrs:
        new_offsets.append(pos)
        pos += _instr_len(instr)

    # Map old encoded offset → new encoded offset
    old_to_new: dict[int, int] = {}
    for i, instr in enumerate(instrs):
        old_to_new[instr.orig_idx] = new_offsets[i]

    # Patch jump targets
    for instr in instrs:
        if instr.op in (Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE):
            if instr.arg is not None and instr.arg in old_to_new:
                instr.arg = old_to_new[instr.arg]
        elif instr.op in (Op.JUMP_IF_VAR_CMP, Op.JUMP_IF_VAR_CONST_CMP) and instr.args:
            target = instr.args[3]
            if target in old_to_new:
                instr.args = (*instr.args[:3], old_to_new[target])

    return instrs


def _thread_jumps(instrs: list[Instr]) -> list[Instr]:
    """Redirect jumps that target an unconditional jump trampoline."""
    if not instrs:
        return instrs

    offset_map = _build_offset_map(instrs)

    def resolve(target: int) -> int:
        seen: set[int] = set()
        while target not in seen:
            seen.add(target)
            target_index = offset_map.get(target)
            if target_index is None:
                break
            target_instr = instrs[target_index]
            if target_instr.op == Op.JUMP and target_instr.arg is not None:
                target = target_instr.arg
                continue
            break
        return target

    changed = False
    for instr in instrs:
        if instr.op in (Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE):
            if instr.arg is None:
                continue
            target = resolve(instr.arg)
            if target != instr.arg:
                instr.arg = target
                changed = True
        elif instr.op in (Op.JUMP_IF_VAR_CMP, Op.JUMP_IF_VAR_CONST_CMP) and instr.args:
            target = resolve(instr.args[3])
            if target != instr.args[3]:
                instr.args = (*instr.args[:3], target)
                changed = True

    return instrs if changed else instrs


# Optimization passes


def _constant_fold(instrs: list[Instr], constants: list[object]) -> list[Instr]:
    """Fold constant arithmetic/logic expressions.

    Pattern: LOAD_CONST a; LOAD_CONST b; BINOP → LOAD_CONST (a op b)
    Also:   LOAD_CONST x; NEG/NOT/BIT_NOT → LOAD_CONST (~x / -x / not x)
    """
    result: list[Instr] = []
    i = 0
    changed = False
    jump_targets = _find_jump_targets(instrs)

    while i < len(instrs):
        # Unary constant folding
        if (
            i + 1 < len(instrs)
            and instrs[i].op == Op.LOAD_CONST
            and instrs[i + 1].op in (Op.NEG, Op.NOT, Op.BIT_NOT)
            and not _has_jump_target(instrs, jump_targets, i + 1, 1)
        ):
            val = _const_at(constants, instrs[i])
            unop = instrs[i + 1].op
            folded = _try_fold_unary(val, unop)
            if folded is not _SENTINEL:
                new_idx = _ensure_constant(constants, folded)
                result.append(Instr(op=Op.LOAD_CONST, arg=new_idx, orig_idx=instrs[i].orig_idx))
                i += 2
                changed = True
                continue

        # Binary constant folding
        if (
            i + 2 < len(instrs)
            and instrs[i].op == Op.LOAD_CONST
            and instrs[i + 1].op == Op.LOAD_CONST
            and instrs[i + 2].op in _BINOP_SET
            and not _has_jump_target(instrs, jump_targets, i + 1, 2)
        ):
            a = _const_at(constants, instrs[i])
            b = _const_at(constants, instrs[i + 1])
            binop = instrs[i + 2].op
            folded = _try_fold_binary(a, b, binop)
            if folded is not _SENTINEL:
                new_idx = _ensure_constant(constants, folded)
                result.append(Instr(op=Op.LOAD_CONST, arg=new_idx, orig_idx=instrs[i].orig_idx))
                i += 3
                changed = True
                continue

        result.append(instrs[i])
        i += 1

    return result if changed else instrs


def _is_control_flow_boundary(instr: Instr, jump_targets: set[int]) -> bool:
    return (
        instr.orig_idx in jump_targets or instr.op in _JUMP_OPS or instr.op in (Op.RETURN, Op.HALT)
    )


def _elide_single_use_temp_slots(
    instrs: list[Instr],
    protected_slots: set[int] | None = None,
) -> list[Instr]:
    """Remove STORE_VAR/POP/LOAD_VAR shuttles for one-off temp slots.

    IR code generation spills every virtual register into a dedicated local slot.
    For slots that are written once and read once in a straight-line region, the
    stack value can stay live directly, so the spill/load pair is redundant.
    """
    if not instrs:
        return instrs

    protected_slots = protected_slots or set()
    jump_targets = _find_jump_targets(instrs)
    store_positions: dict[int, list[int]] = {}
    load_positions: dict[int, list[int]] = {}

    for index, instr in enumerate(instrs):
        if (
            instr.op == Op.STORE_VAR
            and instr.arg is not None
            and index + 1 < len(instrs)
            and instrs[index + 1].op == Op.POP
        ):
            store_positions.setdefault(instr.arg, []).append(index)
        elif instr.op == Op.LOAD_VAR and instr.arg is not None:
            load_positions.setdefault(instr.arg, []).append(index)

    remove_indices: set[int] = set()
    changed = False

    for slot, stores in store_positions.items():
        if slot in protected_slots:
            continue
        loads = load_positions.get(slot, [])
        if len(stores) != 1 or len(loads) != 1:
            continue

        store_index = stores[0]
        load_index = loads[0]
        if load_index <= store_index + 1:
            continue

        if any(
            _is_control_flow_boundary(instrs[index], jump_targets)
            for index in range(store_index, load_index + 1)
        ):
            continue
        # Keeping the stored value live on the stack is only trivially safe
        # when the reload immediately follows STORE/POP. Longer intervals can
        # cross with other spill intervals and reorder operands.
        if load_index != store_index + 2:
            continue

        remove_indices.add(store_index)
        remove_indices.add(store_index + 1)
        remove_indices.add(load_index)
        changed = True

    if not changed:
        return instrs

    return [instr for index, instr in enumerate(instrs) if index not in remove_indices]


def _capture_slots_referenced_by_lambdas(
    instrs: list[Instr],
    functions: list[Function],
) -> set[int]:
    slots: set[int] = set()
    for instr in instrs:
        if instr.op != Op.MAKE_LAMBDA or instr.arg is None:
            continue
        if instr.arg < 0 or instr.arg >= len(functions):
            continue
        slots.update(functions[instr.arg].capture_slots)
    return slots


_SENTINEL = object()  # signals "could not fold"

_BINOP_SET = frozenset(
    {
        Op.ADD,
        Op.SUB,
        Op.MUL,
        Op.DIV,
        Op.MOD,
        Op.BIT_AND,
        Op.BIT_OR,
        Op.BIT_XOR,
        Op.SHL,
        Op.SHR,
        Op.EQ,
        Op.NE,
        Op.GT,
        Op.LT,
        Op.GE,
        Op.LE,
        Op.AND,
        Op.OR,
    }
)


def _try_fold_unary(val: object, op: Op) -> object:
    """Try to fold a unary operation on a constant. Returns _SENTINEL on failure."""
    if op == Op.NEG:
        if isinstance(val, (int, float)):
            return -val
    elif op == Op.NOT and isinstance(val, bool):
        return not val
    elif op == Op.BIT_NOT and isinstance(val, int):
        return ~val
    return _SENTINEL


def _try_fold_binary(a: object, b: object, op: Op) -> object:
    """Try to fold a binary operation on two constants. Returns _SENTINEL on failure."""
    try:
        if op == Op.ADD:
            if isinstance(a, str) or isinstance(b, str):
                return _to_str(a) + _to_str(b)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a + b
        elif op == Op.SUB:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a - b
        elif op == Op.MUL:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a * b
        elif op == Op.DIV:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if b == 0:
                    return _SENTINEL  # don't fold division by zero
                return a // b if isinstance(a, int) and isinstance(b, int) else a / b
        elif op == Op.MOD:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if b == 0:
                    return _SENTINEL
                return a % b
        elif op == Op.BIT_AND:
            if isinstance(a, int) and isinstance(b, int):
                return a & b
        elif op == Op.BIT_OR:
            if isinstance(a, int) and isinstance(b, int):
                return a | b
        elif op == Op.BIT_XOR:
            if isinstance(a, int) and isinstance(b, int):
                return a ^ b
        elif op == Op.SHL:
            if isinstance(a, int) and isinstance(b, int):
                return a << b
        elif op == Op.SHR:
            if isinstance(a, int) and isinstance(b, int):
                return a >> b
        elif op == Op.EQ:
            return a == b
        elif op == Op.NE:
            return a != b
        elif op == Op.GT:
            if isinstance(a, str) and isinstance(b, str):
                return a > b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a > b
        elif op == Op.LT:
            if isinstance(a, str) and isinstance(b, str):
                return a < b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a < b
        elif op == Op.GE:
            if isinstance(a, str) and isinstance(b, str):
                return a >= b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a >= b
        elif op == Op.LE:
            if isinstance(a, str) and isinstance(b, str):
                return a <= b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a <= b
        elif op == Op.AND:
            return a and b
        elif op == Op.OR:
            return a or b
    except (TypeError, ValueError, ZeroDivisionError):
        return _SENTINEL
    return _SENTINEL


def _to_str(val: object) -> str:
    """Mimic the VM's string conversion for constant folding of string concat."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def _ensure_constant(constants: list[object], value: object) -> int:
    """Add a constant if not already present; return its index."""
    for i, c in enumerate(constants):
        if type(c) is type(value) and c == value:
            return i
    idx = len(constants)
    constants.append(value)
    return idx


# Dead code elimination


def _eliminate_dead_code(instrs: list[Instr]) -> list[Instr]:
    """Remove unreachable instructions after unconditional JUMP and RETURN.

    An instruction is reachable if:
      - It is the first instruction
      - It is the target of a jump
      - It immediately follows a non-jump/non-return instruction
    """
    if not instrs:
        return instrs

    jump_targets = _find_jump_targets(instrs)
    offset_map = _build_offset_map(instrs)

    # Mark reachable instructions
    reachable = [False] * len(instrs)
    reachable[0] = True  # entry point

    i = 0
    while i < len(instrs):
        if not reachable[i]:
            i += 1
            continue

        instr = instrs[i]

        # If this is a jump target, mark it reachable
        if instr.orig_idx in jump_targets:
            reachable[i] = True

        # Determine what comes next
        if instr.op in (Op.JUMP, Op.RETURN, Op.HALT):
            # Next instruction is NOT reachable through fall-through
            # But the jump target IS reachable
            if instr.op == Op.JUMP and instr.arg is not None:
                target_idx = offset_map.get(instr.arg)
                if target_idx is not None:
                    reachable[target_idx] = True
        elif instr.op in (Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE):
            # Fall-through is reachable, and so is the jump target
            if i + 1 < len(instrs):
                reachable[i + 1] = True
            if instr.arg is not None:
                target_idx = offset_map.get(instr.arg)
                if target_idx is not None:
                    reachable[target_idx] = True
        elif instr.op in (Op.JUMP_IF_VAR_CMP, Op.JUMP_IF_VAR_CONST_CMP):
            if i + 1 < len(instrs):
                reachable[i + 1] = True
            if instr.args:
                target_idx = offset_map.get(instr.args[3])
                if target_idx is not None:
                    reachable[target_idx] = True
        else:
            # Normal instruction — next is reachable
            if i + 1 < len(instrs):
                reachable[i + 1] = True

        i += 1

    # Also mark jump targets as reachable (in case they were missed)
    for i, instr in enumerate(instrs):
        if instr.orig_idx in jump_targets:
            reachable[i] = True

    # Filter out unreachable instructions
    new_instrs = [instr for i, instr in enumerate(instrs) if reachable[i]]

    if len(new_instrs) < len(instrs):
        return new_instrs
    return instrs


# Peephole optimizations


def _peephole(instrs: list[Instr], constants: list[object]) -> list[Instr]:
    """Apply peephole pattern matching optimizations."""
    result: list[Instr] = list(instrs)
    changed = True

    while changed:
        changed = False
        jump_targets = _find_jump_targets(result)

        def has_jump_target(
            start: int,
            length: int,
            *,
            result: list[Instr] = result,
            jump_targets: set[int] = jump_targets,
        ) -> bool:
            return any(result[start + offset].orig_idx in jump_targets for offset in range(length))

        new_result: list[Instr] = []
        i = 0

        while i < len(result):
            instr = result[i]

            # Constant conditional jumps
            # LOAD_CONST true; JUMP_IF_FALSE → remove both (condition always true, fall through)
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.JUMP_IF_FALSE
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val is True:
                    # Always true → skip the jump, just pop the value
                    new_result.append(Instr(op=Op.POP, orig_idx=instr.orig_idx))
                    i += 2
                    changed = True
                    continue
                elif val is False:
                    # Always false → replace with unconditional JUMP
                    new_result.append(
                        Instr(op=Op.JUMP, arg=result[i + 1].arg, orig_idx=instr.orig_idx)
                    )
                    i += 2
                    changed = True
                    continue

            # LOAD_CONST true; JUMP_IF_TRUE → unconditional JUMP
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.JUMP_IF_TRUE
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val is True:
                    new_result.append(
                        Instr(op=Op.JUMP, arg=result[i + 1].arg, orig_idx=instr.orig_idx)
                    )
                    i += 2
                    changed = True
                    continue
                elif val is False:
                    # Always false → skip the jump, just pop
                    new_result.append(Instr(op=Op.POP, orig_idx=instr.orig_idx))
                    i += 2
                    changed = True
                    continue

            # LOAD_TRUE/FALSE; NOT → LOAD_FALSE/TRUE
            if (
                i + 1 < len(result)
                and instr.op in (Op.LOAD_TRUE, Op.LOAD_FALSE)
                and result[i + 1].op == Op.NOT
            ):
                new_op = Op.LOAD_FALSE if instr.op == Op.LOAD_TRUE else Op.LOAD_TRUE
                new_result.append(Instr(op=new_op, orig_idx=instr.orig_idx))
                i += 2
                changed = True
                continue

            # Dead stores: LOAD_CONST x; POP → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.POP
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # Dead stores: LOAD_TRUE/FALSE/NULL; POP → remove both
            if (
                i + 1 < len(result)
                and instr.op in (Op.LOAD_TRUE, Op.LOAD_FALSE, Op.LOAD_NULL)
                and result[i + 1].op == Op.POP
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # DUP; POP → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.DUP
                and result[i + 1].op == Op.POP
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # JUMP to next instruction → NOP
            if instr.op == Op.JUMP and instr.arg is not None:
                # Compute the encoded offset of the next instruction
                next_orig = result[i + 1].orig_idx if i + 1 < len(result) else None
                if next_orig is not None and instr.arg == next_orig and not has_jump_target(i, 1):
                    i += 1  # skip the JUMP entirely
                    changed = True
                    continue

            # Algebraic identities
            # LOAD_CONST 0; ADD → remove both (x + 0 = x)
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.ADD
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val == 0 and isinstance(val, (int, float)):
                    i += 2
                    changed = True
                    continue

            # LOAD_CONST 0; SUB → NEG (x - 0 = x, but also handle 0 - x pattern)
            # Actually: stack is [..., x, 0]; SUB → x - 0 = x → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.SUB
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val == 0 and isinstance(val, (int, float)):
                    i += 2
                    changed = True
                    continue

            # LOAD_CONST 1; MUL → remove both (x * 1 = x)
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.MUL
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val == 1 and isinstance(val, (int, float)):
                    i += 2
                    changed = True
                    continue

            # LOAD_CONST 1; DIV → remove both (x / 1 = x)
            if (
                i + 1 < len(result)
                and instr.op == Op.LOAD_CONST
                and result[i + 1].op == Op.DIV
                and not has_jump_target(i, 2)
            ):
                val = _const_at(constants, instr)
                if val == 1 and isinstance(val, (int, float)):
                    i += 2
                    changed = True
                    continue

            # ── Double negation / double NOT ──────────────
            # NEG; NEG → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.NEG
                and result[i + 1].op == Op.NEG
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # NOT; NOT → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.NOT
                and result[i + 1].op == Op.NOT
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # BIT_NOT; BIT_NOT → remove both
            if (
                i + 1 < len(result)
                and instr.op == Op.BIT_NOT
                and result[i + 1].op == Op.BIT_NOT
                and not has_jump_target(i, 2)
            ):
                i += 2
                changed = True
                continue

            # NOP elimination
            if instr.op == Op.NOP and not has_jump_target(i, 1):
                i += 1
                changed = True
                continue

            new_result.append(instr)
            i += 1

        result = new_result

    return result


# Constant propagation


def _constant_propagation(instrs: list[Instr], constants: list[object]) -> list[Instr]:
    """Replace LOAD_VAR with LOAD_CONST when the slot was last stored with a constant.

    Only propagates within straight-line code (resets at jump targets).
    """
    jump_targets = _find_jump_targets(instrs)

    # slot → const index (None means "not a known constant")
    slot_const: dict[int, int | None] = {}
    result: list[Instr] = []
    changed = False

    for instr in instrs:
        # Reset at jump targets (conservative)
        if instr.orig_idx in jump_targets:
            slot_const.clear()

        if instr.op == Op.STORE_VAR and instr.arg is not None:
            # Check if the previous instruction loaded a constant
            slot_const[_arg(instr)] = (
                result[-1].arg if result and result[-1].op == Op.LOAD_CONST else None
            )

        elif instr.op in (Op.INPLACE_VAR_VAR, Op.INPLACE_VAR_CONST) and instr.args:
            slot_const[instr.args[0]] = None

        elif instr.op == Op.LOOP_GENERIC and instr.args:
            op_count_index = 4
            op_count = instr.args[op_count_index]
            for op_index in range(op_count):
                start = op_count_index + 1 + op_index * 3
                slot_const[instr.args[start]] = None

        elif (
            instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instr.arg >= 0
            and instr.arg in slot_const
            and slot_const[instr.arg] is not None
        ):
            # Replace with LOAD_CONST
            result.append(
                Instr(op=Op.LOAD_CONST, arg=slot_const[_arg(instr)], orig_idx=instr.orig_idx)
            )
            changed = True
            continue

        result.append(instr)

    return result if changed else instrs


def _superinstructions(instrs: list[Instr]) -> list[Instr]:
    """Fuse common stack bytecode sequences into VM superinstructions."""
    result: list[Instr] = []
    jump_targets = _find_jump_targets(instrs)
    slot_stores = _count_slot_stores(instrs)
    slot_reads = _count_slot_reads(instrs)
    changed = False
    i = 0

    while i < len(instrs):
        instr = instrs[i]

        # IR spill shape for direct-call arguments:
        # LOAD a; STORE t1; POP; LOAD b; STORE t2; POP;
        # LOAD t1; LOAD t2; CALL_GLOBAL nargs
        if instr.op in (Op.LOAD_VAR, Op.LOAD_CONST) and instr.arg is not None:
            sources: list[Instr] = []
            temps: list[int] = []
            j = i
            while (
                j + 2 < len(instrs)
                and instrs[j].op in (Op.LOAD_VAR, Op.LOAD_CONST)
                and instrs[j].arg is not None
                and instrs[j + 1].op == Op.STORE_VAR
                and instrs[j + 1].arg is not None
                and instrs[j + 2].op == Op.POP
            ):
                sources.append(instrs[j])
                temps.append(_arg(instrs[j + 1]))
                j += 3
            if sources and j + len(temps) < len(instrs):
                call_index = j + len(temps)
                call_instr = instrs[call_index]
                arg_loads = instrs[j:call_index]
                args_match = True
                temps_single_use = True
                for offset, temp in enumerate(temps):
                    arg_load = arg_loads[offset]
                    source = sources[offset]
                    const_reload = (
                        source.op == Op.LOAD_CONST
                        and arg_load.op == Op.LOAD_CONST
                        and arg_load.arg == source.arg
                    )
                    var_reload = arg_load.op == Op.LOAD_VAR and arg_load.arg == temp
                    if not (var_reload or const_reload):
                        args_match = False
                        break
                    read_count = slot_reads.get(temp, 0)
                    if slot_stores.get(temp) != 1 or read_count != (1 if var_reload else 0):
                        temps_single_use = False
                        break

                if (
                    call_instr.op == Op.CALL_GLOBAL
                    and call_instr.arg is not None
                    and (call_instr.arg >> 16) == len(temps)
                    and args_match
                    and not _has_jump_target(instrs, jump_targets, i + 1, call_index - i)
                    and temps_single_use
                ):
                    result.extend((*sources, call_instr))
                    i = call_index + 1
                    changed = True
                    continue

        # IR spill shape:
        # LOAD_VAR dst; STORE_VAR t1; POP; LOAD_VAR rhs; STORE_VAR t2; POP;
        # LOAD_VAR t1; LOAD_VAR t2; BINOP; STORE_VAR dst; POP
        if (
            i + 10 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.STORE_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op == Op.POP
            and instrs[i + 3].op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instrs[i + 3].arg is not None
            and instrs[i + 4].op == Op.STORE_VAR
            and instrs[i + 4].arg is not None
            and instrs[i + 5].op == Op.POP
            and instrs[i + 6].op == Op.LOAD_VAR
            and instrs[i + 6].arg == instrs[i + 1].arg
            and instrs[i + 7].op == Op.LOAD_VAR
            and instrs[i + 7].arg == instrs[i + 4].arg
            and instrs[i + 8].op in _INPLACE_OPS
            and instrs[i + 9].op == Op.STORE_VAR
            and instrs[i + 9].arg == instr.arg
            and instrs[i + 10].op == Op.POP
            and not _has_jump_target(instrs, jump_targets, i + 1, 10)
        ):
            left_temp = _arg(instrs[i + 1])
            right_temp = _arg(instrs[i + 4])
            if (
                slot_stores.get(left_temp) == 1
                and slot_stores.get(right_temp) == 1
                and slot_reads.get(left_temp) == 1
                and slot_reads.get(right_temp) == 1
            ):
                if instrs[i + 3].op == Op.LOAD_VAR:
                    result.append(
                        Instr(
                            op=Op.INPLACE_VAR_VAR,
                            arg=_arg(instr),
                            args=(_arg(instr), _arg(instrs[i + 3]), int(instrs[i + 8].op)),
                            orig_idx=instr.orig_idx,
                        )
                    )
                else:
                    result.append(
                        Instr(
                            op=Op.INPLACE_VAR_CONST,
                            arg=_arg(instr),
                            args=(_arg(instr), _arg(instrs[i + 3]), int(instrs[i + 8].op)),
                            orig_idx=instr.orig_idx,
                        )
                    )
                i += 11
                changed = True
                continue

        # IR spill shape for a plain binary expression assigned to a slot:
        # LOAD a; STORE t1; POP; LOAD b; STORE t2; POP;
        # LOAD t1; LOAD t2; BINOP; STORE dst; POP
        if (
            i + 10 < len(instrs)
            and instr.op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instr.arg is not None
            and instrs[i + 1].op == Op.STORE_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op == Op.POP
            and instrs[i + 3].op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instrs[i + 3].arg is not None
            and instrs[i + 4].op == Op.STORE_VAR
            and instrs[i + 4].arg is not None
            and instrs[i + 5].op == Op.POP
            and instrs[i + 6].op == Op.LOAD_VAR
            and instrs[i + 6].arg == instrs[i + 1].arg
            and instrs[i + 7].op == Op.LOAD_VAR
            and instrs[i + 7].arg == instrs[i + 4].arg
            and instrs[i + 8].op in _STACK_BINARY_OPS
            and instrs[i + 9].op == Op.STORE_VAR
            and instrs[i + 9].arg is not None
            and instrs[i + 10].op == Op.POP
            and not _has_jump_target(instrs, jump_targets, i + 1, 10)
        ):
            left_temp = _arg(instrs[i + 1])
            right_temp = _arg(instrs[i + 4])
            if (
                slot_stores.get(left_temp) == 1
                and slot_stores.get(right_temp) == 1
                and slot_reads.get(left_temp) == 1
                and slot_reads.get(right_temp) == 1
            ):
                result.extend(
                    (
                        instr,
                        instrs[i + 3],
                        instrs[i + 8],
                        instrs[i + 9],
                        instrs[i + 10],
                    )
                )
                i += 11
                changed = True
                continue

        # IR spill shape for a plain binary expression returned directly:
        # LOAD a; STORE t1; POP; LOAD b; STORE t2; POP;
        # LOAD t1; LOAD t2; BINOP; RETURN
        if (
            i + 9 < len(instrs)
            and instr.op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instr.arg is not None
            and instrs[i + 1].op == Op.STORE_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op == Op.POP
            and instrs[i + 3].op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instrs[i + 3].arg is not None
            and instrs[i + 4].op == Op.STORE_VAR
            and instrs[i + 4].arg is not None
            and instrs[i + 5].op == Op.POP
            and instrs[i + 6].op == Op.LOAD_VAR
            and instrs[i + 6].arg == instrs[i + 1].arg
            and instrs[i + 7].op == Op.LOAD_VAR
            and instrs[i + 7].arg == instrs[i + 4].arg
            and instrs[i + 8].op in _STACK_BINARY_OPS
            and instrs[i + 9].op == Op.RETURN
            and not _has_jump_target(instrs, jump_targets, i + 1, 9)
        ):
            left_temp = _arg(instrs[i + 1])
            right_temp = _arg(instrs[i + 4])
            if (
                slot_stores.get(left_temp) == 1
                and slot_stores.get(right_temp) == 1
                and slot_reads.get(left_temp) == 1
                and slot_reads.get(right_temp) == 1
            ):
                result.extend((instr, instrs[i + 3], instrs[i + 8], instrs[i + 9]))
                i += 10
                changed = True
                continue

        # IR spill shape feeding a fused comparison jump:
        # LOAD_VAR a; STORE_VAR t1; POP; LOAD_VAR/CONST b; STORE_VAR t2; POP;
        # JUMP_IF_VAR_CMP t1, t2, cmp, target
        if (
            i + 6 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.STORE_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op == Op.POP
            and instrs[i + 3].op in (Op.LOAD_VAR, Op.LOAD_CONST)
            and instrs[i + 3].arg is not None
            and instrs[i + 4].op == Op.STORE_VAR
            and instrs[i + 4].arg is not None
            and instrs[i + 5].op == Op.POP
            and instrs[i + 6].op == Op.JUMP_IF_VAR_CMP
            and instrs[i + 6].args
            and instrs[i + 6].args[0] == instrs[i + 1].arg
            and instrs[i + 6].args[1] == instrs[i + 4].arg
            and not _has_jump_target(instrs, jump_targets, i + 1, 6)
        ):
            left_temp = _arg(instrs[i + 1])
            right_temp = _arg(instrs[i + 4])
            if (
                slot_stores.get(left_temp) == 1
                and slot_stores.get(right_temp) == 1
                and slot_reads.get(left_temp) == 1
                and slot_reads.get(right_temp) == 1
            ):
                _, _, cmp_code, target = instrs[i + 6].args
                if instrs[i + 3].op == Op.LOAD_VAR:
                    result.append(
                        Instr(
                            op=Op.JUMP_IF_VAR_CMP,
                            arg=_arg(instr),
                            args=(_arg(instr), _arg(instrs[i + 3]), cmp_code, target),
                            orig_idx=instr.orig_idx,
                        )
                    )
                else:
                    result.append(
                        Instr(
                            op=Op.JUMP_IF_VAR_CONST_CMP,
                            arg=_arg(instr),
                            args=(_arg(instr), _arg(instrs[i + 3]), cmp_code, target),
                            orig_idx=instr.orig_idx,
                        )
                    )
                i += 7
                changed = True
                continue

        # JUMP_IF_VAR_CMP body; JUMP exit; INPLACE_* body...; JUMP loop
        if (
            i + 4 < len(instrs)
            and instr.op == Op.JUMP_IF_VAR_CMP
            and instr.args
            and instrs[i + 1].op == Op.JUMP
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op in (Op.INPLACE_VAR_VAR, Op.INPLACE_VAR_CONST)
            and instrs[i + 2].args
            and instr.args[3] == instrs[i + 2].orig_idx
            and instrs[i + 1].orig_idx not in jump_targets
        ):
            body_ops: list[Instr] = []
            j = i + 2
            while (
                j < len(instrs)
                and instrs[j].op in (Op.INPLACE_VAR_VAR, Op.INPLACE_VAR_CONST)
                and instrs[j].args
                and (j == i + 2 or instrs[j].orig_idx not in jump_targets)
            ):
                body_ops.append(instrs[j])
                j += 1
            if (
                body_ops
                and j < len(instrs)
                and instrs[j].op == Op.JUMP
                and instrs[j].arg == instr.orig_idx
                and instrs[j].orig_idx not in jump_targets
            ):
                args = [
                    0,
                    instr.args[0],
                    instr.args[1],
                    instr.args[2],
                    len(body_ops),
                ]
                for body_op in body_ops:
                    rhs = body_op.args[1]
                    if body_op.op == Op.INPLACE_VAR_CONST:
                        rhs = ~rhs
                    args.extend((body_op.args[0], rhs, body_op.args[2]))
                args[0] = len(args) - 1
                result.append(
                    Instr(
                        op=Op.LOOP_GENERIC,
                        arg=args[0],
                        args=tuple(args),
                        orig_idx=instr.orig_idx,
                    )
                )
                i = j + 1
                changed = True
                continue

        # LOAD_VAR a; LOAD_VAR b; CMP; JUMP_IF_FALSE target
        if (
            i + 3 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.LOAD_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op in _CMP_TO_CODE
            and instrs[i + 3].op == Op.JUMP_IF_FALSE
            and instrs[i + 3].arg is not None
            and instrs[i + 1].orig_idx not in jump_targets
            and instrs[i + 2].orig_idx not in jump_targets
            and instrs[i + 3].orig_idx not in jump_targets
        ):
            cmp_code = _CMP_TO_CODE[instrs[i + 2].op]
            rhs_slot = _arg(instrs[i + 1])
            target = _arg(instrs[i + 3])
            result.append(
                Instr(
                    op=Op.JUMP_IF_VAR_CMP,
                    arg=_arg(instr),
                    args=(_arg(instr), rhs_slot, cmp_code, target),
                    orig_idx=instr.orig_idx,
                )
            )
            i += 4
            changed = True
            continue

        # LOAD_VAR a; LOAD_CONST b; CMP; JUMP_IF_FALSE target
        if (
            i + 3 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.LOAD_CONST
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op in _CMP_TO_CODE
            and instrs[i + 3].op == Op.JUMP_IF_FALSE
            and instrs[i + 3].arg is not None
            and instrs[i + 1].orig_idx not in jump_targets
            and instrs[i + 2].orig_idx not in jump_targets
            and instrs[i + 3].orig_idx not in jump_targets
        ):
            cmp_code = _CMP_TO_CODE[instrs[i + 2].op]
            const_idx = _arg(instrs[i + 1])
            target = _arg(instrs[i + 3])
            result.append(
                Instr(
                    op=Op.JUMP_IF_VAR_CONST_CMP,
                    arg=_arg(instr),
                    args=(_arg(instr), const_idx, cmp_code, target),
                    orig_idx=instr.orig_idx,
                )
            )
            i += 4
            changed = True
            continue

        # LOAD_VAR dst; LOAD_VAR rhs; BINOP; STORE_VAR dst; POP
        if (
            i + 4 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.LOAD_VAR
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op in _INPLACE_OPS
            and instrs[i + 3].op == Op.STORE_VAR
            and instrs[i + 3].arg == instr.arg
            and instrs[i + 4].op == Op.POP
            and instrs[i + 1].orig_idx not in jump_targets
            and instrs[i + 2].orig_idx not in jump_targets
            and instrs[i + 3].orig_idx not in jump_targets
            and instrs[i + 4].orig_idx not in jump_targets
        ):
            result.append(
                Instr(
                    op=Op.INPLACE_VAR_VAR,
                    arg=_arg(instr),
                    args=(_arg(instr), _arg(instrs[i + 1]), int(instrs[i + 2].op)),
                    orig_idx=instr.orig_idx,
                )
            )
            i += 5
            changed = True
            continue

        # LOAD_VAR dst; LOAD_CONST rhs; BINOP; STORE_VAR dst; POP
        if (
            i + 4 < len(instrs)
            and instr.op == Op.LOAD_VAR
            and instr.arg is not None
            and instrs[i + 1].op == Op.LOAD_CONST
            and instrs[i + 1].arg is not None
            and instrs[i + 2].op in _INPLACE_OPS
            and instrs[i + 3].op == Op.STORE_VAR
            and instrs[i + 3].arg == instr.arg
            and instrs[i + 4].op == Op.POP
            and instrs[i + 1].orig_idx not in jump_targets
            and instrs[i + 2].orig_idx not in jump_targets
            and instrs[i + 3].orig_idx not in jump_targets
            and instrs[i + 4].orig_idx not in jump_targets
        ):
            result.append(
                Instr(
                    op=Op.INPLACE_VAR_CONST,
                    arg=_arg(instr),
                    args=(_arg(instr), _arg(instrs[i + 1]), int(instrs[i + 2].op)),
                    orig_idx=instr.orig_idx,
                )
            )
            i += 5
            changed = True
            continue

        result.append(instr)
        i += 1

    return result if changed else instrs


def _count_slot_stores(instrs: list[Instr]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for instr in instrs:
        if instr.op == Op.STORE_VAR and instr.arg is not None:
            counts[instr.arg] = counts.get(instr.arg, 0) + 1
    return counts


def _count_slot_reads(instrs: list[Instr]) -> dict[int, int]:
    counts: dict[int, int] = {}

    def add(slot: int) -> None:
        counts[slot] = counts.get(slot, 0) + 1

    for instr in instrs:
        if instr.op == Op.LOAD_VAR and instr.arg is not None:
            add(instr.arg)
        elif instr.op == Op.JUMP_IF_VAR_CMP and instr.args:
            add(instr.args[0])
            add(instr.args[1])
        elif instr.op == Op.JUMP_IF_VAR_CONST_CMP and instr.args:
            add(instr.args[0])
        elif instr.op == Op.INPLACE_VAR_VAR and instr.args:
            add(instr.args[0])
            add(instr.args[1])
        elif instr.op == Op.INPLACE_VAR_CONST and instr.args:
            add(instr.args[0])
    return counts


def _tail_calls(instrs: list[Instr], func_idx: int) -> list[Instr]:
    """Replace self calls immediately returned by the caller with frame-reusing tail calls."""
    if func_idx < 0:
        return instrs

    result: list[Instr] = []
    changed = False
    i = 0
    while i < len(instrs):
        instr = instrs[i]
        if (
            i + 1 < len(instrs)
            and instr.op == Op.CALL_GLOBAL
            and instr.arg is not None
            and (instr.arg & 0xFFFF) == func_idx
            and instrs[i + 1].op == Op.RETURN
        ):
            result.append(
                Instr(
                    op=Op.TAIL_CALL_GLOBAL,
                    arg=instr.arg,
                    orig_idx=instr.orig_idx,
                )
            )
            i += 2
            changed = True
            continue
        result.append(instr)
        i += 1
    return result if changed else instrs


# Main optimizer entry point


class Optimizer:
    """Bytecode optimizer that runs multiple passes over function bytecode."""

    def __init__(self, max_passes: int = 10) -> None:
        self.max_passes = max_passes

    def optimize(self, program: ProgramBytecode) -> ProgramBytecode:
        """Optimize all functions in the program."""
        for func_idx, fn in enumerate(program.functions):
            self._optimize_function(fn, program.constants, func_idx, program.functions)
        return program

    def _optimize_function(
        self,
        fn: Function,
        global_constants: list[object],
        func_idx: int = -1,
        functions: list[Function] | None = None,
    ) -> None:
        """Run optimization passes on a single function until fixpoint."""
        local_count = len(fn.constants)
        has_mixed_constants = local_count > 0 and bool(global_constants)
        constants_for_passes = fn.constants if local_count else global_constants

        for _pass in range(self.max_passes):
            instrs = decode(fn.code)
            if not instrs:
                break

            old_code = list(fn.code)

            if not has_mixed_constants:
                # Constant-table indexes are local-first, then program-wide at
                # the same numeric index. A merged list would change meanings
                # for functions that use both tables, so skip table-reading
                # rewrites for that legacy mixed representation.
                instrs = _constant_fold(instrs, constants_for_passes)
                instrs = _peephole(instrs, constants_for_passes)

            # Jump threading exposes dead trampoline blocks before DCE.
            instrs = _thread_jumps(instrs)

            # Dead code elimination
            instrs = _eliminate_dead_code(instrs)

            # Constant propagation
            instrs = _constant_propagation(instrs, constants_for_passes)

            # Remove IR spill/load shuttles before fusing hot-path stack sequences
            protected_slots = (
                _capture_slots_referenced_by_lambdas(instrs, functions)
                if functions is not None
                else set()
            )
            instrs = _elide_single_use_temp_slots(instrs, protected_slots)

            # Hot-path stack sequence fusion
            instrs = _superinstructions(instrs)

            # Generic self-tail-call elimination
            instrs = _tail_calls(instrs, func_idx)

            # Remap jumps after instruction removal
            instrs = _remap_jumps(instrs)

            # Encode back
            fn.code = encode(instrs)

            # If no encoded code changed, reached a fixpoint
            if fn.code == old_code:
                break

        if not local_count:
            # Compiler/codegen output normally uses only the program constant
            # table. Mutating `global_constants` avoids copying that table into
            # every function during optimization.
            fn.constants = []


def optimize(program: ProgramBytecode) -> ProgramBytecode:
    """Convenience function: optimize a program with default settings."""
    return Optimizer().optimize(program)
