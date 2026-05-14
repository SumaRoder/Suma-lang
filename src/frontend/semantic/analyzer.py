from __future__ import annotations

from typing import Optional

from src.frontend.lexer.token_types import TokenInfo
from src.frontend.parser.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BlockStmt,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    ClassDecl,
    CompoundAssignExpr,
    ContinueStmt,
    ElvExpr,
    ErrExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    FunctionDecl,
    GetterDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MemberExpr,
    NullLiteral,
    OkExpr,
    Param,
    PatternMatchExpr,
    Program,
    ReturnStmt,
    SafeCallExpr,
    SetterDecl,
    SliceExpr,
    Stmt,
    StrLiteral,
    ThisExpr,
    ThrowStmt,
    TopLevel,
    TryCatchStmt,
    UnaryExpr,
    VarDecl,
)
from src.frontend.semantic.symbol_table import Scope, Symbol


class AnalysisError(Exception):
    pass


class Analyzer:
    """Semantic analyzer: scope resolution, basic type checks, arity checks."""

    BUILTINS = {
        "print": ("func", None, 1),
        "to_str": ("func", "Str", 1),
        "to_int": ("func", "Int", 1),
        "to_float": ("func", "Float", 1),
        "to_bool": ("func", "Bool", 1),
        "List": ("func", "List", -1),  # variadic, type constructor
        "Ok": ("func", "R", 1),  # type constructor
        "Err": ("func", "R", 1),  # type constructor
        "parse_int": ("func", "R", 1),
        "is_ok": ("func", "Bool", 1),
        "is_err": ("func", "Bool", 1),
        "unwrap": ("func", None, 1),
        "unwrap_or": ("func", None, 2),
        "panic": ("func", None, 1),
        "assert": ("func", None, -1),
        "len": ("func", "Int", 1),
        "type_of": ("func", "Str", 1),
        "__suma_is_type": ("func", "Bool", 2),
    }

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.global_scope = Scope(parent=None, scope_type="global")
        self.current_scope: Scope = self.global_scope
        self.current_class: Optional[str] = None
        self.current_function: Optional[FunctionDecl] = None
        self._slot_counter = 0
        self._class_decls: dict[str, ClassDecl] = {}
        self._class_fields: dict[str, dict[str, VarDecl]] = {}
        self._class_field_types: dict[str, dict[str, Optional[str]]] = {}
        self._class_methods: dict[str, dict[str, FunctionDecl]] = {}
        self._loop_depth = 0

    def _next_slot(self) -> int:
        s = self._slot_counter
        self._slot_counter += 1
        return s

    def _error(self, msg: str, info: Optional[TokenInfo] = None) -> None:
        loc = ""
        if info:
            loc = f"{info.file or '<unknown>'}:{info.line}:{info.column}: "
        self.errors.append(f"{loc}{msg}")

    def _push_scope(self, scope_type: str = "block", class_name: str | None = None) -> Scope:
        self.current_scope = Scope(
            parent=self.current_scope, scope_type=scope_type, class_name=class_name
        )
        return self.current_scope

    def _pop_scope(self) -> None:
        if self.current_scope.parent is not None:
            self.current_scope = self.current_scope.parent

    # public API
    def analyze(self, program: Program) -> list[str]:
        for alias, module_name in program.py_imports.items():
            err = self.global_scope.define(
                Symbol(
                    name=alias,
                    type_name="PyModule",
                    kind="py_module",
                    decl=module_name,
                    is_pub=True,
                    index=self._next_slot(),
                )
            )
            if err:
                self._error(err)

        for decl in program.declarations:
            self._register_toplevel(decl)

        for decl in program.declarations:
            self._analyze_toplevel(decl)

        return self.errors

    def _register_toplevel(self, decl: TopLevel) -> None:
        if isinstance(decl, FunctionDecl):
            sym = Symbol(
                name=decl.name,
                type_name=decl.return_type,
                kind="func",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        elif isinstance(decl, ClassDecl):
            self._class_decls[decl.name] = decl
            self._class_fields[decl.name] = {
                member.name: member for member in decl.members if isinstance(member, VarDecl)
            }
            self._class_field_types[decl.name] = {
                member.name: member.type_annotation
                for member in decl.members
                if isinstance(member, VarDecl)
            }
            methods = {
                member.name: member for member in decl.members if isinstance(member, FunctionDecl)
            }
            for member in decl.members:
                if isinstance(member, GetterDecl):
                    methods[f"get_{member.name}"] = FunctionDecl(
                        name=f"get_{member.name}",
                        params=[],
                        return_type=member.return_type,
                        body=member.body,
                        is_pub=True,
                        is_static=False,
                        info=member.info,
                    )
                elif isinstance(member, SetterDecl):
                    methods[f"set_{member.name}"] = FunctionDecl(
                        name=f"set_{member.name}",
                        params=[
                            Param(
                                name=member.param_name,
                                type_annotation=None,
                                default=None,
                                is_optional=False,
                            )
                        ],
                        return_type=None,
                        body=member.body,
                        is_pub=True,
                        is_static=False,
                        info=member.info,
                    )
            self._class_methods[decl.name] = methods
            sym = Symbol(
                name=decl.name,
                type_name=decl.name,
                kind="class",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        elif isinstance(decl, VarDecl):
            sym = Symbol(
                name=decl.name,
                type_name=decl.type_annotation,
                kind="var",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        # ImportDecl: skip for now, future will complete

    def _analyze_toplevel(self, decl: TopLevel) -> None:
        if isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, VarDecl):
            if decl.initializer:
                init_type = self._infer_expr(decl.initializer)
                type_name = self._resolve_decl_type(decl.type_annotation, init_type)
                self._check_assignable(
                    type_name, init_type, decl.info, f"Cannot assign {init_type} to '{decl.name}'"
                )
                sym = self.global_scope.resolve_local(decl.name)
                if sym:
                    sym.type_name = type_name

    def _analyze_class(self, cls: ClassDecl) -> None:
        prev_class = self.current_class
        self.current_class = cls.name
        scope = self._push_scope("class", cls.name)

        for member in cls.members:
            if isinstance(member, VarDecl):
                sym = Symbol(
                    name=member.name,
                    type_name=member.type_annotation,
                    kind="var",
                    decl=member,
                    is_pub=member.is_pub,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)
            elif isinstance(member, FunctionDecl):
                sym = Symbol(
                    name=member.name,
                    type_name=member.return_type,
                    kind="func",
                    decl=member,
                    is_pub=member.is_pub,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)
            elif isinstance(member, GetterDecl):
                sym = Symbol(
                    name=member.name,
                    type_name=member.return_type,
                    kind="var",
                    decl=member,
                    is_pub=True,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)

        for member in cls.members:
            if isinstance(member, FunctionDecl):
                self._analyze_function(member, is_method=True)
            elif isinstance(member, GetterDecl):
                func = self._class_methods[cls.name][f"get_{member.name}"]
                self._analyze_function(func, is_method=True)
            elif isinstance(member, SetterDecl):
                func = self._class_methods[cls.name][f"set_{member.name}"]
                self._analyze_function(func, is_method=True)
            elif isinstance(member, VarDecl) and member.initializer:
                init_type = self._infer_expr(member.initializer)
                type_name = self._resolve_decl_type(member.type_annotation, init_type)
                self._class_field_types[cls.name][member.name] = type_name
                field_sym = scope.resolve_local(member.name)
                if field_sym:
                    field_sym.type_name = type_name
                self._check_assignable(
                    type_name,
                    init_type,
                    member.info,
                    f"Cannot assign {init_type} to field '{member.name}'",
                )

        self._pop_scope()
        self.current_class = prev_class

    def _analyze_function(self, func: FunctionDecl, is_method: bool = False) -> None:
        prev_func = self.current_function
        self.current_function = func
        scope = self._push_scope("function")

        # 'this'
        if is_method:
            sym = Symbol(name="this", type_name=self.current_class, kind="param")
            scope.define(sym)

        for param in func.params:
            sym = Symbol(name=param.name, type_name=param.type_annotation, kind="param")
            err = scope.define(sym)
            if err:
                self._error(err, func.info)
            if param.default:
                default_type = self._infer_expr(param.default)
                self._check_assignable(
                    param.type_annotation,
                    default_type,
                    func.info,
                    f"Default value for parameter '{param.name}' has type {default_type}",
                )

        self._analyze_block(func.body)

        self._pop_scope()
        self.current_function = prev_func

    def _analyze_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, ExprStmt):
            self._infer_expr(stmt.expr)
        elif isinstance(stmt, VarDecl):
            init_type = None
            if stmt.initializer:
                init_type = self._infer_expr(stmt.initializer)
                type_name = self._resolve_decl_type(stmt.type_annotation, init_type)
                self._check_assignable(
                    type_name, init_type, stmt.info, f"Cannot assign {init_type} to '{stmt.name}'"
                )
            else:
                type_name = stmt.type_annotation
            sym = Symbol(
                name=stmt.name,
                type_name=stmt.type_annotation,
                kind="var",
                decl=stmt,
                is_pub=stmt.is_pub,
            )
            sym.type_name = type_name
            err = self.current_scope.define(sym)
            if err:
                self._error(err, stmt.info)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                value_type = self._infer_expr(stmt.value)
            else:
                value_type = "Null"
            if self.current_function:
                if self.current_function.return_type != "Any":
                    self._check_assignable(
                        self.current_function.return_type,
                        value_type,
                        stmt.info,
                        f"Function '{self.current_function.name}' returns {value_type}",
                    )
        elif isinstance(stmt, BlockStmt):
            self._push_scope()
            for s in stmt.statements:
                self._analyze_stmt(s)
            self._pop_scope()
        elif isinstance(stmt, IfStmt):
            cond_type = self._infer_expr(stmt.condition)
            self._expect_type(cond_type, "Bool", stmt.condition.info, "if condition must be Bool")
            self._analyze_block(stmt.then_branch)
            for elif_cond, elif_body in stmt.elif_branches:
                elif_type = self._infer_expr(elif_cond)
                self._expect_type(elif_type, "Bool", elif_cond.info, "elif condition must be Bool")
                self._analyze_block(elif_body)
            if stmt.else_branch:
                self._analyze_block(stmt.else_branch)
        elif isinstance(stmt, LoopStmt):
            self._loop_depth += 1
            self._analyze_block(stmt.body)
            self._loop_depth -= 1
        elif isinstance(stmt, BreakStmt):
            if self._loop_depth == 0:
                self._error("'break' outside of loop", stmt.info)
        elif isinstance(stmt, ContinueStmt):
            if self._loop_depth == 0:
                self._error("'continue' outside of loop", stmt.info)
        elif isinstance(stmt, ThrowStmt):
            self._infer_expr(stmt.value)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_block(stmt.try_body)
            if stmt.catch_body:
                self._push_scope()
                if stmt.catch_var:
                    sym = Symbol(name=stmt.catch_var, type_name=None, kind="var")
                    self.current_scope.define(sym)
                self._analyze_block(stmt.catch_body)
                self._pop_scope()
            if stmt.finally_body:
                self._analyze_block(stmt.finally_body)

    def _analyze_block(self, block: BlockStmt) -> None:
        self._push_scope()
        for stmt in block.statements:
            self._analyze_stmt(stmt)
        self._pop_scope()

    def _analyze_expr(self, expr: Expr) -> None:
        self._infer_expr(expr)

    def _infer_expr(self, expr: Expr) -> Optional[str]:
        if isinstance(expr, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            return self._literal_type(expr)
        elif isinstance(expr, Identifier):
            sym = self.current_scope.resolve(expr.name)
            if not sym:
                # builtins
                if expr.name not in self.BUILTINS:
                    self._error(f"Undefined name '{expr.name}'", expr.info)
                return self.BUILTINS.get(expr.name, (None, None, None))[1]
            return sym.type_name
        if isinstance(expr, ThisExpr):
            if not self.current_class:
                self._error("'this' used outside of a class", expr.info)
            return self.current_class
        if isinstance(expr, ItExpr):
            # 'it' is context-dependent (match arms), hard to check statically
            sym = self.current_scope.resolve("it")
            return sym.type_name if sym else None
        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expr(expr.operand)
            if expr.op == "!":
                self._expect_type(operand_type, "Bool", expr.info, "'!' operand must be Bool")
                return "Bool"
            if expr.op in ("-", "~"):
                self._expect_numeric(
                    operand_type, expr.info, f"'{expr.op}' operand must be numeric"
                )
                return operand_type
        if isinstance(expr, BinaryExpr):
            return self._infer_binary(expr)
        if isinstance(expr, AssignExpr):
            value_type = self._infer_expr(expr.value)
            if isinstance(expr.target, Identifier):
                sym = self.current_scope.resolve(expr.target.name)
                if not sym:
                    sym = Symbol(name=expr.target.name, type_name=value_type, kind="var")
                    err = self.current_scope.define(sym)
                    if err:
                        self._error(err, expr.target.info)
                    return value_type
                if sym.type_name == "Any":
                    sym.type_name = value_type
            target_type = self._infer_assignment_target(expr.target)
            self._check_assignable(
                target_type, value_type, expr.info, f"Cannot assign {value_type} to {target_type}"
            )
            return value_type
        if isinstance(expr, CompoundAssignExpr):
            target_type = self._infer_assignment_target(expr.target)
            value_type = self._infer_expr(expr.value)
            self._check_binary_operands(expr.op.rstrip("="), target_type, value_type, expr.info)
            return target_type
        if isinstance(expr, CallExpr):
            return self._infer_call(expr)
        if isinstance(expr, MemberExpr):
            obj_type = self._infer_expr(expr.obj)
            return self._member_type(obj_type, expr.member, expr.info)
        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expr(expr.obj)
            index_type = self._infer_expr(expr.index)
            self._expect_type(index_type, "Int", expr.index.info, "index must be Int")
            if obj_type == "Str":
                return "Str"
            if obj_type == "List":
                return None
            if obj_type is not None:
                self._error(f"Cannot index {obj_type}", expr.info)
            return None
        if isinstance(expr, SliceExpr):
            obj_type = self._infer_expr(expr.obj)
            if expr.start:
                start_type = self._infer_expr(expr.start)
                self._expect_type(start_type, "Int", expr.start.info, "slice start must be Int")
            if expr.end:
                end_type = self._infer_expr(expr.end)
                self._expect_type(end_type, "Int", expr.end.info, "slice end must be Int")
            if obj_type in ("List", "Str"):
                return obj_type
            if obj_type is not None:
                self._error(f"Cannot slice {obj_type}", expr.info)
            return None
        if isinstance(expr, ListExpr):
            for elem in expr.elements:
                self._infer_expr(elem)
            return "List"
        if isinstance(expr, OkExpr):
            self._infer_expr(expr.value)
            return "R"
        if isinstance(expr, ErrExpr):
            self._infer_expr(expr.value)
            return "R"
        if isinstance(expr, LambdaExpr):
            scope = self._push_scope("function")
            for pname, ptype in expr.params:
                sym = Symbol(name=pname, type_name=ptype, kind="param")
                scope.define(sym)
            if isinstance(expr.body, BlockStmt):
                self._analyze_block(expr.body)
                result_type = expr.return_type
            else:
                result_type = self._infer_expr(expr.body)
            self._pop_scope()
            self._check_assignable(
                expr.return_type, result_type, expr.info, f"Lambda returns {result_type}"
            )
            return "Function"
        if isinstance(expr, ElvExpr):
            left_type = self._infer_expr(expr.left)
            right_type = self._infer_expr(expr.right)
            return self._common_type(left_type, right_type)
        if isinstance(expr, SafeCallExpr):
            obj_type = self._infer_expr(expr.obj)
            method = self._class_methods.get(obj_type or "", {}).get(expr.member)
            if method:
                self._check_function_call(
                    method,
                    CallExpr(
                        callee=MemberExpr(obj=expr.obj, member=expr.member, info=expr.info),
                        args=expr.args,
                        info=expr.info,
                    ),
                )
                return method.return_type
            for arg in expr.args:
                self._infer_expr(arg)
            if obj_type in (None, "R", "PyObject", "PyCallable"):
                return None
            member_type = self._member_type(obj_type, expr.member, expr.info)
            return (
                member_type if member_type not in ("Function", "PyObject", "PyCallable") else None
            )
        if isinstance(expr, PatternMatchExpr):
            self._infer_expr(expr.scrutinee)
            result_type = None
            for arm in expr.arms:
                if arm.pattern.kind == "literal" and not isinstance(arm.pattern.value, Identifier):
                    self._infer_expr(arm.pattern.value)  # type: ignore[arg-type]
                if isinstance(arm.body, BlockStmt):
                    self._push_scope()
                    # 'it' is implicitly available in match arms
                    sym = Symbol(name="it", type_name=None, kind="var")
                    self.current_scope.define(sym)
                    self._analyze_block(arm.body)
                    self._pop_scope()
                else:
                    arm_type = self._infer_expr(arm.body)
                    result_type = self._common_type(result_type, arm_type)
            return result_type
        return None

    def _literal_type(self, expr: Expr) -> str:
        if isinstance(expr, IntLiteral):
            return "Int"
        if isinstance(expr, FloatLiteral):
            return "Float"
        if isinstance(expr, StrLiteral):
            return "Str"
        if isinstance(expr, BoolLiteral):
            return "Bool"
        return "Null"

    def _resolve_decl_type(self, declared: Optional[str], inferred: Optional[str]) -> Optional[str]:
        if declared == "Any" and inferred is not None:
            return inferred
        return declared or inferred

    def _infer_assignment_target(self, target: Expr) -> Optional[str]:
        if isinstance(target, Identifier):
            sym = self.current_scope.resolve(target.name)
            if not sym:
                self._error(f"Undefined name '{target.name}'", target.info)
                return None
            return sym.type_name
        if isinstance(target, MemberExpr):
            obj_type = self._infer_expr(target.obj)
            return self._member_type(obj_type, target.member, target.info)
        if isinstance(target, IndexExpr):
            self._infer_expr(target.obj)
            index_type = self._infer_expr(target.index)
            self._expect_type(index_type, "Int", target.index.info, "index must be Int")
            return None
        self._error("Invalid assignment target", target.info)
        return None

    def _infer_binary(self, expr: BinaryExpr) -> Optional[str]:
        left_type = self._infer_expr(expr.left)
        if expr.op == "is":
            if not isinstance(expr.right, Identifier):
                self._error("right operand of 'is' must be a type name", expr.right.info)
            return "Bool"
        right_type = self._infer_expr(expr.right)
        if expr.op in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"):
            self._check_binary_operands(expr.op, left_type, right_type, expr.info)
            if expr.op == "+" and (left_type == "Str" or right_type == "Str"):
                return "Str"
            if left_type == "Float" or right_type == "Float":
                return "Float"
            return left_type or right_type
        if expr.op in ("==", "!="):
            return "Bool"
        if expr.op in (">", "<", ">=", "<="):
            self._expect_numeric(left_type, expr.info, f"'{expr.op}' left operand must be numeric")
            self._expect_numeric(
                right_type, expr.info, f"'{expr.op}' right operand must be numeric"
            )
            return "Bool"
        if expr.op in ("&&", "||"):
            self._expect_type(
                left_type, "Bool", expr.info, f"'{expr.op}' left operand must be Bool"
            )
            self._expect_type(
                right_type, "Bool", expr.info, f"'{expr.op}' right operand must be Bool"
            )
            return "Bool"
        return None

    def _infer_call(self, expr: CallExpr) -> Optional[str]:
        if isinstance(expr.callee, MemberExpr):
            obj_type = self._infer_expr(expr.callee.obj)
            method = self._class_methods.get(obj_type or "", {}).get(expr.callee.member)
            if method:
                self._check_function_call(method, expr)
                return method.return_type
            member_type = self._member_type(obj_type, expr.callee.member, expr.callee.info)
            for arg in expr.args:
                self._infer_expr(arg)
            if member_type not in (None, "Function", "PyObject", "PyCallable"):
                self._error(
                    f"Cannot call member '{expr.callee.member}' of type {member_type}", expr.info
                )
            return None
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            if name in self.BUILTINS:
                _, return_type, arity = self.BUILTINS[name]
                self._check_arity(name, len(expr.args), arity, expr.info)
                for arg in expr.args:
                    self._infer_expr(arg)
                return return_type
            sym = self.current_scope.resolve(name)
            if not sym:
                self._error(f"Undefined name '{name}'", expr.info)
                for arg in expr.args:
                    self._infer_expr(arg)
                return None
            if sym.kind == "py_module":
                for arg in expr.args:
                    self._infer_expr(arg)
                return "PyObject"
            if sym.kind == "class":
                self._check_constructor_call(name, expr)
                return name
            if sym.kind == "func" and isinstance(sym.decl, FunctionDecl):
                self._check_function_call(sym.decl, expr)
                return sym.decl.return_type
        callee_type = self._infer_expr(expr.callee)
        for arg in expr.args:
            self._infer_expr(arg)
        if callee_type not in (None, "Function", "PyObject", "PyCallable"):
            self._error(f"Cannot call value of type {callee_type}", expr.info)
        return None

    def _check_function_call(self, func: FunctionDecl, expr: CallExpr) -> None:
        required = sum(
            1 for param in func.params if not param.is_optional and param.default is None
        )
        if len(expr.args) < required or len(expr.args) > len(func.params):
            self._error(
                f"Function '{func.name}' expects {required}-{len(func.params)} args, got {len(expr.args)}",
                expr.info,
            )
        for arg, param in zip(expr.args, func.params):
            arg_type = self._infer_expr(arg)
            if param.type_annotation != "Any":
                self._check_assignable(
                    param.type_annotation,
                    arg_type,
                    arg.info,
                    f"Argument '{param.name}' expects {param.type_annotation}, got {arg_type}",
                )

    def _check_constructor_call(self, class_name: str, expr: CallExpr) -> None:
        init = self._class_methods.get(class_name, {}).get("init")
        if init:
            self._check_function_call(init, expr)
            return
        if expr.args:
            self._error(
                f"Class '{class_name}' constructor expects 0 args, got {len(expr.args)}", expr.info
            )
        for arg in expr.args:
            self._infer_expr(arg)

    def _check_arity(self, name: str, got: int, arity: int, info: TokenInfo) -> None:
        if arity >= 0 and got != arity:
            self._error(f"Function '{name}' expects {arity} args, got {got}", info)

    def _member_type(self, obj_type: Optional[str], member: str, info: TokenInfo) -> Optional[str]:
        if obj_type is None:
            return None
        if obj_type in ("PyModule", "PyObject", "PyCallable"):
            return "PyObject"
        if obj_type == "Str":
            if member == "size":
                return "Int"
            self._error(f"No member '{member}' on Str", info)
            return None
        if obj_type == "List":
            if member == "size":
                return "Int"
            if member == "add":
                return "Function"
            self._error(f"No member '{member}' on List", info)
            return None
        if obj_type == "R":
            if member == "value":
                return None
            return None
        field_type = self._class_field_types.get(obj_type, {}).get(member)
        if field_type is not None:
            return field_type
        methods = self._class_methods.get(obj_type, {})
        getter = methods.get(f"get_{member}")
        if getter:
            return getter.return_type
        method = methods.get(member)
        if method:
            return "Function"
        if obj_type in self._class_decls:
            self._error(f"No member '{member}' on {obj_type}", info)
        return None

    def _check_binary_operands(
        self, op: str, left: Optional[str], right: Optional[str], info: TokenInfo
    ) -> None:
        if op == "+" and (left == "Str" or right == "Str"):
            return
        if op in ("&", "|", "^", "<<", ">>"):
            self._expect_type(left, "Int", info, f"'{op}' left operand must be Int")
            self._expect_type(right, "Int", info, f"'{op}' right operand must be Int")
            return
        if op in ("+", "-", "*", "/", "%"):
            self._expect_numeric(left, info, f"'{op}' left operand must be numeric")
            self._expect_numeric(right, info, f"'{op}' right operand must be numeric")

    def _expect_numeric(self, actual: Optional[str], info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable", "Int", "Float"):
            return
        self._error(f"{msg}, got {actual}", info)

    def _expect_type(self, actual: Optional[str], expected: str, info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable") or expected is None:
            return
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}, got {actual}", info)

    def _check_assignable(
        self, expected: Optional[str], actual: Optional[str], info: TokenInfo, msg: str
    ) -> None:
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}; expected {expected}", info)

    def _is_assignable(self, expected: Optional[str], actual: Optional[str]) -> bool:
        if expected is None or actual is None:
            return True
        if actual in ("PyObject", "PyCallable"):
            return True
        if expected == actual:
            return True
        if expected == "Float" and actual == "Int":
            return True
        if expected == "R" and actual in ("Ok", "Err"):
            return True
        return False

    def _common_type(self, left: Optional[str], right: Optional[str]) -> Optional[str]:
        if left is None:
            return right
        if right is None:
            return left
        if self._is_assignable(left, right):
            return left
        if self._is_assignable(right, left):
            return right
        return None
