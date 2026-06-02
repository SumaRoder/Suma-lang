from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from suma_lang.frontend.lexer.token_types import TokenInfo

# Expr


@dataclass(frozen=True)
class IntLiteral:
    value: int
    info: TokenInfo


@dataclass(frozen=True)
class FloatLiteral:
    value: float
    info: TokenInfo


@dataclass(frozen=True)
class StrLiteral:
    value: str
    info: TokenInfo


@dataclass(frozen=True)
class BoolLiteral:
    value: bool
    info: TokenInfo


@dataclass(frozen=True)
class NullLiteral:
    info: TokenInfo


@dataclass(frozen=True)
class Identifier:
    name: str
    info: TokenInfo


@dataclass(frozen=True)
class ThisExpr:
    info: TokenInfo


@dataclass(frozen=True)
class ItExpr:
    info: TokenInfo


@dataclass(frozen=True)
class UnaryExpr:
    op: str  # "!", "-", "~"
    operand: Expr
    info: TokenInfo


@dataclass(frozen=True)
class BinaryExpr:
    op: str
    left: Expr
    right: Expr
    info: TokenInfo


@dataclass(frozen=True)
class AssignExpr:
    target: Expr
    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class CompoundAssignExpr:
    op: str  # "+=", "-=", "*=", "/=", "%="
    target: Expr
    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class IncrementExpr:
    """Increment/decrement operator: target++ / target-- / ++target / --target."""

    target: Expr
    delta: int
    info: TokenInfo


@dataclass(frozen=True)
class CallExpr:
    callee: Expr
    args: Sequence[Expr]
    info: TokenInfo


@dataclass(frozen=True)
class MemberExpr:
    obj: Expr
    member: str
    info: TokenInfo


@dataclass(frozen=True)
class IndexExpr:
    obj: Expr
    index: Expr
    info: TokenInfo


@dataclass(frozen=True)
class SliceExpr:
    obj: Expr
    start: Expr | None
    end: Expr | None
    info: TokenInfo


@dataclass(frozen=True)
class ListExpr:
    elements: Sequence[Expr]
    info: TokenInfo


@dataclass(frozen=True)
class OkExpr:
    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class ErrExpr:
    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class LambdaExpr:
    params: Sequence[tuple[str, str | None]]
    return_type: str | None
    body: Expr | BlockStmt
    info: TokenInfo


@dataclass(frozen=True)
class ElvExpr:
    """Elvis operator: left ?: right"""

    left: Expr
    right: Expr
    info: TokenInfo


@dataclass(frozen=True)
class NullCoalesceExpr:
    """Null coalescing operator: left ?? right"""

    left: Expr
    right: Expr
    info: TokenInfo


@dataclass(frozen=True)
class PropagateExpr:
    """Result propagation operator: expr?"""

    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class SafeCallExpr:
    """Safe call: obj?.member()"""

    obj: Expr
    member: str
    args: Sequence[Expr]
    info: TokenInfo


@dataclass(frozen=True)
class SafeMemberExpr:
    """Safe member access: obj?.member"""

    obj: Expr
    member: str
    info: TokenInfo


@dataclass(frozen=True)
class PatternMatchExpr:
    """Arrow match: value -> { ... }"""

    scrutinee: Expr
    arms: Sequence[MatchArm]
    info: TokenInfo


@dataclass(frozen=True)
class IfExpr:
    condition: Expr
    then_branch: BlockStmt
    elif_branches: Sequence[tuple[Expr, BlockStmt]]
    else_branch: BlockStmt | None
    info: TokenInfo


@dataclass(frozen=True)
class RangeExpr:
    start: Expr
    end: Expr
    inclusive: bool
    info: TokenInfo


@dataclass(frozen=True)
class MatchPattern:
    kind: str  # "result", "type", "literal", or "wildcard"
    value: Expr | str | None


@dataclass(frozen=True)
class MatchArm:
    pattern: MatchPattern
    body: Expr | BlockStmt
    info: TokenInfo


