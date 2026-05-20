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
    Decorator,
    DestructureAssignStmt,
    ElvExpr,
    ErrExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForInStmt,
    FunctionDecl,
    GetterDecl,
    Identifier,
    IfExpr,
    IfStmt,
    IncrementExpr,
    IndexExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MemberExpr,
    NullCoalesceExpr,
    NullLiteral,
    OkExpr,
    Param,
    PatternMatchExpr,
    Program,
    PropagateExpr,
    RangeExpr,
    ReturnStmt,
    SafeCallExpr,
    SafeMemberExpr,
    SetterDecl,
    SliceExpr,
    Stmt,
    StrLiteral,
    ThisExpr,
    ThrowStmt,
    TryCatchStmt,
    UnaryExpr,
    VarDecl,
    WhileStmt,
)


class Compiler:
    def __init__(self) -> None:
        self.program = ProgramBytecode()
        self._const_pool: dict[tuple[type, object], int] = {}
        self._class_info: dict[str, dict] = {}  # class_name -> {fields, methods}
        self._string_pool: dict[str, int] = {}
        self._func_name_to_idx: dict[str, int] = {}  # func_name -> index in program.functions
        self._func_decls: dict[str, FunctionDecl] = {}
        self._func_overloads: dict[str, list[FunctionDecl]] = {}
        self._overloaded_names: set[str] = set()
        self._class_init_decls: dict[str, FunctionDecl] = {}
        self._decorated_names: set[str] = set()
        self._decorated_classes: set[str] = set()
        self._global_names: set[str] = set()

    def compile(self, ast: Program) -> ProgramBytecode:
        self.program.py_imports = dict(ast.py_imports)
        self._decorated_names = {
            decl.name
            for decl in ast.declarations
            if isinstance(decl, FunctionDecl) and decl.decorators
        }
        self._decorated_classes = {
            decl.name
            for decl in ast.declarations
            if isinstance(decl, ClassDecl) and decl.decorators
        }
        global_vars = [decl for decl in ast.declarations if isinstance(decl, VarDecl)]
        self._global_names = {decl.name for decl in global_vars}
        self._func_overloads = {}
        for decl in ast.declarations:
            if isinstance(decl, FunctionDecl):
                self._func_overloads.setdefault(decl.name, []).append(decl)
        self._overloaded_names = {
            name for name, funcs in self._func_overloads.items() if len(funcs) > 1
        }
        self._func_decls = {
            name: funcs[0] for name, funcs in self._func_overloads.items() if len(funcs) == 1
        }
        for decl in ast.declarations:
            if isinstance(decl, ClassDecl):
                self._register_class(decl)
                for member in decl.members:
                    if isinstance(member, FunctionDecl) and member.name == "init":
                        self._class_init_decls[decl.name] = member

        decorated_globals: list[tuple[str, Sequence[Decorator], int]] = []
        decorated_methods: list[tuple[str, Sequence[Decorator]]] = []
        for decl in ast.declarations:
            if isinstance(decl, FunctionDecl):
                overload_index = self._func_overloads.get(decl.name, []).index(decl)
                is_overloaded = decl.name in self._overloaded_names
                internal_name = f"{decl.name}#{overload_index}" if is_overloaded else None
                func_idx = self._compile_function(
                    decl,
                    is_method=False,
                    global_vars=global_vars if decl.name == "main" else None,
                    internal_name=internal_name,
                    register_global=not is_overloaded,
                )
                if is_overloaded:
                    self.program.overloads.setdefault(decl.name, []).append(func_idx)
                if decl.decorators:
                    decorated_globals.append((decl.name, decl.decorators, func_idx))
            elif isinstance(decl, ClassDecl):
                decorated_methods.extend(self._compile_class_methods(decl))
                if decl.decorators:
                    ctor_idx = self._compile_class_constructor(decl)
                    decorated_globals.append((decl.name, decl.decorators, ctor_idx))

        for name, decorators, func_idx in decorated_globals:
            init_idx = self._compile_decorator_init(name, decorators, func_idx)
            self.program.decorators[name] = init_idx

        for key, decorators in decorated_methods:
            init_idx = self._compile_decorator_init(key, decorators)
            self.program.method_decorators[key] = init_idx

        for i, fn in enumerate(self.program.functions):
            if fn.name == "main":
                self.program.entry = i
                break

        self.program.classes = self._class_info
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

    def _register_class(self, cls: ClassDecl) -> None:
        fields = []
        method_groups: dict[str, list[FunctionDecl]] = {}
        getters: dict[str, int] = {}
        setters: dict[str, int] = {}
        for member in cls.members:
            if isinstance(member, VarDecl):
                fields.append(member.name)
            elif isinstance(member, FunctionDecl):
                method_groups.setdefault(member.name, []).append(member)
            elif isinstance(member, GetterDecl):
                getters[member.name] = -1
            elif isinstance(member, SetterDecl):
                setters[member.name] = -1
        methods = {name: -1 for name, members in method_groups.items() if len(members) == 1}
        method_overloads = {name: [] for name, members in method_groups.items() if len(members) > 1}
        self._class_info[cls.name] = {
            "fields": fields,
            "methods": methods,
            "method_overloads": method_overloads,
            "getters": getters,
            "setters": setters,
        }

    def _getter_function(self, member: GetterDecl) -> FunctionDecl:
        return FunctionDecl(
            name=f"get_{member.name}",
            params=[],
            return_type=member.return_type,
            body=member.body,
            is_pub=member.is_pub,
            is_static=False,
            info=member.info,
        )

    def _setter_function(self, member: SetterDecl) -> FunctionDecl:
        return FunctionDecl(
            name=f"set_{member.name}",
            params=[
                Param(
                    name=member.param_name,
                    type_annotation=member.param_type,
                    default=None,
                    is_optional=False,
                )
            ],
            return_type=None,
            body=member.body,
            is_pub=member.is_pub,
            is_static=False,
            info=member.info,
        )

    def _compile_class_methods(self, cls: ClassDecl) -> list[tuple[str, Sequence[Decorator]]]:
        decorated_methods: list[tuple[str, Sequence[Decorator]]] = []
        method_counts: dict[str, int] = {}
        method_group_sizes: dict[str, int] = {}
        for member in cls.members:
            if isinstance(member, FunctionDecl):
                method_group_sizes[member.name] = method_group_sizes.get(member.name, 0) + 1
        for member in cls.members:
            if isinstance(member, FunctionDecl):
                overload_index = method_counts.get(member.name, 0)
                method_counts[member.name] = overload_index + 1
                is_overloaded = method_group_sizes.get(member.name, 0) > 1
                internal_name = (
                    f"{cls.name}.{member.name}#{overload_index}" if is_overloaded else None
                )
                func_idx = self._compile_function(
                    member, is_method=True, class_name=cls.name, internal_name=internal_name
                )
                if is_overloaded:
                    self._class_info[cls.name]["method_overloads"][member.name].append(func_idx)
                else:
                    self._class_info[cls.name]["methods"][member.name] = func_idx
                if member.decorators:
                    decorated_methods.append((f"{cls.name}.{member.name}", member.decorators))
            elif isinstance(member, GetterDecl):
                func = self._getter_function(member)
                func_idx = self._compile_function(func, is_method=True, class_name=cls.name)
                self._class_info[cls.name]["getters"][member.name] = func_idx
            elif isinstance(member, SetterDecl):
                func = self._setter_function(member)
                func_idx = self._compile_function(func, is_method=True, class_name=cls.name)
                self._class_info[cls.name]["setters"][member.name] = func_idx
        return decorated_methods

    def _compile_class_constructor(self, cls: ClassDecl) -> int:
        init = self._class_init_decls.get(cls.name)
        params = init.params if init else ()
        fn = Function(
            name=f"<class:{cls.name}>",
            arity=len(params),
            param_types=[param.type_annotation for param in params],
        )
        func_idx = len(self.program.functions)
        self.program.functions.append(fn)
        ctx = FuncContext(fn, self)
        for param in params:
            ctx.add_local(param.name)
        for index, _ in enumerate(params):
            ctx.emit(Op.LOAD_VAR, index)
        ctx.emit(Op.MAKE_OBJECT, self._string_const(cls.name))
        ctx.emit(len(params))
        ctx.emit(Op.RETURN)
        fn.locals_count = ctx.max_locals
        return func_idx

    def _compile_function(
        self,
        func: FunctionDecl,
        is_method: bool = False,
        class_name: Optional[str] = None,
        global_vars: Optional[list[VarDecl]] = None,
        internal_name: Optional[str] = None,
        register_global: bool = True,
    ) -> int:
        fn = Function(
            name=internal_name or func.name,
            arity=len(func.params),
            is_method=is_method,
            class_name=class_name,
            param_types=[param.type_annotation for param in func.params],
            type_params=list(func.type_params),
        )
        func_idx = len(self.program.functions)
        self.program.functions.append(fn)
        if not is_method and register_global:
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
        fn = Function(
            name="<lambda>", arity=len(lam.params), param_types=[ptype for _, ptype in lam.params]
        )
        func_idx = len(self.program.functions)
        self.program.functions.append(fn)

        param_names = {pname for pname, _ in lam.params}
        captured = sorted(ctx.locals.items(), key=lambda item: item[1])
        fn.capture_count = len(captured)

        lam_ctx = FuncContext(fn, self)
        for name, slot in captured:
            local_name = f"__capture_shadow_{slot}_{name}" if name in param_names else name
            lam_ctx.add_local(local_name)
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

    def _compile_decorator_init(
        self, name: str, decorators: Sequence[Decorator], func_idx: Optional[int] = None
    ) -> int:
        fn = Function(name=f"<decorator:{name}>", arity=0 if func_idx is not None else 1)
        init_idx = len(self.program.functions)
        self.program.functions.append(fn)
        ctx = FuncContext(fn, self)

        value_slot = ctx.add_local(f"__decorated_{name}")
        if func_idx is not None:
            ctx.emit(Op.LOAD_FUNC, func_idx)
            ctx.emit(Op.STORE_VAR, value_slot)
            ctx.emit(Op.POP)

        for decorator in reversed(decorators):
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
        elif isinstance(stmt, WhileStmt):
            self._compile_while(stmt)
        elif isinstance(stmt, ForInStmt):
            self._compile_for_in(stmt)
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
        elif isinstance(stmt, DestructureAssignStmt):
            self._compile_destructure_assignment(stmt)

    def compile_global_var(self, stmt: VarDecl) -> None:
        if not stmt.initializer:
            return
        self.compile_expr(stmt.initializer)
        self.emit(Op.STORE_GLOBAL, self.compiler._string_const(stmt.name))
        self.emit(Op.POP)

    def _compile_destructure_assignment(self, stmt: DestructureAssignStmt) -> None:
        value_slot = self.add_local(f"__destructure_value_{len(self.locals)}")
        self.compile_expr(stmt.value)
        self.emit(Op.STORE_VAR, value_slot)
        self.emit(Op.POP)
        for index, target in enumerate(stmt.targets):
            self.emit(Op.LOAD_VAR, value_slot)
            self.emit(Op.LOAD_CONST, self.compiler._const(index))
            self.emit(Op.INDEX)
            self._store_identifier(target)
            self.emit(Op.POP)

    def _store_identifier(self, name: str) -> None:
        slot = self.get_local(name)
        if slot is not None:
            self.emit(Op.STORE_VAR, slot)
        elif name in self.compiler._global_names:
            self.emit(Op.STORE_GLOBAL, self.compiler._string_const(name))
        else:
            self.emit(Op.STORE_VAR, self.add_local(name))

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

    def _compile_while(self, stmt: WhileStmt) -> None:
        loop_start = len(self.fn.code)
        self._break_targets.append([])
        self._continue_targets.append([])

        self.compile_expr(stmt.condition)
        false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        for s in stmt.body.statements:
            self.compile_stmt(s)

        for cont_idx in self._continue_targets.pop():
            self.fn.code[cont_idx] = loop_start
        self.emit(Op.JUMP, loop_start)

        self.patch_jump(false_jump)
        for break_idx in self._break_targets.pop():
            self.patch_jump(break_idx)

    def _compile_for_in(self, stmt: ForInStmt) -> None:
        iter_slot = self.add_local(f"__for_iter_{len(self.locals)}")
        index_slot = self.add_local(f"__for_index_{len(self.locals)}")
        item_slot = self.add_local(stmt.var_name)

        self.compile_expr(stmt.iterable)
        self.emit(Op.STORE_VAR, iter_slot)
        self.emit(Op.POP)
        self.emit(Op.LOAD_CONST, self.compiler._const(0))
        self.emit(Op.STORE_VAR, index_slot)
        self.emit(Op.POP)

        loop_start = len(self.fn.code)
        self._break_targets.append([])
        self._continue_targets.append([])

        self.emit(Op.LOAD_VAR, index_slot)
        self.emit(Op.LOAD_VAR, iter_slot)
        self.emit(Op.MEMBER, self.compiler._string_const("size"))
        self.emit(Op.LT)
        false_jump = self.emit_jump(Op.JUMP_IF_FALSE)

        self.emit(Op.LOAD_VAR, iter_slot)
        self.emit(Op.LOAD_VAR, index_slot)
        self.emit(Op.INDEX)
        self.emit(Op.STORE_VAR, item_slot)
        self.emit(Op.POP)
        for s in stmt.body.statements:
            self.compile_stmt(s)

        increment_start = len(self.fn.code)
        self.emit(Op.LOAD_VAR, index_slot)
        self.emit(Op.LOAD_CONST, self.compiler._const(1))
        self.emit(Op.ADD)
        self.emit(Op.STORE_VAR, index_slot)
        self.emit(Op.POP)
        self.emit(Op.JUMP, loop_start)

        for cont_idx in self._continue_targets.pop():
            self.fn.code[cont_idx] = increment_start
        self.patch_jump(false_jump)
        for break_idx in self._break_targets.pop():
            self.patch_jump(break_idx)

    def _compile_try_catch(self, stmt: TryCatchStmt) -> None:
        if stmt.finally_body:
            self._compile_try_catch_with_finally(stmt)
            return

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

    def _compile_try_catch_with_finally(self, stmt: TryCatchStmt) -> None:
        finally_body = stmt.finally_body
        if finally_body is None:
            return
        pending_throw_slot = self.add_local(f"__finally_throw_{len(self.locals)}")
        catch_slot = self.add_local(stmt.catch_var) if stmt.catch_body and stmt.catch_var else None
        try_throw_jumps: list[int] = []
        handler_slot = catch_slot if stmt.catch_body else pending_throw_slot

        self._throw_handlers.append((handler_slot, try_throw_jumps))
        for s in stmt.try_body.statements:
            self.compile_stmt(s)
        self._throw_handlers.pop()

        normal_jump = self.emit_jump(Op.JUMP)
        for jump in try_throw_jumps:
            self.patch_jump(jump)

        catch_normal_jump = None
        catch_throw_jumps: list[int] = []
        catch_body = stmt.catch_body
        if catch_body is not None:
            self._throw_handlers.append((pending_throw_slot, catch_throw_jumps))
            for s in catch_body.statements:
                self.compile_stmt(s)
            self._throw_handlers.pop()
            catch_normal_jump = self.emit_jump(Op.JUMP)
            for jump in catch_throw_jumps:
                self.patch_jump(jump)

        for s in finally_body.statements:
            self.compile_stmt(s)
        self.emit(Op.LOAD_VAR, pending_throw_slot)
        self.emit(Op.MAKE_ERR)
        self.emit(Op.RETURN)

        self.patch_jump(normal_jump)
        if catch_normal_jump is not None:
            self.patch_jump(catch_normal_jump)
        for s in finally_body.statements:
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
            slot = self.get_local("this")
            if slot is not None and not self.fn.is_method:
                self.emit(Op.LOAD_VAR, slot)
            else:
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
                    self.compile_expr(expr.value)
                    self.emit(Op.STORE_GLOBAL, name_idx)
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
        elif isinstance(expr, IncrementExpr):
            self._compile_compound_assign(
                CompoundAssignExpr(
                    op="+=" if expr.delta > 0 else "-=",
                    target=expr.target,
                    value=IntLiteral(value=abs(expr.delta), info=expr.info),
                    info=expr.info,
                )
            )
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
            self.emit(Op.IS_ERR)
            ok_jump = self.emit_jump(Op.JUMP_IF_FALSE)
            self.emit(Op.POP)

            self.compile_expr(expr.right)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            done_jump = self.emit_jump(Op.JUMP)

            self.patch_jump(ok_jump)
            self.emit(Op.UNWRAP_OK)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)

            self.patch_jump(done_jump)
            self.emit(Op.LOAD_VAR, result_slot)
        elif isinstance(expr, NullCoalesceExpr):
            self._compile_null_coalesce(expr)
        elif isinstance(expr, PropagateExpr):
            self._compile_propagate(expr)
        elif isinstance(expr, SafeCallExpr):
            self._compile_safe_access(expr.obj, expr.member, expr.args)
        elif isinstance(expr, SafeMemberExpr):
            self._compile_safe_access(expr.obj, expr.member, None)
        elif isinstance(expr, IfExpr):
            self._compile_if_expr(expr)
        elif isinstance(expr, RangeExpr):
            self.compile_expr(expr.start)
            self.compile_expr(expr.end)
            self.emit(Op.MAKE_RANGE, 1 if expr.inclusive else 0)
        elif isinstance(expr, PatternMatchExpr):
            self._compile_pattern_match(expr)

    def _compile_predicate_from_stack(self, op: Op) -> None:
        pred_slot = self.add_local(f"__predicate_{len(self.locals)}")
        self.emit(op)
        self.emit(Op.STORE_VAR, pred_slot)
        self.emit(Op.POP)
        self.emit(Op.POP)
        self.emit(Op.LOAD_VAR, pred_slot)

    def _compile_null_coalesce(self, expr: NullCoalesceExpr) -> None:
        left_slot = self.add_local(f"__nullish_left_{len(self.locals)}")
        result_slot = self.add_local(f"__nullish_result_{len(self.locals)}")
        self.compile_expr(expr.left)
        self.emit(Op.STORE_VAR, left_slot)
        self.emit(Op.POP)

        self.emit(Op.LOAD_VAR, left_slot)
        self.emit(Op.LOAD_NULL)
        self.emit(Op.EQ)
        use_left_jump = self.emit_jump(Op.JUMP_IF_FALSE)

        self.compile_expr(expr.right)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)
        done_jump = self.emit_jump(Op.JUMP)

        self.patch_jump(use_left_jump)
        self.emit(Op.LOAD_VAR, left_slot)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)

        self.patch_jump(done_jump)
        self.emit(Op.LOAD_VAR, result_slot)

    def _compile_propagate(self, expr: PropagateExpr) -> None:
        value_slot = self.add_local(f"__propagate_value_{len(self.locals)}")
        self.compile_expr(expr.value)
        self.emit(Op.STORE_VAR, value_slot)
        self.emit(Op.POP)

        self.emit(Op.LOAD_VAR, value_slot)
        self._compile_predicate_from_stack(Op.IS_ERR)
        ok_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        self.emit(Op.LOAD_VAR, value_slot)
        self.emit(Op.RETURN)

        self.patch_jump(ok_jump)
        self.emit(Op.LOAD_VAR, value_slot)
        self.emit(Op.UNWRAP_OK)

    def _compile_safe_access(self, obj: Expr, member: str, args: Sequence[Expr] | None) -> None:
        obj_slot = self.add_local(f"__safe_obj_{len(self.locals)}")
        receiver_slot = self.add_local(f"__safe_receiver_{len(self.locals)}")
        result_slot = self.add_local(f"__safe_result_{len(self.locals)}")
        self.compile_expr(obj)
        self.emit(Op.STORE_VAR, obj_slot)
        self.emit(Op.POP)

        self.emit(Op.LOAD_VAR, obj_slot)
        self.emit(Op.IS_ERR)
        not_err_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        self.emit(Op.POP)
        self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)
        done_jumps = [self.emit_jump(Op.JUMP)]

        self.patch_jump(not_err_jump)
        self.emit(Op.POP)
        self.emit(Op.LOAD_VAR, obj_slot)
        self.emit(Op.LOAD_NULL)
        self.emit(Op.EQ)
        not_null_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)
        done_jumps.append(self.emit_jump(Op.JUMP))

        self.patch_jump(not_null_jump)
        self.emit(Op.LOAD_VAR, obj_slot)
        self.emit(Op.IS_OK)
        raw_receiver_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        self.emit(Op.UNWRAP_OK)
        self.emit(Op.STORE_VAR, receiver_slot)
        self.emit(Op.POP)
        access_jump = self.emit_jump(Op.JUMP)

        self.patch_jump(raw_receiver_jump)
        self.emit(Op.STORE_VAR, receiver_slot)
        self.emit(Op.POP)
        self.patch_jump(access_jump)

        self.emit(Op.LOAD_VAR, receiver_slot)
        self.emit(Op.MEMBER, self.compiler._string_const(member))
        if args is not None:
            for arg in args:
                self.compile_expr(arg)
            self.emit(Op.CALL, len(args))
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)

        for jump in done_jumps:
            self.patch_jump(jump)
        self.emit(Op.LOAD_VAR, result_slot)

    def _compile_binary(self, expr: BinaryExpr) -> None:
        if expr.op == "&&":
            self.compile_expr(expr.left)
            false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
            self.compile_expr(expr.right)
            end_jump = self.emit_jump(Op.JUMP)
            self.patch_jump(false_jump)
            self.emit(Op.LOAD_FALSE)
            self.patch_jump(end_jump)
            return

        if expr.op == "||":
            self.compile_expr(expr.left)
            true_jump = self.emit_jump(Op.JUMP_IF_TRUE)
            self.compile_expr(expr.right)
            end_jump = self.emit_jump(Op.JUMP)
            self.patch_jump(true_jump)
            self.emit(Op.LOAD_TRUE)
            self.patch_jump(end_jump)
            return

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
                self.emit(Op.LOAD_GLOBAL, name_idx)
                self.compile_expr(expr.value)
                self.emit(op_map[expr.op])
                self.emit(Op.STORE_GLOBAL, name_idx)
        elif isinstance(expr.target, MemberExpr):
            self.compile_expr(expr.target.obj)
            self.emit(Op.DUP)
            self.emit(Op.MEMBER, self.compiler._string_const(expr.target.member))
            self.compile_expr(expr.value)
            self.emit(op_map[expr.op])
            self.emit(Op.SET_MEMBER, self.compiler._string_const(expr.target.member))
        elif isinstance(expr.target, IndexExpr):
            obj_slot = self.add_local(f"__compound_obj_{len(self.locals)}")
            index_slot = self.add_local(f"__compound_index_{len(self.locals)}")
            result_slot = self.add_local(f"__compound_result_{len(self.locals)}")
            self.compile_expr(expr.target.obj)
            self.emit(Op.STORE_VAR, obj_slot)
            self.emit(Op.POP)
            self.compile_expr(expr.target.index)
            self.emit(Op.STORE_VAR, index_slot)
            self.emit(Op.POP)
            self.emit(Op.LOAD_VAR, obj_slot)
            self.emit(Op.LOAD_VAR, index_slot)
            self.emit(Op.INDEX)
            self.compile_expr(expr.value)
            self.emit(op_map[expr.op])
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            self.emit(Op.LOAD_VAR, obj_slot)
            self.emit(Op.LOAD_VAR, index_slot)
            self.emit(Op.LOAD_VAR, result_slot)
            self.emit(Op.SET_INDEX)

    def _compile_call(self, expr: CallExpr) -> None:
        if isinstance(expr.callee, Identifier) and expr.callee.name in self.compiler._class_info:
            init = self.compiler._class_init_decls.get(expr.callee.name)
            if expr.callee.name in self.compiler._decorated_classes:
                self.emit(Op.LOAD_GLOBAL, self.compiler._string_const(expr.callee.name))
                nargs = self._compile_args(expr.args, init.params if init else None)
                self.emit(Op.CALL, nargs)
                return
            nargs = self._compile_args(expr.args, init.params if init else None)
            self.emit(Op.MAKE_OBJECT, self.compiler._string_const(expr.callee.name))
            self.emit(nargs)
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
        saved_it_slot = self.add_local(f"__match_saved_it_{len(self.locals)}")
        self.emit(Op.LOAD_IT)
        self.emit(Op.STORE_VAR, saved_it_slot)
        self.emit(Op.POP)
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
                self._compile_block_value(arm.body)
            else:
                self.compile_expr(arm.body)

            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            self.emit(Op.LOAD_VAR, saved_it_slot)
            self.emit(Op.SET_IT)
            end_jumps.append(self.emit_jump(Op.JUMP))
            if false_jump is not None:
                self.patch_jump(false_jump)

        self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)
        self.emit(Op.LOAD_VAR, saved_it_slot)
        self.emit(Op.SET_IT)

        for idx in end_jumps:
            self.patch_jump(idx)

        self.emit(Op.LOAD_VAR, result_slot)

    def _compile_if_expr(self, expr: IfExpr) -> None:
        result_slot = self.add_local(f"__if_result_{len(self.locals)}")
        self.compile_expr(expr.condition)
        end_jumps = []

        false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
        self._compile_block_value(expr.then_branch)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)
        end_jumps.append(self.emit_jump(Op.JUMP))
        self.patch_jump(false_jump)

        for elif_cond, elif_body in expr.elif_branches:
            self.compile_expr(elif_cond)
            false_jump = self.emit_jump(Op.JUMP_IF_FALSE)
            self._compile_block_value(elif_body)
            self.emit(Op.STORE_VAR, result_slot)
            self.emit(Op.POP)
            end_jumps.append(self.emit_jump(Op.JUMP))
            self.patch_jump(false_jump)

        if expr.else_branch:
            self._compile_block_value(expr.else_branch)
        else:
            self.emit(Op.LOAD_NULL)
        self.emit(Op.STORE_VAR, result_slot)
        self.emit(Op.POP)

        for idx in end_jumps:
            self.patch_jump(idx)

        self.emit(Op.LOAD_VAR, result_slot)

    def _compile_block_value(self, block: BlockStmt) -> None:
        statements = list(block.statements)
        if statements and isinstance(statements[-1], ExprStmt):
            for stmt in statements[:-1]:
                self.compile_stmt(stmt)
            self.compile_expr(statements[-1].expr)
            return
        for stmt in statements:
            self.compile_stmt(stmt)
        self.emit(Op.LOAD_NULL)

    def _compile_match_literal(self, pattern: Expr) -> None:
        if isinstance(pattern, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            self.compile_expr(pattern)
        elif isinstance(pattern, Identifier):
            self.emit(Op.LOAD_CONST, self.compiler._string_const(pattern.name))
        else:
            self.compile_expr(pattern)


class CompileError(Exception):
    pass
