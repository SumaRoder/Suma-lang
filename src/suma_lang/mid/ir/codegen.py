"""Code generation: IR → bytecode.

Converts the IR representation back to bytecode for the VM.
"""

from __future__ import annotations

from suma_lang.backend.codegen.compiler import Compiler
from suma_lang.backend.codegen.opcodes import Function, Op, ProgramBytecode
from suma_lang.frontend.parser.ast_nodes import FunctionDecl

from .ir import (
    Add,
    And,
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
    IsEnumVariant,
    IsErr,
    IsOk,
    Jump,
    Label,
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
    MakeEnum,
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
    Nop,
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


class CodegenError(Exception):
    pass


class CodeGenerator:
    """Generates bytecode from IR."""

    def __init__(self) -> None:
        self.program = ProgramBytecode()
        self._const_pool: dict[tuple[type, object], int] = {}
        self._string_pool: dict[str, int] = {}
        self._spill_slots: dict[VirtualReg, int] = {}  # VirtualReg -> spill slot
        self._next_spill_slot: int = 0

    def _alloc_spill_slot(self, reg: VirtualReg) -> int:
        """Allocate a spill slot for a virtual register that must be materialized."""
        if reg in self._spill_slots:
            return self._spill_slots[reg]
        slot = self._next_spill_slot
        self._next_spill_slot += 1
        self._spill_slots[reg] = slot
        return slot

    def generate(self, ir_program: IRProgram) -> ProgramBytecode:
        """Generate bytecode from an IR program."""
        self.program.classes = ir_program.classes
        self.program.enums = ir_program.enums
        self.program.py_imports = dict(ir_program.py_imports)
        self.program.overloads = dict(ir_program.overloads)

        for ir_func in ir_program.functions:
            self._gen_function(ir_func)

        if (
            ir_program.decorated_functions
            or ir_program.decorated_classes
            or ir_program.decorated_methods
        ):
            direct_compiler = Compiler()
            direct_compiler.program = self.program
            direct_compiler._class_info = self.program.classes
            direct_compiler._func_name_to_idx = {
                fn.name: i for i, fn in enumerate(self.program.functions)
            }
            for cls in ir_program.decorated_classes:
                for member in cls.members:
                    if isinstance(member, FunctionDecl) and member.name == "init":
                        direct_compiler._class_init_decls[cls.name] = member

            for func in ir_program.decorated_functions:
                func_idx = direct_compiler._func_name_to_idx.get(func.name)
                if func_idx is not None:
                    init_idx = direct_compiler._compile_decorator_init(
                        func.name, func.decorators, func_idx
                    )
                    self.program.decorators[func.name] = init_idx

            for cls in ir_program.decorated_classes:
                ctor_idx = direct_compiler._compile_class_constructor(cls)
                init_idx = direct_compiler._compile_decorator_init(
                    cls.name, cls.decorators, ctor_idx
                )
                self.program.decorators[cls.name] = init_idx

            for key, method in ir_program.decorated_methods:
                init_idx = direct_compiler._compile_decorator_init(key, method.decorators)
                self.program.method_decorators[key] = init_idx

        self.program.entry = ir_program.entry
        return self.program

    def _const(self, value: object) -> int:
        """Add a constant and return its index."""
        if len(self._const_pool) < len(self.program.constants):
            self._const_pool = {
                (type(const), const): idx for idx, const in enumerate(self.program.constants)
            }
        key = (type(value), value)
        existing = self._const_pool.get(key)
        if existing is not None:
            return existing
        idx = len(self.program.constants)
        self.program.constants.append(value)
        self._const_pool[key] = idx
        return idx

    def _string_const(self, value: str) -> int:
        """Add a string constant (dedup)."""
        if value in self._string_pool:
            return self._string_pool[value]
        idx = self._const(value)
        self._string_pool[value] = idx
        return idx

    def _load_operand(self, op: Operand, fn: Function) -> None:
        """Load an operand onto the stack."""
        if isinstance(op, Immediate):
            fn.code.append(int(Op.LOAD_CONST))
            fn.code.append(self._const(op.value))
        elif isinstance(op, VirtualReg):
            slot = self._spill_slots.get(op)
            if slot is None:
                raise CodegenError(f"Virtual register used before definition: {op}")
            fn.code.append(int(Op.LOAD_VAR))
            fn.code.append(slot)
        else:
            raise CodegenError(f"Cannot load operand onto stack: {op!r}")

    def _spill_dest(self, dest: VirtualReg, fn: Function) -> None:
        slot = self._alloc_spill_slot(dest)
        fn.code.append(int(Op.STORE_VAR))
        fn.code.append(slot)
        fn.code.append(int(Op.POP))

    def _emit_predicate(self, src: Operand, dest: VirtualReg, opcode: Op, fn: Function) -> None:
        self._load_operand(src, fn)
        fn.code.append(int(opcode))
        self._spill_dest(dest, fn)
        fn.code.append(int(Op.POP))

    def _gen_function(self, ir_func: IRFunction) -> None:
        """Generate bytecode for a single function."""
        self._spill_slots = {}
        self._next_spill_slot = ir_func.locals_count
        fn = Function(
            name=ir_func.name,
            arity=ir_func.arity,
            is_method=ir_func.is_method,
            class_name=ir_func.class_name,
            capture_count=ir_func.capture_count,
            capture_slots=list(ir_func.capture_slots),
            param_types=list(ir_func.param_types),
            type_params=list(ir_func.type_params),
        )
        self.program.functions.append(fn)

        # Build block offset map
        block_offsets: dict[Label, int] = {}
        current_offset = 0

        # Calculate offsets
        for block in ir_func.blocks:
            block_offsets[block.label] = current_offset
            for instr in block.instrs:
                current_offset += self._instr_size(instr)

        # Generate bytecode
        for block in ir_func.blocks:
            for instr in block.instrs:
                self._gen_instr(instr, fn, block_offsets)

        if len(fn.code) != current_offset:
            raise CodegenError(
                f"Generated bytecode size mismatch for {ir_func.name}: "
                f"expected {current_offset}, got {len(fn.code)}"
            )

        fn.locals_count = max(ir_func.locals_count, self._next_spill_slot)

    def _instr_size(self, instr: IRInstr) -> int:
        """Calculate the bytecode size of an IR instruction."""
        if isinstance(instr, (LoadConst, LoadVar, LoadGlobal)):
            return 2 + self._dest_spill_size()
        if isinstance(instr, (LoadThis, LoadIt)):
            return 1 + self._dest_spill_size()
        if isinstance(instr, StoreVar):
            return self._operand_size(instr.src) + 3
        if isinstance(instr, StoreGlobal):
            return self._operand_size(instr.src) + 3
        if isinstance(
            instr,
            (
                Add,
                Sub,
                Mul,
                Div,
                Mod,
                BitAnd,
                BitOr,
                BitXor,
                Shl,
                Shr,
                And,
                Or,
                Eq,
                Ne,
                Gt,
                Lt,
                Ge,
                Le,
            ),
        ):
            return (
                self._operand_size(instr.left)
                + self._operand_size(instr.right)
                + 1
                + self._dest_spill_size()
            )
        if isinstance(instr, (Neg, BitNot, Not)):
            return self._operand_size(instr.src) + 1 + self._dest_spill_size()
        if isinstance(instr, (Jump, Branch, BranchFalse)):
            return (0 if isinstance(instr, Jump) else self._operand_size(instr.cond)) + 2
        if isinstance(instr, Return):
            return 2 if instr.value is None else self._operand_size(instr.value) + 1
        if isinstance(instr, Call):
            return (
                self._operand_size(instr.callee)
                + sum(self._operand_size(a) for a in instr.args)
                + 2
                + self._dest_spill_size()
            )
        if isinstance(instr, CallGlobal):
            return sum(self._operand_size(a) for a in instr.args) + 2 + self._dest_spill_size()
        if isinstance(instr, (MakeList, MakeTuple)):
            return sum(self._operand_size(e) for e in instr.elements) + 2 + self._dest_spill_size()
        if isinstance(instr, MakeRange):
            return (
                self._operand_size(instr.start)
                + self._operand_size(instr.end)
                + 2
                + self._dest_spill_size()
            )
        if isinstance(instr, (MakeOk, MakeErr)):
            return self._operand_size(instr.value) + 1 + self._dest_spill_size()
        if isinstance(instr, MakeEnum):
            return sum(self._operand_size(arg) for arg in instr.args) + 3 + self._dest_spill_size()
        if isinstance(instr, MakeLambda):
            return 2 + self._dest_spill_size()
        if isinstance(instr, MakeObject):
            return sum(self._operand_size(a) for a in instr.args) + 3 + self._dest_spill_size()
        if isinstance(instr, LoadMember):
            return self._operand_size(instr.obj) + 2 + self._dest_spill_size()
        if isinstance(instr, StoreMember):
            return self._operand_size(instr.obj) + self._operand_size(instr.value) + 3
        if isinstance(instr, LoadIndex):
            return (
                self._operand_size(instr.obj)
                + self._operand_size(instr.index)
                + 1
                + self._dest_spill_size()
            )
        if isinstance(instr, StoreIndex):
            return (
                self._operand_size(instr.obj)
                + self._operand_size(instr.index)
                + self._operand_size(instr.value)
                + 2
            )
        if isinstance(instr, LoadSlice):
            size = self._operand_size(instr.obj) + 2 + self._dest_spill_size()
            if instr.start is not None:
                size += self._operand_size(instr.start)
            if instr.end is not None:
                size += self._operand_size(instr.end)
            return size
        if isinstance(instr, (IsOk, IsErr)):
            return self._operand_size(instr.src) + 5
        if isinstance(instr, IsEnumVariant):
            return self._operand_size(instr.src) + 6
        if isinstance(instr, UnwrapOk):
            return self._operand_size(instr.src) + 1 + self._dest_spill_size()
        if isinstance(instr, SetIt):
            return self._operand_size(instr.src) + 1
        if isinstance(instr, Pop):
            return 0
        if isinstance(instr, Print):
            return self._operand_size(instr.src) + 1
        if isinstance(instr, Nop):
            return 1
        raise CodegenError(f"Unknown IR instruction: {type(instr).__name__}")

    def _dest_spill_size(self) -> int:
        return 3

    def _operand_size(self, op: Operand) -> int:
        if isinstance(op, Immediate):
            return 2
        if isinstance(op, VirtualReg):
            return 2
        return 0

    def _gen_instr(self, instr: IRInstr, fn: Function, block_offsets: dict[Label, int]) -> None:
        """Generate bytecode for a single IR instruction."""
        if isinstance(instr, LoadConst):
            fn.code.append(int(Op.LOAD_CONST))
            fn.code.append(self._const(instr.value))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, LoadVar):
            fn.code.append(int(Op.LOAD_VAR))
            fn.code.append(instr.slot)
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, StoreVar):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.STORE_VAR))
            fn.code.append(instr.slot)
            fn.code.append(int(Op.POP))
        elif isinstance(instr, LoadGlobal):
            fn.code.append(int(Op.LOAD_GLOBAL))
            fn.code.append(self._string_const(instr.name))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, StoreGlobal):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.STORE_GLOBAL))
            fn.code.append(self._string_const(instr.name))
            fn.code.append(int(Op.POP))
        elif isinstance(
            instr,
            (
                Add,
                Sub,
                Mul,
                Div,
                Mod,
                BitAnd,
                BitOr,
                BitXor,
                Shl,
                Shr,
                And,
                Or,
                Eq,
                Ne,
                Gt,
                Lt,
                Ge,
                Le,
            ),
        ):
            self._load_operand(instr.left, fn)
            self._load_operand(instr.right, fn)
            op_map = {
                Add: Op.ADD,
                Sub: Op.SUB,
                Mul: Op.MUL,
                Div: Op.DIV,
                Mod: Op.MOD,
                BitAnd: Op.BIT_AND,
                BitOr: Op.BIT_OR,
                BitXor: Op.BIT_XOR,
                Shl: Op.SHL,
                Shr: Op.SHR,
                And: Op.AND,
                Or: Op.OR,
                Eq: Op.EQ,
                Ne: Op.NE,
                Gt: Op.GT,
                Lt: Op.LT,
                Ge: Op.GE,
                Le: Op.LE,
            }
            fn.code.append(int(op_map[type(instr)]))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, (Neg, BitNot, Not)):
            self._load_operand(instr.src, fn)
            op_map = {
                Neg: Op.NEG,
                BitNot: Op.BIT_NOT,
                Not: Op.NOT,
                And: Op.AND,
                Or: Op.OR,
            }
            fn.code.append(int(op_map[type(instr)]))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, Jump):
            fn.code.append(int(Op.JUMP))
            fn.code.append(block_offsets[instr.target])
        elif isinstance(instr, Branch):
            self._load_operand(instr.cond, fn)
            fn.code.append(int(Op.JUMP_IF_TRUE))
            fn.code.append(block_offsets[instr.target])
        elif isinstance(instr, BranchFalse):
            self._load_operand(instr.cond, fn)
            fn.code.append(int(Op.JUMP_IF_FALSE))
            fn.code.append(block_offsets[instr.target])
        elif isinstance(instr, Return):
            if instr.value is not None:
                self._load_operand(instr.value, fn)
            else:
                fn.code.append(int(Op.LOAD_NULL))
            fn.code.append(int(Op.RETURN))
        elif isinstance(instr, Call):
            self._load_operand(instr.callee, fn)
            for arg in instr.args:
                self._load_operand(arg, fn)
            fn.code.append(int(Op.CALL))
            fn.code.append(len(instr.args))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, CallGlobal):
            for arg in instr.args:
                self._load_operand(arg, fn)
            fn.code.append(int(Op.CALL_GLOBAL))
            fn.code.append((len(instr.args) << 16) | instr.func_idx)
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeList):
            for elem in instr.elements:
                self._load_operand(elem, fn)
            fn.code.append(int(Op.MAKE_LIST))
            fn.code.append(len(instr.elements))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeTuple):
            for elem in instr.elements:
                self._load_operand(elem, fn)
            fn.code.append(int(Op.MAKE_TUPLE))
            fn.code.append(len(instr.elements))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeRange):
            self._load_operand(instr.start, fn)
            self._load_operand(instr.end, fn)
            fn.code.append(int(Op.MAKE_RANGE))
            fn.code.append(1 if instr.inclusive else 0)
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeOk):
            self._load_operand(instr.value, fn)
            fn.code.append(int(Op.MAKE_OK))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeErr):
            self._load_operand(instr.value, fn)
            fn.code.append(int(Op.MAKE_ERR))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeEnum):
            for arg in instr.args:
                self._load_operand(arg, fn)
            fn.code.append(int(Op.MAKE_ENUM))
            fn.code.append(self._string_const(instr.tag))
            fn.code.append(len(instr.args))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeLambda):
            fn.code.append(int(Op.MAKE_LAMBDA))
            fn.code.append(instr.func_idx)
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, MakeObject):
            for arg in instr.args:
                self._load_operand(arg, fn)
            fn.code.append(int(Op.MAKE_OBJECT))
            fn.code.append(self._string_const(instr.class_name))
            fn.code.append(len(instr.args))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, LoadMember):
            self._load_operand(instr.obj, fn)
            fn.code.append(int(Op.MEMBER))
            fn.code.append(self._string_const(instr.member))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, StoreMember):
            self._load_operand(instr.obj, fn)
            self._load_operand(instr.value, fn)
            fn.code.append(int(Op.SET_MEMBER))
            fn.code.append(self._string_const(instr.member))
            fn.code.append(int(Op.POP))
        elif isinstance(instr, StoreIndex):
            self._load_operand(instr.obj, fn)
            self._load_operand(instr.index, fn)
            self._load_operand(instr.value, fn)
            fn.code.append(int(Op.SET_INDEX))
            fn.code.append(int(Op.POP))
        elif isinstance(instr, LoadIndex):
            self._load_operand(instr.obj, fn)
            self._load_operand(instr.index, fn)
            fn.code.append(int(Op.INDEX))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, LoadSlice):
            self._load_operand(instr.obj, fn)
            if instr.start is not None:
                self._load_operand(instr.start, fn)
            if instr.end is not None:
                self._load_operand(instr.end, fn)
            mask = 0
            if instr.start is not None:
                mask |= 1
            if instr.end is not None:
                mask |= 2
            fn.code.append(int(Op.SLICE))
            fn.code.append(mask)
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, IsOk):
            self._emit_predicate(instr.src, instr.dest, Op.IS_OK, fn)
        elif isinstance(instr, IsErr):
            self._emit_predicate(instr.src, instr.dest, Op.IS_ERR, fn)
        elif isinstance(instr, IsEnumVariant):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.IS_ENUM_VARIANT))
            fn.code.append(self._string_const(instr.tag))
            self._spill_dest(instr.dest, fn)
            fn.code.append(int(Op.POP))
        elif isinstance(instr, UnwrapOk):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.UNWRAP_OK))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, LoadThis):
            fn.code.append(int(Op.LOAD_THIS))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, LoadIt):
            fn.code.append(int(Op.LOAD_IT))
            self._spill_dest(instr.dest, fn)
        elif isinstance(instr, SetIt):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.SET_IT))
        elif isinstance(instr, Pop):
            pass
        elif isinstance(instr, Print):
            self._load_operand(instr.src, fn)
            fn.code.append(int(Op.PRINT))
        elif isinstance(instr, Nop):
            fn.code.append(int(Op.NOP))
        else:
            raise CodegenError(f"Unknown IR instruction: {type(instr)}")


def ir_to_bytecode(ir_program: IRProgram) -> ProgramBytecode:
    """Convert an IR program to bytecode."""
    return CodeGenerator().generate(ir_program)
