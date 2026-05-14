"""Bytecode compiler for Suma-lang."""

from __future__ import annotations

from typing import Optional, Sequence

from src.backend.codegen.opcodes import Function, Op, ProgramBytecode
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
    TryCatchStmt,
    UnaryExpr,
    VarDecl,
)


class Compiler:
    def __init__(self) -> None:
        self.program = ProgramBytecode()
        self._class_info: dict[str, dict] = {}  # class_name -> {fields, methods}
        self._string_pool: dict[str, int] = {}
        self._func_name_to_idx: dict[str, int] = {}  # func_name -> index in program.functions
        self._func_decls: dict[str, FunctionDecl] = {}
        self._class_init_decls: dict[str, FunctionDecl] = {}
        self._decorated_names: set[str] = set()
        self._global_names: set[str] = set()

    def compile(self, ast: Program) -> ProgramBytecode:
        self.program.py_imports = dict(ast.py_imports)
        self._decorated_names = {
            decl.name
            for decl in ast.declarations
            if isinstance(decl, FunctionDecl) and decl.decorators
        }
        global_vars = [decl for decl in ast.declarations if isinstance(decl, VarDecl)]
        self._global_names = {decl.name for decl in global_vars}
        self._func_decls = {
            decl.name: decl for decl in ast.declarations if isinstance(decl, FunctionDecl)
        }
        for decl in ast.declarations:
            if isinstance(decl, ClassDecl):
                self._register_class(decl)
                for member in decl.members:
                    if isinstance(member, FunctionDecl) and member.name == "init":
                        self._class_init_decls[decl.name] = member

        decorated_functions: list[tuple[str, FunctionDecl, int]] = []
        for decl in ast.declarations:
            if isinstance(decl, FunctionDecl):
                func_idx = self._compile_function(
                    decl,
                    is_method=False,
                    global_vars=global_vars if decl.name == "main" else None,
                )
                if decl.decorators:
                    decorated_functions.append((decl.name, decl, func_idx))
            elif isinstance(decl, ClassDecl):
                self._compile_class_methods(decl)

        for name, func, func_idx in decorated_functions:
            init_idx = self._compile_decorator_init(name, func, func_idx)
            self.program.decorators[name] = init_idx

        for i, fn in enumerate(self.program.functions):
            if fn.name == "main":
                self.program.entry = i
                break

        self.program.classes = self._class_info
        return self.program

    def _const(self, value: object) -> int:
        """Add a constant and return its index."""
        for i, c in enumerate(self.program.constants):
            if type(c) is type(value) and c == value:
                return i
        idx = len(self.program.constants)
        self.program.constants.append(value)
        return idx

    def _string_const(self, value: str) -> int:
        """Add a string constant (dedup)."""
        if value in self._string_pool:
            return self._string_pool[value]
        idx = self._const(value)
        self._string_pool[value] = idx
        return idx

    def _register_class(self, cls: ClassDecl) -> None:
        fields = []
        methods = {}
        for member in cls.members:
            if isinstance(member, VarDecl):
                fields.append(member.name)
            elif isinstance(member, FunctionDecl):
                methods[member.name] = -1
            elif isinstance(member, GetterDecl):
                methods[f"get_{member.name}"] = -1
            elif isinstance(member, SetterDecl):
                methods[f"set_{member.name}"] = -1
        self._class_info[cls.name] = {"fields": fields, "methods": methods}

    def _compile_class_methods(self, cls: ClassDecl) -> None:
        for member in cls.members:
            if isinstance(member, FunctionDecl):
                func_idx = self._compile_function(member, is_method=True, class_name=cls.name)
                self._class_info[cls.name]["methods"][member.name] = func_idx
            elif isinstance(member, GetterDecl):
                func = FunctionDecl(
                    name=f"get_{member.name}",
                    params=[],
                    return_type=member.return_type,
                    body=member.body,
                    is_pub=True,
                    is_static=False,
                    info=member.info,
                )
                func_idx = self._compile_function(func, is_method=True, class_name=cls.name)
                self._class_info[cls.name]["methods"][f"get_{member.name}"] = func_idx
            elif isinstance(member, SetterDecl):
                func = FunctionDecl(
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
                func_idx = self._compile_function(func, is_method=True, class_name=cls.name)
                self._class_info[cls.name]["methods"][f"set_{member.name}"] = func_idx

    def _compile_function(
        self,
        func: FunctionDecl,
        is_method: bool = False,
        class_name: Optional[str] = None,
        global_vars: Optional[list[VarDecl]] = None,
    ) -> int:
        fn = Function(
            name=func.name, arity=len(func.params), is_method=is_method, class_name=class_name
        )
        func_idx = len(self.program.functions)
        self.program.functions.append(fn)
        if not is_method:
            self._func_name_to_idx[func.name] = func_idx

        ctx = FuncContext(fn, self)

        if is_method:
            ctx.add_local("this")
            for p in func.params:
                ctx.add_local(p.name)
        else:
            for p in func.params:
                ctx.add_local(p.name)

        if global_vars:
            for decl in global_vars:
                ctx.compile_global_var(decl)

        for stmt in func.body.statements:
            ctx.compile_stmt(stmt)

        stmts = func.body.statements
        if not stmts or not isinstance(stmts[-1], ReturnStmt):
            ctx.emit(Op.LOAD_NULL)
        ctx.emit(Op.RETURN)

        fn.locals_count = ctx.max_locals
        return func_idx

    def _compile_lambda(self, lam: LambdaExpr, ctx: FuncContext) -> int:
        fn = Function(name="<lambda>", arity=len(lam.params))
        func_idx = len(self.program.functions)
        self.program.functions.append(fn)

        lam_ctx = FuncContext(fn, self)
        for pname, _ in lam.params:
            lam_ctx.add_local(pname)

        if isinstance(lam.body, BlockStmt):
            for stmt in lam.body.statements:
                lam_ctx.compile_stmt(stmt)
            lam_ctx.emit(Op.RETURN)
        else:
            lam_ctx.compile_expr(lam.body)
            lam_ctx.emit(Op.RETURN)

        fn.locals_count = lam_ctx.max_locals
        return func_idx

    def _compile_decorator_init(self, name: str, func: FunctionDecl, func_idx: int) -> int:
        fn = Function(name=f"<decorator:{name}>", arity=0)
        init_idx = len(self.program.functions)
        self.program.functions.append(fn)
        ctx = FuncContext(fn, self)

        value_slot = ctx.add_local(f"__decorated_{name}")
        ctx.emit(Op.LOAD_FUNC, func_idx)
        ctx.emit(Op.STORE_VAR, value_slot)
        ctx.emit(Op.POP)

        for decorator in reversed(func.decorators):
            ctx.compile_expr(decorator.expr)
            ctx.emit(Op.LOAD_VAR, value_slot)
            ctx.emit(Op.CALL, 1)
            ctx.emit(Op.STORE_VAR, value_slot)
            ctx.emit(Op.POP)

        ctx.emit(Op.LOAD_VAR, value_slot)
        ctx.emit(Op.RETURN)
        fn.locals_count = ctx.max_locals
        return init_idx


class FuncContext:
    """Compilation context for a single function."""

    def __init__(self, fn: Function, compiler: Compiler) -> None:
        self.fn = fn
        self.compiler = compiler
        self.locals: dict[str, int] = {}
        self.max_locals = 0
        self._break_targets: list[list[int]] = []  # stack of patch lists
        self._continue_targets: list[list[int]] = []  # stack of patch lists
        self._throw_handlers: list[tuple[Optional[int], list[int]]] = []

    def emit(self, *args: int) -> int:
        """Emit instruction(s). Returns the index of the first emitted item."""
        idx = len(self.fn.code)
        for a in args:
            self.fn.code.append(a)
        return idx

    def emit_jump(self, op: Op) -> int:
        """Emit a jump instruction with placeholder target. Returns index to patch."""
        self.emit(op, 0)
        return len(self.fn.code) - 1

    def patch_jump(self, jump_idx: int) -> None:
        """Patch jump target to current position."""
        self.fn.code[jump_idx] = len(self.fn.code)

    def add_local(self, name: str) -> int:
        if name in self.locals:
            return self.locals[name]
        idx = len(self.locals)
        self.locals[name] = idx
        self.max_locals = max(self.max_locals, idx + 1)
        return idx

    def get_local(self, name: str) -> Optional[int]:
        return self.locals.get(name)

    def compile_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, ExprStmt):
            self.compile_expr(stmt.expr)
            self.emit(Op.POP)
        elif isinstance(stmt, VarDecl):
            if stmt.initializer:
                self.compile_expr(stmt.initializer)
            else:
                self.emit(Op.LOAD_NULL)
            slot = self.add_local(stmt.name)
            self.emit(Op.STORE_VAR, slot)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self.compile_expr(stmt.value)
            else:
                self.emit(Op.LOAD_NULL)
            self.emit(Op.RETURN)
        elif isinstance(stmt, BlockStmt):
            for s in stmt.statements:
                self.compile_stmt(s)
        elif isinstance(stmt, IfStmt):
            self._compile_if(stmt)
        elif isinstance(stmt, LoopStmt):
            self._compile_loop(stmt)
        elif isinstance(stmt, BreakStmt):
            if not self._break_targets:
                raise CompileError("'break' outside of loop")
            self.emit(Op.JUMP, 0)
            self._break_targets[-1].append(len(self.fn.code) - 1)
        elif isinstance(stmt, ContinueStmt):
            if not self._continue_targets:
                raise CompileError("'continue' outside of loop")
            self.emit(Op.JUMP, 0)
            self._continue_targets[-1].append(len(self.fn.code) - 1)
        elif isinstance(stmt, ThrowStmt):
            if self._throw_handlers:
                catch_slot, jumps = self._throw_handlers[-1]
                self.compile_expr(stmt.value)
                if catch_slot is not None:
                    self.emit(Op.STORE_VAR, catch_slot)
                self.emit(Op.POP)
                jumps.append(self.emit_jump(Op.JUMP))
            else:
                self.compile_expr(stmt.value)
                self.emit(Op.MAKE_ERR)
                self.emit(Op.RETURN)
        elif isinstance(stmt, TryCatchStmt):
            self._compile_try_catch(stmt)

    def compile_global_var(self, stmt: VarDecl) -> None:
        self.emit(Op.LOAD_CONST, self.compiler._string_const(stmt.name))
        if stmt.initializer:
            self.compile_expr(stmt.initializer)
        else:
            self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, -1)
        self.emit(Op.POP)

    def _compile_if(self, stmt: IfStmt) -> None:
        self.compile_expr(stmt.condition)
        end_jumps = []

        false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        for s in stmt.then_branch.statements:
            self.compile_stmt(s)
        end_jumps.append(self.emit_jump(Op.JUMP))
        self.patch_jump(false_jump)

        for elif_cond, elif_body in stmt.elif_branches:
            self.compile_expr(elif_cond)
            false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
            for s in elif_body.statements:
                self.compile_stmt(s)
            end_jumps.append(self.emit_jump(Op.JUMP))
            self.patch_jump(false_jump)

        if stmt.else_branch:
            for s in stmt.else_branch.statements:
                self.compile_stmt(s)

        for idx in end_jumps:
            self.patch_jump(idx)

    def _compile_loop(self, stmt: LoopStmt) -> None:
        loop_start = len(self.fn.code)
        self._break_targets.append([])
        self._continue_targets.append([])

        for s in stmt.body.statements:
            self.compile_stmt(s)

        self.emit(Op.JUMP, loop_start)

        for cont_idx in self._continue_targets.pop():
            self.fn.code[cont_idx] = loop_start

        for break_idx in self._break_targets.pop():
            self.patch_jump(break_idx)

    def _compile_try_catch(self, stmt: TryCatchStmt) -> None:
        catch_slot = self.add_local(stmt.catch_var) if stmt.catch_body and stmt.catch_var else None
        throw_jumps: list[int] = []
        if stmt.catch_body:
            self._throw_handlers.append((catch_slot, throw_jumps))
        for s in stmt.try_body.statements:
            self.compile_stmt(s)
        if stmt.catch_body:
            self._throw_handlers.pop()
        skip_catch = self.emit_jump(Op.JUMP) if stmt.catch_body else None
        for jump in throw_jumps:
            self.patch_jump(jump)
        if stmt.catch_body:
            for s in stmt.catch_body.statements:
                self.compile_stmt(s)
        if skip_catch is not None:
            self.patch_jump(skip_catch)
        if stmt.finally_body:
            for s in stmt.finally_body.statements:
                self.compile_stmt(s)

    def compile_expr(self, expr: Expr) -> None:
        if isinstance(expr, IntLiteral):
            self.emit(Op.LOAD_CONST, self.compiler._const(expr.value))
        elif isinstance(expr, FloatLiteral):
            self.emit(Op.LOAD_CONST, self.compiler._const(expr.value))
        elif isinstance(expr, StrLiteral):
            self.emit(Op.LOAD_CONST, self.compiler._string_const(expr.value))
        elif isinstance(expr, BoolLiteral):
            self.emit(Op.LOAD_TRUE if expr.value else Op.LOAD_FALSE)
        elif isinstance(expr, NullLiteral):
            self.emit(Op.LOAD_NULL)
        elif isinstance(expr, Identifier):
            slot = self.get_local(expr.name)
            if slot is not None:
                self.emit(Op.LOAD_VAR, slot)
            else:
                self.emit(Op.LOAD_GLOBAL, self.compiler._string_const(expr.name))
        elif isinstance(expr, ThisExpr):
            self.emit(Op.LOAD_THIS)
        elif isinstance(expr, ItExpr):
            self.emit(Op.LOAD_IT)
        elif isinstance(expr, UnaryExpr):
            self.compile_expr(expr.operand)
            if expr.op == "-":
                self.emit(Op.NEG)
            elif expr.op == "!":
                self.emit(Op.NOT)
            elif expr.op == "~":
                self.emit(Op.BIT_NOT)
        elif isinstance(expr, BinaryExpr):
            self._compile_binary(expr)
        elif isinstance(expr, AssignExpr):
            if isinstance(expr.target, Identifier):
                slot = self.get_local(expr.target.name)
                if slot is not None:
                    self.compile_expr(expr.value)
                    self.emit(Op.STORE_VAR, slot)
                elif expr.target.name in self.compiler._global_names:
                    name_idx = self.compiler._string_const(expr.target.name)
                    self.emit(Op.LOAD_CONST, name_idx)
                    self.compile_expr(expr.value)
                    self.emit(Op.STORE_VAR, -1)
                else:
                    self.compile_expr(expr.value)
                    slot = self.add_local(expr.target.name)
                    self.emit(Op.STORE_VAR, slot)
            elif isinstance(expr.target, MemberExpr):
                self.compile_expr(expr.target.obj)
                self.compile_expr(expr.value)
                self.emit(Op.SET_MEMBER, self.compiler._string_const(expr.target.member))
            elif isinstance(expr.target, IndexExpr):
                self.compile_expr(expr.target.obj)
                self.compile_expr(expr.target.index)
                self.compile_expr(expr.value)
                self.emit(Op.SET_INDEX)
        elif isinstance(expr, CompoundAssignExpr):
            self._compile_compound_assign(expr)
        elif isinstance(expr, CallExpr):
            self._compile_call(expr)
        elif isinstance(expr, MemberExpr):
            self.compile_expr(expr.obj)
            self.emit(Op.MEMBER, self.compiler._string_const(expr.member))
        elif isinstance(expr, IndexExpr):
            self.compile_expr(expr.obj)
            self.compile_expr(expr.index)
            self.emit(Op.INDEX)
        elif isinstance(expr, SliceExpr):
            self.compile_expr(expr.obj)
            mask = 0
            if expr.start:
                self.compile_expr(expr.start)
                mask |= 1
            if expr.end:
                self.compile_expr(expr.end)
                mask |= 2
            self.emit(Op.SLICE, mask)
        elif isinstance(expr, ListExpr):
            for elem in expr.elements:
                self.compile_expr(elem)
            self.emit(Op.MAKE_LIST, len(expr.elements))
        elif isinstance(expr, OkExpr):
            self.compile_expr(expr.value)
            self.emit(Op.MAKE_OK)
        elif isinstance(expr, ErrExpr):
            self.compile_expr(expr.value)
            self.emit(Op.MAKE_ERR)
        elif isinstance(expr, LambdaExpr):
            func_idx = self.compiler._compile_lambda(expr, self)
            self.emit(Op.MAKE_LAMBDA, func_idx)
        elif isinstance(expr, ElvExpr):
            left_slot = self.add_local(f"__elv_left_{len(self.locals)}")
            result_slot = self.add_local(f"__elv_result_{len(self.locals)}")
            self.compile_expr(expr.left)
            self.emit(Op.STORE_VAR, left_slot)
            self.emit(Op.POP)

            self.emit(Op.LOAD_VAR, left_slot)
            self._compile_predicate_from_stack(Op.IS_ERR)
            ok_jump = self.emit_jump(Op.JUMP_IF_FALSE)

            self.compile_expr(expr.right)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            done_jump = self.emit_jump(Op.JUMP)

            self.patch_jump(ok_jump)
            self.emit(Op.LOAD_VAR, left_slot)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)

            self.patch_jump(done_jump)
            self.emit(Op.LOAD_VAR, result_slot)
        elif isinstance(expr, SafeCallExpr):
            obj_slot = self.add_local(f"__safe_obj_{len(self.locals)}")
            result_slot = self.add_local(f"__safe_result_{len(self.locals)}")
            self.compile_expr(expr.obj)
            self.emit(Op.STORE_VAR, obj_slot)
            self.emit(Op.POP)

            self.emit(Op.LOAD_VAR, obj_slot)
            self._compile_predicate_from_stack(Op.IS_ERR)
            call_jump = self.emit_jump(Op.JUMP_IF_FALSE)

            self.emit(Op.LOAD_NULL)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            done_jump = self.emit_jump(Op.JUMP)

            self.patch_jump(call_jump)
            self.emit(Op.LOAD_VAR, obj_slot)
            self.emit(Op.MEMBER, self.compiler._string_const(expr.member))
            for arg in expr.args:
                self.compile_expr(arg)
            self.emit(Op.CALL, len(expr.args))
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)

            self.patch_jump(done_jump)
            self.emit(Op.LOAD_VAR, result_slot)
        elif isinstance(expr, PatternMatchExpr):
            self._compile_pattern_match(expr)

    def _compile_predicate_from_stack(self, op: Op) -> None:
        pred_slot = self.add_local(f"__predicate_{len(self.locals)}")
        self.emit(op)
        self.emit(Op.STORE_VAR, pred_slot)
        self.emit(Op.POP)
        self.emit(Op.POP)
        self.emit(Op.LOAD_VAR, pred_slot)

    def _compile_binary(self, expr: BinaryExpr) -> None:
        if expr.op == "is" and isinstance(expr.right, Identifier):
            self.emit(Op.LOAD_GLOBAL, self.compiler._string_const("__suma_is_type"))
            self.compile_expr(expr.left)
            self.emit(Op.LOAD_CONST, self.compiler._string_const(expr.right.name))
            self.emit(Op.CALL, 2)
            return
        self.compile_expr(expr.left)
        self.compile_expr(expr.right)
        op_map = {
            "+": Op.ADD,
            "-": Op.SUB,
            "*": Op.MUL,
            "/": Op.DIV,
            "%": Op.MOD,
            "==": Op.EQ,
            "!=": Op.NE,
            ">": Op.GT,
            "<": Op.LT,
            ">=": Op.GE,
            "<=": Op.LE,
            "&&": Op.AND,
            "||": Op.OR,
            "&": Op.BIT_AND,
            "|": Op.BIT_OR,
            "^": Op.BIT_XOR,
            "<<": Op.SHL,
            ">>": Op.SHR,
        }
        self.emit(op_map[expr.op])

    def _compile_compound_assign(self, expr: CompoundAssignExpr) -> None:
        op_map = {"+=": Op.ADD, "-=": Op.SUB, "*=": Op.MUL, "/=": Op.DIV, "%=": Op.MOD}
        if isinstance(expr.target, Identifier):
            slot = self.get_local(expr.target.name)
            if slot is not None:
                self.emit(Op.LOAD_VAR, slot)
                self.compile_expr(expr.value)
                self.emit(op_map[expr.op])
                self.emit(Op.STORE_VAR, slot)
            else:
                name_idx = self.compiler._string_const(expr.target.name)
                self.emit(Op.LOAD_CONST, name_idx)
                self.emit(Op.LOAD_GLOBAL, name_idx)
                self.compile_expr(expr.value)
                self.emit(op_map[expr.op])
                self.emit(Op.STORE_VAR, -1)
        elif isinstance(expr.target, MemberExpr):
            self.compile_expr(expr.target.obj)
            self.emit(Op.DUP)
            self.emit(Op.MEMBER, self.compiler._string_const(expr.target.member))
            self.compile_expr(expr.value)
            self.emit(op_map[expr.op])
            self.emit(Op.SET_MEMBER, self.compiler._string_const(expr.target.member))

    def _compile_call(self, expr: CallExpr) -> None:
        if isinstance(expr.callee, Identifier) and expr.callee.name in self.compiler._class_info:
            init = self.compiler._class_init_decls.get(expr.callee.name)
            self._compile_args(expr.args, init.params if init else None)
            self.emit(Op.MAKE_OBJECT, self.compiler._string_const(expr.callee.name))
            return

        if isinstance(expr.callee, Identifier):
            slot = self.get_local(expr.callee.name)
            if slot is None:
                func_idx = self.compiler._func_name_to_idx.get(expr.callee.name)
                if func_idx is not None and expr.callee.name not in self.compiler._decorated_names:
                    func_decl = self.compiler._func_decls.get(expr.callee.name)
                    nargs = self._compile_args(expr.args, func_decl.params if func_decl else None)
                    self.emit(Op.CALL_GLOBAL, (nargs << 16) | func_idx)
                    return

        if isinstance(expr.callee, Identifier):
            slot = self.get_local(expr.callee.name)
            if slot is not None:
                self.emit(Op.LOAD_VAR, slot)
            else:
                self.emit(Op.LOAD_GLOBAL, self.compiler._string_const(expr.callee.name))
        elif isinstance(expr.callee, MemberExpr):
            self.compile_expr(expr.callee.obj)
            self.emit(Op.MEMBER, self.compiler._string_const(expr.callee.member))
        else:
            self.compile_expr(expr.callee)

        params = None
        if isinstance(expr.callee, Identifier):
            func_decl = self.compiler._func_decls.get(expr.callee.name)
            params = func_decl.params if func_decl else None
        nargs = self._compile_args(expr.args, params)

        self.emit(Op.CALL, nargs)

    def _compile_args(self, args: Sequence[Expr], params: Optional[Sequence[Param]]) -> int:
        for arg in args:
            self.compile_expr(arg)
        if params is not None:
            defaults = 0
            for param in params[len(args) :]:
                if param.default is None:
                    break
                self.compile_expr(param.default)
                defaults += 1
            return len(args) + defaults
        return len(args)

    def _compile_pattern_match(self, expr: PatternMatchExpr) -> None:
        scrutinee_slot = self.add_local(f"__match_scrutinee_{len(self.locals)}")
        result_slot = self.add_local(f"__match_result_{len(self.locals)}")
        self.compile_expr(expr.scrutinee)
        self.emit(Op.STORE_VAR, scrutinee_slot)
        self.emit(Op.POP)

        end_jumps = []
        for arm in expr.arms:
            false_jump = None
            pattern = arm.pattern
            if pattern.kind == "result" and pattern.value == "Ok":
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self.emit(Op.IS_OK)
            elif pattern.kind == "result" and pattern.value == "Err":
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self.emit(Op.IS_ERR)
            elif pattern.kind == "type":
                self.emit(Op.LOAD_GLOBAL, self.compiler._string_const("__suma_is_type"))
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self.emit(Op.LOAD_CONST, self.compiler._string_const(str(pattern.value)))
                self.emit(Op.CALL, 2)
            elif pattern.kind == "literal":
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self._compile_match_literal(pattern.value)  # type: ignore[arg-type]
                self.emit(Op.EQ)

            if pattern.kind != "wildcard":
                pred_slot = self.add_local(f"__match_pred_{len(self.locals)}")
                self.emit(Op.STORE_VAR, pred_slot)
                self.emit(Op.POP)
                if pattern.kind == "result":
                    self.emit(Op.POP)
                self.emit(Op.LOAD_VAR, pred_slot)
                false_jump = self.emit_jump(Op.JUMP_IF_FALSE)

            if pattern.kind == "result":
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self.emit(Op.MEMBER, self.compiler._string_const("value"))
                self.emit(Op.SET_IT)
            elif pattern.kind in ("type", "literal", "wildcard"):
                self.emit(Op.LOAD_VAR, scrutinee_slot)
                self.emit(Op.SET_IT)

            if isinstance(arm.body, BlockStmt):
                for s in arm.body.statements:
                    self.compile_stmt(s)
                self.emit(Op.LOAD_NULL)
            else:
                self.compile_expr(arm.body)

            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            end_jumps.append(self.emit_jump(Op.JUMP))
            if false_jump is not None:
                self.patch_jump(false_jump)

        self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)

        for idx in end_jumps:
            self.patch_jump(idx)

        self.emit(Op.LOAD_VAR, result_slot)

    def _compile_match_literal(self, pattern: Expr) -> None:
        if isinstance(pattern, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            self.compile_expr(pattern)
        elif isinstance(pattern, Identifier):
            self.emit(Op.LOAD_CONST, self.compiler._string_const(pattern.name))
        else:
            self.compile_expr(pattern)


class CompileError(Exception):
    pass
