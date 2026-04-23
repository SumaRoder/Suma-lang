package io.github.sumaroder.rosenfeld.ast

import io.github.sumaroder.rosenfeld.tokenize.TokenInfo

interface ASTNode {
    val info: TokenInfo
}

interface Expr : ASTNode

interface Stmt : ASTNode

interface Decl : Stmt

data class IntLiteral(
    val value: Long,
    override val info: TokenInfo
) : Expr

data class FloatLiteral(
    val value: Double,
    override val info: TokenInfo
) : Expr

data class StringLiteral(
    val value: String,
    override val info: TokenInfo
) : Expr

data class BoolLiteral(
    val value: Boolean,
    override val info: TokenInfo
) : Expr

data class NullLiteral(
    override val info: TokenInfo
) : Expr

data class Identifier(
    val name: String,
    override val info: TokenInfo
) : Expr

data class ThisExpr(
    override val info: TokenInfo
) : Expr

data class ItExpr(
    override val info: TokenInfo
) : Expr

data class BinaryExpr(
    val left: Expr,
    val operator: BinaryOp,
    val right: Expr,
    override val info: TokenInfo
) : Expr

enum class BinaryOp {
    ADD, MINUS, MULT, DIV, REM,
    ANDB, ORB, XOR, SHIFTL, SHIFTR,
    GT, LT, GE, LE, EQ, NE,
    ANDL, ORL,
    ASSIGN, ASSIGN_PLUS, ASSIGN_MINUS
}

data class UnaryExpr(
    val operator: UnaryOp,
    val operand: Expr,
    override val info: TokenInfo
) : Expr

enum class UnaryOp {
    MINUS, NOTL, NOTB
}

data class CallExpr(
    val callee: Expr,
    val arguments: List<Expr>,
    override val info: TokenInfo
) : Expr

data class MemberExpr(
    val obj: Expr,
    val property: String,
    override val info: TokenInfo
) : Expr

data class IndexExpr(
    val obj: Expr,
    val index: Expr,
    override val info: TokenInfo
) : Expr

data class ConditionalExpr(
    val condition: Expr,
    val thenExpr: Expr,
    val elseExpr: Expr,
    override val info: TokenInfo
) : Expr

data class ElvisExpr(
    val left: Expr,
    val right: Expr,
    override val info: TokenInfo
) : Expr

data class SafeCallExpr(
    val obj: Expr,
    val call: Expr,
    override val info: TokenInfo
) : Expr

data class ArrowMatchExpr(
    val value: Expr,
    val branches: List<MatchBranch>,
    override val info: TokenInfo
) : Expr

data class MatchBranch(
    val pattern: String,
    val body: Expr,
    val isBlock: Boolean
)

data class ExprStmt(
    val expr: Expr,
    override val info: TokenInfo
) : Stmt

data class BlockStmt(
    val statements: List<Stmt>,
    override val info: TokenInfo
) : Stmt

data class VarDecl(
    val name: String,
    val typeAnnotation: String?,
    val initializer: Expr?,
    val isPublic: Boolean,
    val isConst: Boolean,
    override val info: TokenInfo
) : Decl

data class VarStmt(
    val name: String,
    val typeAnnotation: String?,
    val initializer: Expr,
    override val info: TokenInfo
) : Stmt

data class ReturnStmt(
    val value: Expr?,
    override val info: TokenInfo
) : Stmt

data class IfStmt(
    val condition: Expr,
    val thenBranch: Stmt,
    val elseBranch: Stmt?,
    override val info: TokenInfo
) : Stmt

data class LoopStmt(
    val body: Stmt,
    override val info: TokenInfo
) : Stmt

data class BreakStmt(
    override val info: TokenInfo
) : Stmt

data class ContinueStmt(
    override val info: TokenInfo
) : Stmt

data class ClassDecl(
    val name: String,
    val isPublic: Boolean,
    val members: List<ClassMember>,
    override val info: TokenInfo
) : Decl

interface ClassMember : ASTNode {
    val name: String
    val isPublic: Boolean
}

data class PropertyDecl(
    override val name: String,
    val typeAnnotation: String?,
    val initializer: Expr?,
    override val isPublic: Boolean,
    val isConst: Boolean,
    val getter: GetterDecl?,
    val setter: SetterDecl?,
    val propertyInfo: TokenInfo
) : ClassMember {
    override val info: TokenInfo get() = propertyInfo
}

data class GetterDecl(
    val body: Expr,
    val isExpression: Boolean,
    val info: TokenInfo
)

data class SetterDecl(
    val body: BlockStmt?,
    val info: TokenInfo
)

data class MethodDecl(
    override val name: String,
    val params: List<Parameter>,
    val returnType: String?,
    val body: Stmt?,
    override val isPublic: Boolean,
    val isInit: Boolean,
    val methodInfo: TokenInfo
) : ClassMember {
    override val info: TokenInfo get() = methodInfo
}

data class Parameter(
    val name: String,
    val typeAnnotation: String?,
    val defaultValue: Expr?,
    val isOptional: Boolean
)

data class ImportDecl(
    val path: String,
    override val info: TokenInfo
) : Decl

data class FunctionDecl(
    val name: String,
    val params: List<Parameter>,
    val returnType: String?,
    val body: Stmt,
    val isPublic: Boolean,
    override val info: TokenInfo
) : Decl

data class Program(
    val declarations: List<Decl>,
    override val info: TokenInfo
) : ASTNode

data class BlockExpr(
    val block: BlockStmt,
    override val info: TokenInfo = block.info
) : Expr
