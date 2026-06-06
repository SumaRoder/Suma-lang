"""Suma-lang IR data structures.

The IR uses a three-address code format with explicit control flow:
- Basic blocks connected by edges
- SSA-like naming for values (virtual registers)
- Explicit labels for jump targets
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suma_lang.frontend.parser.ast_nodes import ClassDecl, FunctionDecl


class IRType(Enum):
    """IR value types."""

    INT = auto()
    FLOAT = auto()
    BOOL = auto()
    STR = auto()
    NULL = auto()
    LIST = auto()
    TUPLE = auto()
    OBJECT = auto()
    LAMBDA = auto()
    OK = auto()
    ERR = auto()
    ANY = auto()  # unknown/polymorphic type


@dataclass(frozen=True)
class VirtualReg:
    """A virtual register (SSA value)."""

    name: str
    version: int = 0
    ir_type: IRType = IRType.ANY

    def __repr__(self) -> str:
        return f"%{self.name}.{self.version}" if self.version else f"%{self.name}"


@dataclass(frozen=True)
class Immediate:
    """An immediate constant value."""

    value: object

    def __repr__(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class Label:
    """A basic block label."""

    name: str

    def __repr__(self) -> str:
        return f"@{self.name}"


Operand = VirtualReg | Immediate | Label


@dataclass
class IRInstr:
    """Base class for IR instructions."""

    pass


# --- Load/Store ---


@dataclass
class LoadConst(IRInstr):
    """Load a constant value into a virtual register."""

    dest: VirtualReg
    value: object


@dataclass
class LoadVar(IRInstr):
    """Load a local variable into a virtual register."""

    dest: VirtualReg
    slot: int
    name: str = ""


@dataclass
class StoreVar(IRInstr):
    """Store a virtual register into a local variable."""

    src: Operand
    slot: int
    name: str = ""


@dataclass
class LoadGlobal(IRInstr):
    """Load a global variable by name."""

    dest: VirtualReg
    name: str


@dataclass
class StoreGlobal(IRInstr):
    """Store a value into a global variable."""

    src: Operand
    name: str


# --- Arithmetic ---


@dataclass
class Add(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Sub(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Mul(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Div(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Mod(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Neg(IRInstr):
    dest: VirtualReg
    src: Operand


# --- Bitwise ---


@dataclass
class BitAnd(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class BitOr(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class BitXor(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class BitNot(IRInstr):
    dest: VirtualReg
    src: Operand


@dataclass
class Shl(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Shr(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


# --- Logic ---


@dataclass
class Not(IRInstr):
    dest: VirtualReg
    src: Operand


@dataclass
class And(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Or(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


# --- Comparison ---


@dataclass
class Eq(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Ne(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Gt(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Lt(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Ge(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


@dataclass
class Le(IRInstr):
    dest: VirtualReg
    left: Operand
    right: Operand


# --- Control Flow ---


@dataclass
class Jump(IRInstr):
    """Unconditional jump to a label."""

    target: Label


@dataclass
class Branch(IRInstr):
    """Conditional branch: if cond is true, jump to target."""

    cond: Operand
    target: Label


@dataclass
class BranchFalse(IRInstr):
    """Conditional branch: if cond is false, jump to target."""

    cond: Operand
    target: Label


@dataclass
class Return(IRInstr):
    """Return a value from the current function."""

    value: Operand | None = None


# --- Function Calls ---


@dataclass
class Call(IRInstr):
    """Call a function by name or register."""

    dest: VirtualReg
    callee: Operand
    args: list[Operand]


@dataclass
class CallGlobal(IRInstr):
    """Call a known global function by index (fast path)."""

    dest: VirtualReg
    func_idx: int
    args: list[Operand]


# --- Data Structures ---


@dataclass
class MakeList(IRInstr):
    """Create a list from elements."""

    dest: VirtualReg
    elements: list[Operand]


@dataclass
class MakeTuple(IRInstr):
    """Create a tuple from elements."""

    dest: VirtualReg
    elements: list[Operand]


@dataclass
class MakeRange(IRInstr):
    """Create a range from start/end bounds."""

    dest: VirtualReg
    start: Operand
    end: Operand
    inclusive: bool


@dataclass
class MakeOk(IRInstr):
    """Wrap a value in Ok."""

    dest: VirtualReg
    value: Operand


@dataclass
class MakeErr(IRInstr):
    """Wrap a value in Err."""

    dest: VirtualReg
    value: Operand


@dataclass
class MakeEnum(IRInstr):
    """Create an enum variant value."""

    dest: VirtualReg
    tag: str
    args: list[Operand]


@dataclass
class MakeLambda(IRInstr):
    """Create a lambda with captured variables."""

    dest: VirtualReg
    func_idx: int
    captures: list[Operand]


@dataclass
class MakeObject(IRInstr):
    """Create an object instance."""

    dest: VirtualReg
    class_name: str
    args: list[Operand]


# --- Member Access ---


@dataclass
class LoadMember(IRInstr):
    """Load a member from an object."""

    dest: VirtualReg
    obj: Operand
    member: str


@dataclass
class StoreMember(IRInstr):
    """Store a value into an object member."""

    obj: Operand
    member: str
    value: Operand


@dataclass
class LoadIndex(IRInstr):
    """Load a value by index."""

    dest: VirtualReg
    obj: Operand
    index: Operand


@dataclass
class StoreIndex(IRInstr):
    """Store a value by index."""

    obj: Operand
    index: Operand
    value: Operand


@dataclass
class LoadSlice(IRInstr):
    """Load a slice of a list/string."""

    dest: VirtualReg
    obj: Operand
    start: Operand | None
    end: Operand | None


# --- Pattern Matching ---


@dataclass
class IsOk(IRInstr):
    """Check if a value is Ok."""

    dest: VirtualReg
    src: Operand


@dataclass
class IsErr(IRInstr):
    """Check if a value is Err."""

    dest: VirtualReg
    src: Operand


@dataclass
class IsEnumVariant(IRInstr):
    """Check whether a value is a specific enum variant."""

    dest: VirtualReg
    src: Operand
    tag: str


@dataclass
class UnwrapOk(IRInstr):
    """Unwrap an Ok value."""

    dest: VirtualReg
    src: Operand


# --- Special ---


@dataclass
class SetIt(IRInstr):
    """Set the 'it' variable for pattern matching."""

    src: Operand


@dataclass
class LoadIt(IRInstr):
    """Load the 'it' variable."""

    dest: VirtualReg


@dataclass
class LoadThis(IRInstr):
    """Load the 'this' reference."""

    dest: VirtualReg


@dataclass
class Pop(IRInstr):
    """Discard a value (for side-effect-only expressions)."""

    src: Operand


@dataclass
class Nop(IRInstr):
    """No operation."""

    pass


@dataclass
class Print(IRInstr):
    """Print a value."""

    src: Operand


# ============================================================================
# Basic Block
# ============================================================================


@dataclass
class BasicBlock:
    """A basic block: a sequence of instructions with single entry/exit."""

    label: Label
    instrs: list[IRInstr] = field(default_factory=list)
    # Predecessors and successors (filled by CFG construction)
    preds: list[BasicBlock] = field(default_factory=list)
    succs: list[BasicBlock] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"Block({self.label.name}, {len(self.instrs)} instrs)"


# ============================================================================
# IR Function
# ============================================================================


@dataclass
class IRFunction:
    """A function in IR form."""

    name: str
    params: list[str]  # parameter names
    arity: int
    is_method: bool = False
    class_name: str | None = None
    entry: BasicBlock | None = None
    blocks: list[BasicBlock] = field(default_factory=list)
    # Local variable slots (for codegen)
    locals_count: int = 0
    capture_count: int = 0
    capture_slots: list[int] = field(default_factory=list)
    param_types: list[str | None] = field(default_factory=list)
    type_params: list[str] = field(default_factory=list)


# ============================================================================
# IR Program
# ============================================================================


@dataclass
class IRProgram:
    """A complete program in IR form."""

    functions: list[IRFunction] = field(default_factory=list)
    entry: int = 0  # index of entry function
    classes: dict[str, dict] = field(default_factory=dict)
    enums: dict[str, dict] = field(default_factory=dict)
    constants: list[object] = field(default_factory=list)
    py_imports: dict[str, str] = field(default_factory=dict)
    decorated_functions: list[FunctionDecl] = field(default_factory=list)
    decorated_classes: list[ClassDecl] = field(default_factory=list)
    decorated_methods: list[tuple[str, FunctionDecl]] = field(default_factory=list)
    overloads: dict[str, list[int]] = field(default_factory=dict)