Expr = (
    IntLiteral
    | FloatLiteral
    | StrLiteral
    | BoolLiteral
    | NullLiteral
    | Identifier
    | ThisExpr
    | ItExpr
    | UnaryExpr
    | BinaryExpr
    | AssignExpr
    | CompoundAssignExpr
    | IncrementExpr
    | CallExpr
    | MemberExpr
    | IndexExpr
    | SliceExpr
    | ListExpr
    | OkExpr
    | ErrExpr
    | LambdaExpr
    | ElvExpr
    | NullCoalesceExpr
    | PropagateExpr
    | SafeCallExpr
    | SafeMemberExpr
    | PatternMatchExpr
    | IfExpr
    | RangeExpr
)

# Stmt


@dataclass(frozen=True)
class ExprStmt:
    expr: Expr
    info: TokenInfo


@dataclass(frozen=True)
class VarDecl:
    name: str
    type_annotation: str | None
    initializer: Expr | None
    is_const: bool
    is_pub: bool
    info: TokenInfo


@dataclass(frozen=True)
class ReturnStmt:
    value: Expr | None
    info: TokenInfo


@dataclass(frozen=True)
class BlockStmt:
    statements: Sequence[Stmt]
    info: TokenInfo


@dataclass(frozen=True)
class IfStmt:
    condition: Expr
    then_branch: BlockStmt
    elif_branches: Sequence[tuple[Expr, BlockStmt]]
    else_branch: BlockStmt | None
    info: TokenInfo


@dataclass(frozen=True)
class LoopStmt:
    body: BlockStmt
    info: TokenInfo


@dataclass(frozen=True)
class WhileStmt:
    condition: Expr
    body: BlockStmt
    info: TokenInfo


@dataclass(frozen=True)
class ForInStmt:
    var_name: str
    iterable: Expr
    body: BlockStmt
    info: TokenInfo


@dataclass(frozen=True)
class BreakStmt:
    info: TokenInfo


@dataclass(frozen=True)
class ContinueStmt:
    info: TokenInfo


@dataclass(frozen=True)
class ThrowStmt:
    value: Expr
    info: TokenInfo


@dataclass(frozen=True)
class TryCatchStmt:
    try_body: BlockStmt
    catch_var: str | None
    catch_body: BlockStmt | None
    finally_body: BlockStmt | None
    info: TokenInfo


@dataclass(frozen=True)
class DestructureAssignStmt:
    targets: Sequence[str]
    value: Expr
    info: TokenInfo


Stmt = (
    ExprStmt
    | VarDecl
    | ReturnStmt
    | BlockStmt
    | IfStmt
    | LoopStmt
    | WhileStmt
    | ForInStmt
    | BreakStmt
    | ContinueStmt
    | ThrowStmt
    | TryCatchStmt
    | DestructureAssignStmt
)


# Top-level Decl
@dataclass(frozen=True)
class Param:
    name: str
    type_annotation: str | None
    default: Expr | None
    is_optional: bool


@dataclass(frozen=True)
class Decorator:
    expr: Expr
    info: TokenInfo


@dataclass(frozen=True)
class FunctionDecl:
    name: str
    params: Sequence[Param]
    return_type: str | None
    body: BlockStmt
    is_pub: bool
    is_static: bool
    info: TokenInfo
    type_params: Sequence[str] = field(default_factory=tuple)
    decorators: Sequence[Decorator] = field(default_factory=tuple)


@dataclass(frozen=True)
class GetterDecl:
    name: str
    return_type: str | None
    body: BlockStmt
    is_pub: bool
    info: TokenInfo


@dataclass(frozen=True)
class SetterDecl:
    name: str
    param_name: str
    param_type: str | None
    body: BlockStmt
    is_pub: bool
    info: TokenInfo


@dataclass(frozen=True)
class ClassDecl:
    name: str
    members: Sequence[FunctionDecl | VarDecl | GetterDecl | SetterDecl]
    is_pub: bool
    info: TokenInfo
    type_params: Sequence[str] = field(default_factory=tuple)
    base_type: str | None = None
    decorators: Sequence[Decorator] = field(default_factory=tuple)


@dataclass(frozen=True)
class ImportDecl:
    path: str
    info: TokenInfo


TopLevel = FunctionDecl | ClassDecl | VarDecl | ImportDecl


@dataclass
class Program:
    declarations: Sequence[TopLevel]
    py_imports: dict[str, str] = field(default_factory=dict)  # alias -> Python module name
