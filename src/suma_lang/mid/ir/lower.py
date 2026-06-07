"""Lower AST to IR.

Converts the parsed AST into the IR representation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from suma_lang.frontend.parser.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BlockStmt,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    ClassDecl,
    CompoundAssignExpr,
    ContinueStmt,
    DestructureAssignStmt,
    DestructureDeclStmt,
    ElvExpr,
    EnumDecl,
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
    InterpolatedStringExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MemberExpr,
    NullCoalesceExpr,
    NullLiteral,
    OkExpr,
    OuterIdentifier,
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
    TupleExpr,
    UnaryExpr,
    VarDecl,
    WhileStmt,
)

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
    IRType,
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
    Not,
    Operand,
    Or,
    Pop,
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


class LowerError(Exception):
    pass


class IRBuilder:
    """Helper to build IR basic blocks."""

    def __init__(self) -> None:
        self.blocks: list[BasicBlock] = []
        self._current: BasicBlock | None = None
        self._label_counter = 0
        self._reg_counter = 0

    def new_label(self, hint: str = "bb") -> Label:
        self._label_counter += 1
        return Label(f"{hint}.{self._label_counter}")

    def new_reg(self, hint: str = "v", ir_type: IRType = IRType.ANY) -> VirtualReg:
        self._reg_counter += 1
        return VirtualReg(f"{hint}", self._reg_counter, ir_type)

    def add_block(self, label: Label) -> BasicBlock:
        block = BasicBlock(label=label)
        self.blocks.append(block)
        return block

    def set_current(self, block: BasicBlock) -> None:
        self._current = block

    def emit(self, instr: IRInstr) -> None:
        if self._current is None:
            raise LowerError("No current basic block")
        self._current.instrs.append(instr)

    @property
    def current(self) -> BasicBlock:
        if self._current is None:
            raise LowerError("No current basic block")
        return self._current


def _getter_function(member: GetterDecl) -> FunctionDecl:
    return FunctionDecl(
        name=f"get_{member.name}",
        params=[],
        return_type=member.return_type,
        body=member.body,
        is_pub=member.is_pub,
        is_static=False,
        info=member.info,
    )


def _setter_function(member: SetterDecl) -> FunctionDecl:
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


class FuncLowering:
    """Lowers a single function from AST to IR."""

    def __init__(
        self,
        func_name: str,
        is_method: bool = False,
        class_name: str | None = None,
        nested_functions: list[IRFunction] | None = None,
        next_func_idx: Callable[[str], int] | None = None,
        captured_locals: Sequence[str] | None = None,
        capture_slots: Sequence[int] | None = None,
    ) -> None:
        self.func_name = func_name
        self.is_method = is_method
        self.class_name = class_name
        self.builder = IRBuilder()
        self.locals: dict[str, int] = {}
        self.local_count = 0
        self._scope_names: list[set[str]] = [set()]
        self._scope_shadows: list[list[tuple[str, int | None]]] = [[]]
        self._break_labels: list[Label] = []
        self._continue_labels: list[Label] = []
        self._string_pool: dict[str, int] = {}
        self._constants: list[object] = []
        self._const_pool: dict[tuple[type, object], int] = {}
        self._class_info: dict = {}
        self._func_name_to_idx: dict = {}
        self._func_decls: dict[str, FunctionDecl] = {}
        self._class_init_decls: dict[str, FunctionDecl] = {}
        self._decorated_names: set[str] = set()
        self._decorated_classes: set[str] = set()
        self._overloaded_names: set[str] = set()
        self._global_names: set[str] = set()
        self._enum_variants: dict[str, dict[str, str | None]] = {}
        self._nested_functions = nested_functions if nested_functions is not None else []
        self._next_func_idx = next_func_idx
        self._captured_locals = tuple(captured_locals or ())
        self._capture_slots = tuple(
            capture_slots if capture_slots is not None else range(len(self._captured_locals))
        )
        self._lambda_counter = 0
        self._throw_handlers: list[tuple[int | None, Label]] = []
        self._finally_bodies: list[BlockStmt] = []
        self._finally_handler_depths: list[int] = []

    def add_local(self, name: str) -> int:
        current_scope = self._scope_names[-1]
        if name in current_scope:
            return self.locals[name]
        previous = self.locals.get(name)
        self._scope_shadows[-1].append((name, previous))
        idx = self.local_count
        self.locals[name] = idx
        current_scope.add(name)
        self.local_count += 1
        return idx

    def get_local(self, name: str) -> int | None:
        return self.locals.get(name)

    def get_current_local(self, name: str) -> int | None:
        if name not in self._scope_names[-1]:
            return None
        return self.locals.get(name)

    def get_outer_local(self, name: str) -> int | None:
        if name not in self._scope_names[-1]:
            return self.locals.get(name)
        for shadow_name, previous in reversed(self._scope_shadows[-1]):
            if shadow_name == name:
                return previous
        return None

    def reserve_local(self) -> int:
        idx = self.local_count
        self.local_count += 1
        return idx

    def bind_local(self, name: str, slot: int) -> int:
        current_scope = self._scope_names[-1]
        if name in current_scope:
            return self.locals[name]
        previous = self.locals.get(name)
        self._scope_shadows[-1].append((name, previous))
        self.locals[name] = slot
        current_scope.add(name)
        self.local_count = max(self.local_count, slot + 1)
        return slot

    def push_scope(self) -> None:
        self._scope_names.append(set())
        self._scope_shadows.append([])

    def pop_scope(self) -> None:
        if len(self._scope_names) == 1:
            return
        for name, previous in reversed(self._scope_shadows.pop()):
            if previous is None:
                self.locals.pop(name, None)
            else:
                self.locals[name] = previous
        self._scope_names.pop()

    def lower_block(self, block: BlockStmt) -> None:
        self.push_scope()
        try:
            for stmt in block.statements:
                self._lower_stmt(stmt)
        finally:
            self.pop_scope()

    def _lower_active_finally(self) -> None:
        saved_bodies = self._finally_bodies
        saved_depths = self._finally_handler_depths
        saved_handlers = self._throw_handlers
        try:
            for index in range(len(saved_bodies) - 1, -1, -1):
                body = saved_bodies[index]
                self._finally_bodies = saved_bodies[:index]
                self._finally_handler_depths = saved_depths[:index]
                self._throw_handlers = saved_handlers[: saved_depths[index]]
                self.lower_block(body)
        finally:
            self._finally_bodies = saved_bodies
            self._finally_handler_depths = saved_depths
            self._throw_handlers = saved_handlers

    def _lower_pending_throw(self, value_slot: int) -> None:
        thrown = self.builder.new_reg("finally_throw")
        self.builder.emit(LoadVar(dest=thrown, slot=value_slot, name="__finally_throw"))
        if self._throw_handlers:
            catch_slot, catch_label = self._throw_handlers[-1]
            if catch_slot is not None:
                self.builder.emit(StoreVar(src=thrown, slot=catch_slot, name="__catch"))
            self.builder.emit(Jump(target=catch_label))
            return
        err = self.builder.new_reg("finally_err")
        self.builder.emit(MakeErr(dest=err, value=thrown))
        self.builder.emit(Return(value=err))

    def _const(self, value: object) -> int:
        key = (type(value), value)
        existing = self._const_pool.get(key)
        if existing is not None:
            return existing
        idx = len(self._constants)
        self._constants.append(value)
        self._const_pool[key] = idx
        return idx

    def _string_const(self, value: str) -> int:
        if value in self._string_pool:
            return self._string_pool[value]
        idx = self._const(value)
        self._string_pool[value] = idx
        return idx

    def lower(self, func: FunctionDecl, global_vars: list[VarDecl] | None = None) -> IRFunction:
        """Lower a function declaration to IR."""
        entry_label = self.builder.new_label(f"{self.func_name}.entry")
        entry_block = self.builder.add_block(entry_label)
        self.builder.set_current(entry_block)

        params = []
        for name in self._captured_locals:
            self.add_local(name)
        if self.is_method:
            self.add_local("this")
            params.append("this")
        for p in func.params:
            self.add_local(p.name)
            params.append(p.name)

        if global_vars:
            for decl in global_vars:
                self._lower_global_var(decl)

        self.push_scope()
        try:
            for stmt in func.body.statements:
                self._lower_stmt(stmt)
        finally:
            self.pop_scope()

        last_block = self.builder.current
        if not last_block.instrs or not isinstance(last_block.instrs[-1], Return):
            null_reg = self.builder.new_reg("null")
            self.builder.emit(LoadConst(dest=null_reg, value=None))
            self.builder.emit(Return(value=null_reg))

        ir_func = IRFunction(
            name=self.func_name,
            params=params,
            arity=len(func.params),
            is_method=self.is_method,
            class_name=self.class_name,
            entry=entry_block,
            blocks=self.builder.blocks,
            locals_count=self.local_count,
            capture_count=len(self._captured_locals),
            capture_slots=list(self._capture_slots),
            param_types=[param.type_annotation for param in func.params],
            type_params=list(func.type_params),
        )
        return ir_func

    def _lower_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, ExprStmt):
            result = self._lower_expr(stmt.expr)
            self.builder.emit(Pop(src=result))
        elif isinstance(stmt, VarDecl):
            if stmt.initializer:
                val = self._lower_expr(stmt.initializer)
            else:
                val = self.builder.new_reg("null")
                self.builder.emit(LoadConst(dest=val, value=None))
            slot = self.add_local(stmt.name)
            self.builder.emit(StoreVar(src=val, slot=slot, name=stmt.name))
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                val = self._lower_expr(stmt.value)
            else:
                val = self.builder.new_reg("null")
                self.builder.emit(LoadConst(dest=val, value=None))
            if self._finally_bodies:
                return_slot = self.add_local(f"__finally_return_{len(self.locals)}")
                self.builder.emit(StoreVar(src=val, slot=return_slot, name="__finally_return"))
                self._lower_active_finally()
                val = self.builder.new_reg("finally_return")
                self.builder.emit(LoadVar(dest=val, slot=return_slot, name="__finally_return"))
            self.builder.emit(Return(value=val))
        elif isinstance(stmt, BlockStmt):
            self.lower_block(stmt)
        elif isinstance(stmt, IfStmt):
            self._lower_if(stmt)
        elif isinstance(stmt, LoopStmt):
            self._lower_loop(stmt)
        elif isinstance(stmt, WhileStmt):
            self._lower_while(stmt)
        elif isinstance(stmt, ForInStmt):
            self._lower_for_in(stmt)
        elif isinstance(stmt, BreakStmt):
            if not self._break_labels:
                raise LowerError("'break' outside of loop")
            self._lower_active_finally()
            self.builder.emit(Jump(target=self._break_labels[-1]))
            new_label = self.builder.new_label("after_break")
            new_block = self.builder.add_block(new_label)
            self.builder.set_current(new_block)
        elif isinstance(stmt, ContinueStmt):
            if not self._continue_labels:
                raise LowerError("'continue' outside of loop")
            self._lower_active_finally()
            self.builder.emit(Jump(target=self._continue_labels[-1]))
            new_label = self.builder.new_label("after_continue")
            new_block = self.builder.add_block(new_label)
            self.builder.set_current(new_block)
        elif isinstance(stmt, ThrowStmt):
            if self._throw_handlers:
                catch_slot, catch_label = self._throw_handlers[-1]
                val = self._lower_expr(stmt.value)
                if catch_slot is not None:
                    self.builder.emit(StoreVar(src=val, slot=catch_slot, name="__catch"))
                self.builder.emit(Jump(target=catch_label))
                after_throw = self.builder.add_block(self.builder.new_label("after_throw"))
                self.builder.set_current(after_throw)
            else:
                val = self._lower_expr(stmt.value)
                err_reg = self.builder.new_reg("err")
                self.builder.emit(MakeErr(dest=err_reg, value=val))
                self.builder.emit(Return(value=err_reg))
        elif isinstance(stmt, TryCatchStmt):
            self._lower_try_catch(stmt)
        elif isinstance(stmt, DestructureAssignStmt):
            self._lower_destructure_assignment(stmt)
        elif isinstance(stmt, DestructureDeclStmt):
            self._lower_destructure_declaration(stmt)

    def _lower_global_var(self, stmt: VarDecl) -> None:
        if not stmt.initializer:
            return
        val = self._lower_expr(stmt.initializer)
        self.builder.emit(StoreGlobal(src=val, name=stmt.name))

    def _lower_destructure_assignment(self, stmt: DestructureAssignStmt) -> None:
        value_slot = self.add_local(f"__destructure_value_{len(self.locals)}")
        value = self._lower_expr(stmt.value)
        self.builder.emit(StoreVar(src=value, slot=value_slot, name="__destructure_value"))
        for index, target in enumerate(stmt.targets):
            loaded = self.builder.new_reg("destructure")
            self.builder.emit(LoadVar(dest=loaded, slot=value_slot, name="__destructure_value"))
            idx = self.builder.new_reg("destructure_index")
            self.builder.emit(LoadConst(dest=idx, value=index))
            item = self.builder.new_reg(target)
            self.builder.emit(LoadIndex(dest=item, obj=loaded, index=idx))
            self._store_identifier(target, item)

    def _lower_destructure_declaration(self, stmt: DestructureDeclStmt) -> None:
        value_slot = self.add_local(f"__destructure_value_{len(self.locals)}")
        value = self._lower_expr(stmt.value)
        self.builder.emit(StoreVar(src=value, slot=value_slot, name="__destructure_value"))
        for index, target in enumerate(stmt.targets):
            loaded = self.builder.new_reg("destructure")
            self.builder.emit(LoadVar(dest=loaded, slot=value_slot, name="__destructure_value"))
            idx = self.builder.new_reg("destructure_index")
            self.builder.emit(LoadConst(dest=idx, value=index))
            item = self.builder.new_reg(target)
            self.builder.emit(LoadIndex(dest=item, obj=loaded, index=idx))
            target_slot = self.add_local(target)
            self.builder.emit(StoreVar(src=item, slot=target_slot, name=target))

    def _store_identifier(self, name: str, value: Operand) -> None:
        slot = self.get_current_local(name)
        if slot is None:
            slot = self.add_local(name)
        self.builder.emit(StoreVar(src=value, slot=slot, name=name))

    def _lower_if(self, stmt: IfStmt) -> None:
        end_label = self.builder.new_label("if.end")
        else_label = self.builder.new_label("if.else")
        next_label = self.builder.new_label("if.next")

        cond = self._lower_expr(stmt.condition)
        self.builder.emit(BranchFalse(cond=cond, target=next_label))

        then_block = self.builder.add_block(self.builder.new_label("if.then"))
        self.builder.set_current(then_block)
        self.lower_block(stmt.then_branch)
        self.builder.emit(Jump(target=end_label))

        for index, (elif_cond, elif_body) in enumerate(stmt.elif_branches):
            cond_block = self.builder.add_block(next_label)
            self.builder.set_current(cond_block)
            following_label = (
                self.builder.new_label("if.next")
                if index + 1 < len(stmt.elif_branches)
                else else_label
            )
            cond = self._lower_expr(elif_cond)
            self.builder.emit(BranchFalse(cond=cond, target=following_label))

            body_block = self.builder.add_block(self.builder.new_label("elif.body"))
            self.builder.set_current(body_block)
            self.lower_block(elif_body)
            self.builder.emit(Jump(target=end_label))
            next_label = following_label

        else_block = self.builder.add_block(next_label if not stmt.elif_branches else else_label)
        self.builder.set_current(else_block)
        if stmt.else_branch:
            self.lower_block(stmt.else_branch)
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

    def _lower_loop(self, stmt: LoopStmt) -> None:
        body_label = self.builder.new_label("loop.body")
        continue_label = self.builder.new_label("loop.continue")
        end_label = self.builder.new_label("loop.end")

        self._break_labels.append(end_label)
        self._continue_labels.append(continue_label)

        self.builder.emit(Jump(target=continue_label))

        continue_block = self.builder.add_block(continue_label)
        self.builder.set_current(continue_block)
        self.builder.emit(Jump(target=body_label))

        body_block = self.builder.add_block(body_label)
        self.builder.set_current(body_block)
        self.lower_block(stmt.body)
        self.builder.emit(Jump(target=continue_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        self._break_labels.pop()
        self._continue_labels.pop()

    def _lower_while(self, stmt: WhileStmt) -> None:
        cond_label = self.builder.new_label("while.cond")
        body_label = self.builder.new_label("while.body")
        end_label = self.builder.new_label("while.end")

        self._break_labels.append(end_label)
        self._continue_labels.append(cond_label)
        self.builder.emit(Jump(target=cond_label))

        cond_block = self.builder.add_block(cond_label)
        self.builder.set_current(cond_block)
        cond = self._lower_expr(stmt.condition)
        self.builder.emit(BranchFalse(cond=cond, target=end_label))
        self.builder.emit(Jump(target=body_label))

        body_block = self.builder.add_block(body_label)
        self.builder.set_current(body_block)
        self.lower_block(stmt.body)
        self.builder.emit(Jump(target=cond_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        self._break_labels.pop()
        self._continue_labels.pop()

    def _lower_for_in(self, stmt: ForInStmt) -> None:
        if isinstance(stmt.iterable, RangeExpr):
            self._lower_for_range(stmt, stmt.iterable)
            return
        self.push_scope()
        iter_slot = self.add_local(f"__for_iter_{len(self.locals)}")
        index_slot = self.add_local(f"__for_index_{len(self.locals)}")
        item_slot = self.add_local(stmt.var_name)
        iterable = self._lower_expr(stmt.iterable)
        self.builder.emit(StoreVar(src=iterable, slot=iter_slot, name="__for_iter"))
        zero = self.builder.new_reg("zero")
        self.builder.emit(LoadConst(dest=zero, value=0))
        self.builder.emit(StoreVar(src=zero, slot=index_slot, name="__for_index"))

        cond_label = self.builder.new_label("for.cond")
        body_label = self.builder.new_label("for.body")
        inc_label = self.builder.new_label("for.inc")
        end_label = self.builder.new_label("for.end")

        self._break_labels.append(end_label)
        self._continue_labels.append(inc_label)
        self.builder.emit(Jump(target=cond_label))

        cond_block = self.builder.add_block(cond_label)
        self.builder.set_current(cond_block)
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        iter_value = self.builder.new_reg("for_iter")
        self.builder.emit(LoadVar(dest=iter_value, slot=iter_slot, name="__for_iter"))
        size = self.builder.new_reg("for_size")
        self.builder.emit(LoadMember(dest=size, obj=iter_value, member="size"))
        keep_going = self.builder.new_reg("for_keep")
        self.builder.emit(Lt(dest=keep_going, left=index, right=size))
        self.builder.emit(BranchFalse(cond=keep_going, target=end_label))
        self.builder.emit(Jump(target=body_label))

        body_block = self.builder.add_block(body_label)
        self.builder.set_current(body_block)
        iter_value = self.builder.new_reg("for_iter")
        self.builder.emit(LoadVar(dest=iter_value, slot=iter_slot, name="__for_iter"))
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        item = self.builder.new_reg("for_item")
        self.builder.emit(LoadIndex(dest=item, obj=iter_value, index=index))
        self.builder.emit(StoreVar(src=item, slot=item_slot, name=stmt.var_name))
        self.lower_block(stmt.body)
        self.builder.emit(Jump(target=inc_label))

        inc_block = self.builder.add_block(inc_label)
        self.builder.set_current(inc_block)
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        one = self.builder.new_reg("one")
        self.builder.emit(LoadConst(dest=one, value=1))
        next_index = self.builder.new_reg("for_next")
        self.builder.emit(Add(dest=next_index, left=index, right=one))
        self.builder.emit(StoreVar(src=next_index, slot=index_slot, name="__for_index"))
        self.builder.emit(Jump(target=cond_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        self._break_labels.pop()
        self._continue_labels.pop()
        self.pop_scope()

    def _lower_for_range(self, stmt: ForInStmt, range_expr: RangeExpr) -> None:
        self.push_scope()
        index_slot = self.add_local(f"__for_index_{len(self.locals)}")
        end_slot = self.add_local(f"__for_end_{len(self.locals)}")
        item_slot = self.add_local(stmt.var_name)

        start = self._lower_expr(range_expr.start)
        self.builder.emit(StoreVar(src=start, slot=index_slot, name="__for_index"))
        end = self._lower_expr(range_expr.end)
        self.builder.emit(StoreVar(src=end, slot=end_slot, name="__for_end"))

        cond_label = self.builder.new_label("for_range.cond")
        body_label = self.builder.new_label("for_range.body")
        inc_label = self.builder.new_label("for_range.inc")
        end_label = self.builder.new_label("for_range.end")

        self._break_labels.append(end_label)
        self._continue_labels.append(inc_label)
        self.builder.emit(Jump(target=cond_label))

        cond_block = self.builder.add_block(cond_label)
        self.builder.set_current(cond_block)
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        end_value = self.builder.new_reg("for_end")
        self.builder.emit(LoadVar(dest=end_value, slot=end_slot, name="__for_end"))
        keep_going = self.builder.new_reg("for_keep")
        if range_expr.inclusive:
            self.builder.emit(Le(dest=keep_going, left=index, right=end_value))
        else:
            self.builder.emit(Lt(dest=keep_going, left=index, right=end_value))
        self.builder.emit(BranchFalse(cond=keep_going, target=end_label))
        self.builder.emit(Jump(target=body_label))

        body_block = self.builder.add_block(body_label)
        self.builder.set_current(body_block)
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        self.builder.emit(StoreVar(src=index, slot=item_slot, name=stmt.var_name))
        self.lower_block(stmt.body)
        self.builder.emit(Jump(target=inc_label))

        inc_block = self.builder.add_block(inc_label)
        self.builder.set_current(inc_block)
        index = self.builder.new_reg("for_index")
        self.builder.emit(LoadVar(dest=index, slot=index_slot, name="__for_index"))
        one = self.builder.new_reg("one")
        self.builder.emit(LoadConst(dest=one, value=1))
        next_index = self.builder.new_reg("for_next")
        self.builder.emit(Add(dest=next_index, left=index, right=one))
        self.builder.emit(StoreVar(src=next_index, slot=index_slot, name="__for_index"))
        self.builder.emit(Jump(target=cond_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        self._break_labels.pop()
        self._continue_labels.pop()
        self.pop_scope()

    def _lower_try_catch(self, stmt: TryCatchStmt) -> None:
        if stmt.finally_body:
            self._lower_try_catch_with_finally(stmt)
            return

        end_label = self.builder.new_label("try.end")
        catch_label = self.builder.new_label("catch")
        catch_slot = self.reserve_local() if stmt.catch_body and stmt.catch_var else None
        if stmt.catch_body:
            self._throw_handlers.append((catch_slot, catch_label))
        self.lower_block(stmt.try_body)
        if stmt.catch_body:
            self._throw_handlers.pop()
        if stmt.catch_body:
            self.builder.emit(Jump(target=end_label))
            catch_block = self.builder.add_block(catch_label)
            self.builder.set_current(catch_block)
        if stmt.catch_body:
            self.push_scope()
            if stmt.catch_var and catch_slot is not None:
                self.bind_local(stmt.catch_var, catch_slot)
            self.lower_block(stmt.catch_body)
            self.pop_scope()
        if stmt.catch_body:
            self.builder.emit(Jump(target=end_label))
            end_block = self.builder.add_block(end_label)
            self.builder.set_current(end_block)

    def _lower_try_catch_with_finally(self, stmt: TryCatchStmt) -> None:
        finally_body = stmt.finally_body
        if finally_body is None:
            return
        end_label = self.builder.new_label("try.end")
        catch_label = self.builder.new_label("catch")
        throw_label = self.builder.new_label("finally.throw")
        normal_finally_label = self.builder.new_label("finally.normal")
        pending_throw_slot = self.add_local(f"__finally_throw_{len(self.locals)}")
        catch_slot = self.reserve_local() if stmt.catch_body and stmt.catch_var else None
        handler_slot = catch_slot if stmt.catch_body else pending_throw_slot
        handler_label = catch_label if stmt.catch_body else throw_label

        self._finally_handler_depths.append(len(self._throw_handlers))
        self._throw_handlers.append((handler_slot, handler_label))
        self._finally_bodies.append(finally_body)
        try:
            self.lower_block(stmt.try_body)
        finally:
            self._finally_bodies.pop()
            self._finally_handler_depths.pop()
            self._throw_handlers.pop()
        self.builder.emit(Jump(target=normal_finally_label))

        catch_body = stmt.catch_body
        if catch_body is not None:
            catch_block = self.builder.add_block(catch_label)
            self.builder.set_current(catch_block)
            self._finally_handler_depths.append(len(self._throw_handlers))
            self._throw_handlers.append((pending_throw_slot, throw_label))
            self._finally_bodies.append(finally_body)
            try:
                self.push_scope()
                if stmt.catch_var and catch_slot is not None:
                    self.bind_local(stmt.catch_var, catch_slot)
                self.lower_block(catch_body)
                self.pop_scope()
            finally:
                self._finally_bodies.pop()
                self._finally_handler_depths.pop()
                self._throw_handlers.pop()
            self.builder.emit(Jump(target=normal_finally_label))

        throw_block = self.builder.add_block(throw_label)
        self.builder.set_current(throw_block)
        self.lower_block(finally_body)
        self._lower_pending_throw(pending_throw_slot)

        normal_block = self.builder.add_block(normal_finally_label)
        self.builder.set_current(normal_block)
        self.lower_block(finally_body)
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

    def _lower_expr(self, expr: Expr) -> Operand:
        """Lower an expression, returning the operand holding the result."""
        if isinstance(expr, IntLiteral):
            dest = self.builder.new_reg("i", IRType.INT)
            self.builder.emit(LoadConst(dest=dest, value=expr.value))
            return dest
        elif isinstance(expr, FloatLiteral):
            dest = self.builder.new_reg("f", IRType.FLOAT)
            self.builder.emit(LoadConst(dest=dest, value=expr.value))
            return dest
        elif isinstance(expr, StrLiteral):
            dest = self.builder.new_reg("s", IRType.STR)
            self.builder.emit(LoadConst(dest=dest, value=expr.value))
            return dest
        elif isinstance(expr, InterpolatedStringExpr):
            return self._lower_interpolated_string(expr)
        elif isinstance(expr, BoolLiteral):
            dest = self.builder.new_reg("b", IRType.BOOL)
            self.builder.emit(LoadConst(dest=dest, value=expr.value))
            return dest
        elif isinstance(expr, NullLiteral):
            dest = self.builder.new_reg("n", IRType.NULL)
            self.builder.emit(LoadConst(dest=dest, value=None))
            return dest
        elif isinstance(expr, Identifier):
            slot = self.get_local(expr.name)
            if slot is not None:
                dest = self.builder.new_reg(expr.name)
                self.builder.emit(LoadVar(dest=dest, slot=slot, name=expr.name))
                return dest
            else:
                dest = self.builder.new_reg(expr.name)
                self.builder.emit(LoadGlobal(dest=dest, name=expr.name))
                return dest
        elif isinstance(expr, OuterIdentifier):
            slot = self.get_outer_local(expr.name)
            dest = self.builder.new_reg(expr.name)
            if slot is not None:
                self.builder.emit(LoadVar(dest=dest, slot=slot, name=expr.name))
            elif expr.name in self._global_names:
                self.builder.emit(LoadGlobal(dest=dest, name=expr.name))
            else:
                raise LowerError(f"Cannot access undefined outer name '{expr.name}'")
            return dest
        elif isinstance(expr, ThisExpr):
            dest = self.builder.new_reg("this")
            slot = self.get_local("this")
            if slot is not None and not self.is_method:
                self.builder.emit(LoadVar(dest=dest, slot=slot, name="this"))
            else:
                self.builder.emit(LoadThis(dest=dest))
            return dest
        elif isinstance(expr, ItExpr):
            dest = self.builder.new_reg("it")
            self.builder.emit(LoadIt(dest=dest))
            return dest
        elif isinstance(expr, UnaryExpr):
            src = self._lower_expr(expr.operand)
            dest = self.builder.new_reg("unary")
            if expr.op == "-":
                self.builder.emit(Neg(dest=dest, src=src))
            elif expr.op == "!":
                self.builder.emit(Not(dest=dest, src=src))
            elif expr.op == "~":
                self.builder.emit(BitNot(dest=dest, src=src))
            return dest
        elif isinstance(expr, BinaryExpr):
            return self._lower_binary(expr)
        elif isinstance(expr, AssignExpr):
            return self._lower_assign(expr)
        elif isinstance(expr, CompoundAssignExpr):
            return self._lower_compound_assign(expr)
        elif isinstance(expr, IncrementExpr):
            return self._lower_compound_assign(
                CompoundAssignExpr(
                    op="+=" if expr.delta > 0 else "-=",
                    target=expr.target,
                    value=IntLiteral(value=abs(expr.delta), info=expr.info),
                    info=expr.info,
                )
            )
        elif isinstance(expr, CallExpr):
            return self._lower_call(expr)
        elif isinstance(expr, MemberExpr):
            tag = self._enum_variant_tag(expr)
            if tag is not None:
                expected = self._enum_variant_arity(tag)
                if expected != 0:
                    raise LowerError(f"Enum variant '{tag}' expects {expected} payload argument")
                dest = self.builder.new_reg("enum")
                self.builder.emit(MakeEnum(dest=dest, tag=tag, args=[]))
                return dest
            obj = self._lower_expr(expr.obj)
            dest = self.builder.new_reg("member")
            self.builder.emit(LoadMember(dest=dest, obj=obj, member=expr.member))
            return dest
        elif isinstance(expr, IndexExpr):
            obj = self._lower_expr(expr.obj)
            idx = self._lower_expr(expr.index)
            dest = self.builder.new_reg("idx")
            self.builder.emit(LoadIndex(dest=dest, obj=obj, index=idx))
            return dest
        elif isinstance(expr, SliceExpr):
            obj = self._lower_expr(expr.obj)
            start = self._lower_expr(expr.start) if expr.start else None
            end = self._lower_expr(expr.end) if expr.end else None
            dest = self.builder.new_reg("slice")
            self.builder.emit(LoadSlice(dest=dest, obj=obj, start=start, end=end))
            return dest
        elif isinstance(expr, ListExpr):
            elems = [self._lower_expr(e) for e in expr.elements]
            dest = self.builder.new_reg("list", IRType.LIST)
            self.builder.emit(MakeList(dest=dest, elements=elems))
            return dest
        elif isinstance(expr, TupleExpr):
            elems = [self._lower_expr(e) for e in expr.elements]
            dest = self.builder.new_reg("tuple", IRType.TUPLE)
            self.builder.emit(MakeTuple(dest=dest, elements=elems))
            return dest
        elif isinstance(expr, OkExpr):
            val = self._lower_expr(expr.value)
            dest = self.builder.new_reg("ok")
            self.builder.emit(MakeOk(dest=dest, value=val))
            return dest
        elif isinstance(expr, ErrExpr):
            val = self._lower_expr(expr.value)
            dest = self.builder.new_reg("err")
            self.builder.emit(MakeErr(dest=dest, value=val))
            return dest
        elif isinstance(expr, LambdaExpr):
            return self._lower_lambda(expr)
        elif isinstance(expr, ElvExpr):
            return self._lower_elv(expr)
        elif isinstance(expr, NullCoalesceExpr):
            return self._lower_null_coalesce(expr)
        elif isinstance(expr, PropagateExpr):
            return self._lower_propagate(expr)
        elif isinstance(expr, SafeCallExpr):
            return self._lower_safe_access(expr.obj, expr.member, expr.args)
        elif isinstance(expr, SafeMemberExpr):
            return self._lower_safe_access(expr.obj, expr.member, None)
        elif isinstance(expr, IfExpr):
            return self._lower_if_expr(expr)
        elif isinstance(expr, RangeExpr):
            start = self._lower_expr(expr.start)
            end = self._lower_expr(expr.end)
            dest = self.builder.new_reg("range")
            self.builder.emit(MakeRange(dest=dest, start=start, end=end, inclusive=expr.inclusive))
            return dest
        elif isinstance(expr, PatternMatchExpr):
            return self._lower_pattern_match(expr)
        else:
            raise LowerError(f"Unsupported expression: {type(expr).__name__}")

    def _lower_lambda(self, expr: LambdaExpr) -> Operand:
        if self._next_func_idx is None:
            raise LowerError("Lambda lowering requires a function index allocator")

        self._lambda_counter += 1
        lambda_name = f"{self.func_name}.<lambda>{self._lambda_counter}"
        func_idx = self._next_func_idx(lambda_name)
        params = [
            Param(name=name, type_annotation=type_annotation, default=None, is_optional=False)
            for name, type_annotation in expr.params
        ]
        body = (
            expr.body
            if isinstance(expr.body, BlockStmt)
            else BlockStmt(
                statements=(ReturnStmt(value=expr.body, info=expr.info),), info=expr.info
            )
        )
        func_decl = FunctionDecl(
            name=lambda_name,
            params=params,
            return_type=expr.return_type,
            body=body,
            is_pub=False,
            is_static=False,
            info=expr.info,
        )
        param_names = {name for name, _ in expr.params}
        captured = sorted(self.locals.items(), key=lambda item: item[1])
        captured_locals = [
            f"__capture_shadow_{slot}_{name}" if name in param_names else name
            for name, slot in captured
        ]
        capture_slots = [slot for _, slot in captured]
        lowering = FuncLowering(
            lambda_name,
            nested_functions=self._nested_functions,
            next_func_idx=self._next_func_idx,
            captured_locals=captured_locals,
            capture_slots=capture_slots,
        )
        lowering._class_info = self._class_info
        lowering._func_name_to_idx = self._func_name_to_idx
        lowering._decorated_names = self._decorated_names
        lowering._decorated_classes = self._decorated_classes
        lowering._overloaded_names = self._overloaded_names
        lowering._global_names = self._global_names
        lowering._enum_variants = self._enum_variants
        ir_func = lowering.lower(func_decl)
        setattr(ir_func, "reserved_func_idx", func_idx)  # noqa: B010 — dynamic attr
        self._nested_functions.append(ir_func)

        dest = self.builder.new_reg("lambda")
        self.builder.emit(MakeLambda(dest=dest, func_idx=func_idx, captures=[]))
        return dest

    def _lower_binary(self, expr: BinaryExpr) -> Operand:
        if expr.op in ("&&", "||"):
            return self._lower_logical(expr)

        left = self._lower_expr(expr.left)
        dest = self.builder.new_reg("bin")

        if expr.op == "is" and isinstance(expr.right, Identifier):
            callee = self.builder.new_reg("is_type_fn")
            self.builder.emit(LoadGlobal(dest=callee, name="__suma_is_type"))
            type_name = self.builder.new_reg("type_name")
            self.builder.emit(LoadConst(dest=type_name, value=expr.right.name))
            self.builder.emit(Call(dest=dest, callee=callee, args=[left, type_name]))
            return dest

        right = self._lower_expr(expr.right)

        op_map = {
            "+": Add,
            "-": Sub,
            "*": Mul,
            "/": Div,
            "%": Mod,
            "==": Eq,
            "!=": Ne,
            ">": Gt,
            "<": Lt,
            ">=": Ge,
            "<=": Le,
            "&&": And,
            "||": Or,
            "&": BitAnd,
            "|": BitOr,
            "^": BitXor,
            "<<": Shl,
            ">>": Shr,
        }
        cls = op_map.get(expr.op)
        if cls:
            self.builder.emit(cls(dest=dest, left=left, right=right))
        return dest

    def _lower_interpolated_string(self, expr: InterpolatedStringExpr) -> Operand:
        if expr.parts and isinstance(expr.parts[0], StrLiteral):
            result = self._lower_expr(expr.parts[0])
            start = 1
        else:
            result = self.builder.new_reg("interp", IRType.STR)
            self.builder.emit(LoadConst(dest=result, value=""))
            start = 0
        for part in expr.parts[start:]:
            right = self._lower_expr(part)
            dest = self.builder.new_reg("interp", IRType.STR)
            self.builder.emit(Add(dest=dest, left=result, right=right))
            result = dest
        return result

    def _lower_logical(self, expr: BinaryExpr) -> Operand:
        left = self._lower_expr(expr.left)
        result_slot = self.add_local(f"__logical_result_{len(self.locals)}")
        right_label = self.builder.new_label("logical.right")
        shortcut_label = self.builder.new_label("logical.shortcut")
        end_label = self.builder.new_label("logical.end")

        if expr.op == "&&":
            self.builder.emit(BranchFalse(cond=left, target=shortcut_label))
        else:
            self.builder.emit(Branch(cond=left, target=shortcut_label))

        right_block = self.builder.add_block(right_label)
        self.builder.set_current(right_block)
        right = self._lower_expr(expr.right)
        self.builder.emit(StoreVar(src=right, slot=result_slot, name="__logical_result"))
        self.builder.emit(Jump(target=end_label))

        shortcut_block = self.builder.add_block(shortcut_label)
        self.builder.set_current(shortcut_block)
        shortcut = self.builder.new_reg("logical")
        self.builder.emit(LoadConst(dest=shortcut, value=expr.op == "||"))
        self.builder.emit(StoreVar(src=shortcut, slot=result_slot, name="__logical_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("logical")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__logical_result"))
        return dest

    def _lower_assign(self, expr: AssignExpr) -> Operand:
        val = self._lower_expr(expr.value)
        if isinstance(expr.target, Identifier):
            slot = self.get_current_local(expr.target.name)
            if slot is None:
                slot = self.add_local(expr.target.name)
            self.builder.emit(StoreVar(src=val, slot=slot, name=expr.target.name))
        elif isinstance(expr.target, OuterIdentifier):
            slot = self.get_outer_local(expr.target.name)
            if slot is not None:
                self.builder.emit(StoreVar(src=val, slot=slot, name=expr.target.name))
            elif expr.target.name in self._global_names:
                self.builder.emit(StoreGlobal(src=val, name=expr.target.name))
            else:
                raise LowerError(f"Cannot assign to undefined outer name '{expr.target.name}'")
        elif isinstance(expr.target, MemberExpr):
            obj = self._lower_expr(expr.target.obj)
            self.builder.emit(StoreMember(obj=obj, member=expr.target.member, value=val))
        elif isinstance(expr.target, IndexExpr):
            obj = self._lower_expr(expr.target.obj)
            index = self._lower_expr(expr.target.index)
            self.builder.emit(StoreIndex(obj=obj, index=index, value=val))
        return val

    def _lower_compound_assign(self, expr: CompoundAssignExpr) -> Operand:
        op_map = {"+": Add, "-": Sub, "*": Mul, "/": Div, "%": Mod}

        if isinstance(expr.target, Identifier):
            slot = self.get_current_local(expr.target.name)
            if slot is not None:
                left = self.builder.new_reg(expr.target.name)
                self.builder.emit(LoadVar(dest=left, slot=slot, name=expr.target.name))
            else:
                raise LowerError(
                    f"Cannot compound-assign '{expr.target.name}' outside the current scope"
                )
            right = self._lower_expr(expr.value)
            dest = self.builder.new_reg("compound")
            op_cls = op_map.get(expr.op.rstrip("="))
            if op_cls:
                self.builder.emit(op_cls(dest=dest, left=left, right=right))
            self.builder.emit(StoreVar(src=dest, slot=slot, name=expr.target.name))
            return dest
        elif isinstance(expr.target, OuterIdentifier):
            slot = self.get_outer_local(expr.target.name)
            left = self.builder.new_reg(expr.target.name)
            if slot is not None:
                self.builder.emit(LoadVar(dest=left, slot=slot, name=expr.target.name))
            else:
                if expr.target.name not in self._global_names:
                    raise LowerError(f"Cannot assign to undefined outer name '{expr.target.name}'")
                left = self.builder.new_reg(expr.target.name)
                self.builder.emit(LoadGlobal(dest=left, name=expr.target.name))
            right = self._lower_expr(expr.value)
            dest = self.builder.new_reg("compound")
            op_cls = op_map.get(expr.op.rstrip("="))
            if op_cls:
                self.builder.emit(op_cls(dest=dest, left=left, right=right))
            if slot is not None:
                self.builder.emit(StoreVar(src=dest, slot=slot, name=expr.target.name))
            else:
                self.builder.emit(StoreGlobal(src=dest, name=expr.target.name))
            return dest
        elif isinstance(expr.target, MemberExpr):
            obj = self._lower_expr(expr.target.obj)
            member = self.builder.new_reg("member")
            self.builder.emit(LoadMember(dest=member, obj=obj, member=expr.target.member))
            right = self._lower_expr(expr.value)
            dest = self.builder.new_reg("compound")
            op_cls = op_map.get(expr.op.rstrip("="))
            if op_cls:
                self.builder.emit(op_cls(dest=dest, left=member, right=right))
            self.builder.emit(StoreMember(obj=obj, member=expr.target.member, value=dest))
            return dest
        elif isinstance(expr.target, IndexExpr):
            obj = self._lower_expr(expr.target.obj)
            index = self._lower_expr(expr.target.index)
            current = self.builder.new_reg("index")
            self.builder.emit(LoadIndex(dest=current, obj=obj, index=index))
            right = self._lower_expr(expr.value)
            dest = self.builder.new_reg("compound")
            op_cls = op_map.get(expr.op.rstrip("="))
            if op_cls:
                self.builder.emit(op_cls(dest=dest, left=current, right=right))
            self.builder.emit(StoreIndex(obj=obj, index=index, value=dest))
            return dest
        return self._lower_expr(expr.value)

    def _lower_call(self, expr: CallExpr) -> Operand:
        if isinstance(expr.callee, MemberExpr):
            tag = self._enum_variant_tag(expr.callee)
            if tag is not None:
                expected = self._enum_variant_arity(tag)
                if len(expr.args) != expected:
                    raise LowerError(
                        f"Enum variant '{tag}' expects {expected} args, got {len(expr.args)}"
                    )
                args = [self._lower_expr(arg) for arg in expr.args]
                dest = self.builder.new_reg("enum")
                self.builder.emit(MakeEnum(dest=dest, tag=tag, args=args))
                return dest

        if isinstance(expr.callee, Identifier) and expr.callee.name in self._class_info:
            init = self._class_init_decls.get(expr.callee.name)
            args = self._lower_args(expr.args, init.params if init else None)
            dest = self.builder.new_reg("obj")
            if expr.callee.name in self._decorated_classes:
                callee = self.builder.new_reg(expr.callee.name)
                self.builder.emit(LoadGlobal(dest=callee, name=expr.callee.name))
                self.builder.emit(Call(dest=dest, callee=callee, args=args))
            else:
                self.builder.emit(MakeObject(dest=dest, class_name=expr.callee.name, args=args))
            return dest

        # Method calls stay dynamic so receiver binding remains correct.
        if isinstance(expr.callee, MemberExpr):
            callee = self._lower_expr(expr.callee)
            args = [self._lower_expr(a) for a in expr.args]
            dest = self.builder.new_reg("call")
            self.builder.emit(Call(dest=dest, callee=callee, args=args))
            return dest

        if isinstance(expr.callee, Identifier):
            slot = self.get_local(expr.callee.name)
            if slot is None:
                func_idx = self._func_name_to_idx.get(expr.callee.name)
                if (
                    func_idx is not None
                    and expr.callee.name not in self._decorated_names
                    and expr.callee.name not in self._overloaded_names
                ):
                    func_decl = self._func_decls.get(expr.callee.name)
                    args = self._lower_args(expr.args, func_decl.params if func_decl else None)
                    dest = self.builder.new_reg("call")
                    self.builder.emit(CallGlobal(dest=dest, func_idx=func_idx, args=args))
                    return dest

        callee = self._lower_expr(expr.callee)
        params = None
        if isinstance(expr.callee, Identifier):
            func_decl = self._func_decls.get(expr.callee.name)
            params = func_decl.params if func_decl else None
        args = self._lower_args(expr.args, params)
        dest = self.builder.new_reg("call")
        self.builder.emit(Call(dest=dest, callee=callee, args=args))
        return dest

    def _lower_args(self, args: Sequence[Expr], params: Sequence[Param] | None) -> list[Operand]:
        lowered = [self._lower_expr(a) for a in args]
        if params is not None:
            for param in params[len(args) :]:
                if param.default is None:
                    break
                lowered.append(self._lower_expr(param.default))
        return lowered

    def _lower_elv(self, expr: ElvExpr) -> Operand:
        left = self._lower_expr(expr.left)
        ok_label = self.builder.new_label("elv.ok")
        end_label = self.builder.new_label("elv.end")
        result_slot = self.add_local(f"__elv_result_{len(self.locals)}")

        is_err = self.builder.new_reg("is_err")
        self.builder.emit(IsErr(dest=is_err, src=left))
        self.builder.emit(BranchFalse(cond=is_err, target=ok_label))

        right = self._lower_expr(expr.right)
        self.builder.emit(StoreVar(src=right, slot=result_slot, name="__elv_result"))
        self.builder.emit(Jump(target=end_label))

        ok_block = self.builder.add_block(ok_label)
        self.builder.set_current(ok_block)
        ok_value = self.builder.new_reg("elv.ok_value")
        self.builder.emit(UnwrapOk(dest=ok_value, src=left))
        self.builder.emit(StoreVar(src=ok_value, slot=result_slot, name="__elv_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("elv")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__elv_result"))
        return dest

    def _lower_null_coalesce(self, expr: NullCoalesceExpr) -> Operand:
        left = self._lower_expr(expr.left)
        right_label = self.builder.new_label("nullish.right")
        left_label = self.builder.new_label("nullish.left")
        end_label = self.builder.new_label("nullish.end")
        result_slot = self.add_local(f"__nullish_result_{len(self.locals)}")

        is_null = self.builder.new_reg("is_null")
        self.builder.emit(Eq(dest=is_null, left=left, right=Immediate(None)))
        self.builder.emit(BranchFalse(cond=is_null, target=left_label))

        right_block = self.builder.add_block(right_label)
        self.builder.set_current(right_block)
        right = self._lower_expr(expr.right)
        self.builder.emit(StoreVar(src=right, slot=result_slot, name="__nullish_result"))
        self.builder.emit(Jump(target=end_label))

        left_block = self.builder.add_block(left_label)
        self.builder.set_current(left_block)
        self.builder.emit(StoreVar(src=left, slot=result_slot, name="__nullish_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("nullish")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__nullish_result"))
        return dest

    def _lower_propagate(self, expr: PropagateExpr) -> Operand:
        value = self._lower_expr(expr.value)
        ok_label = self.builder.new_label("propagate.ok")
        is_err = self.builder.new_reg("is_err")
        self.builder.emit(IsErr(dest=is_err, src=value))
        self.builder.emit(BranchFalse(cond=is_err, target=ok_label))
        self.builder.emit(Return(value=value))

        ok_block = self.builder.add_block(ok_label)
        self.builder.set_current(ok_block)
        dest = self.builder.new_reg("propagate")
        self.builder.emit(UnwrapOk(dest=dest, src=value))
        return dest

    def _lower_safe_access(
        self, obj_expr: Expr, member_name: str, args: Sequence[Expr] | None
    ) -> Operand:
        obj = self._lower_expr(obj_expr)
        null_label = self.builder.new_label("safe.null")
        raw_label = self.builder.new_label("safe.raw")
        access_label = self.builder.new_label("safe.access")
        end_label = self.builder.new_label("safe.end")
        result_slot = self.add_local(f"__safe_result_{len(self.locals)}")
        receiver_slot = self.add_local(f"__safe_receiver_{len(self.locals)}")

        is_err = self.builder.new_reg("is_err")
        self.builder.emit(IsErr(dest=is_err, src=obj))
        self.builder.emit(Branch(cond=is_err, target=null_label))
        is_null = self.builder.new_reg("is_null")
        self.builder.emit(Eq(dest=is_null, left=obj, right=Immediate(None)))
        self.builder.emit(Branch(cond=is_null, target=null_label))
        is_ok = self.builder.new_reg("is_ok")
        self.builder.emit(IsOk(dest=is_ok, src=obj))
        self.builder.emit(BranchFalse(cond=is_ok, target=raw_label))
        receiver = self.builder.new_reg("safe.receiver")
        self.builder.emit(UnwrapOk(dest=receiver, src=obj))
        self.builder.emit(StoreVar(src=receiver, slot=receiver_slot, name="__safe_receiver"))
        self.builder.emit(Jump(target=access_label))

        null_block = self.builder.add_block(null_label)
        self.builder.set_current(null_block)
        null_reg = self.builder.new_reg("null")
        self.builder.emit(LoadConst(dest=null_reg, value=None))
        self.builder.emit(StoreVar(src=null_reg, slot=result_slot, name="__safe_result"))
        self.builder.emit(Jump(target=end_label))

        raw_block = self.builder.add_block(raw_label)
        self.builder.set_current(raw_block)
        self.builder.emit(StoreVar(src=obj, slot=receiver_slot, name="__safe_receiver"))
        self.builder.emit(Jump(target=access_label))

        access_block = self.builder.add_block(access_label)
        self.builder.set_current(access_block)
        receiver_value = self.builder.new_reg("safe.receiver")
        self.builder.emit(LoadVar(dest=receiver_value, slot=receiver_slot, name="__safe_receiver"))
        member = self.builder.new_reg("member")
        self.builder.emit(LoadMember(dest=member, obj=receiver_value, member=member_name))
        if args is None:
            self.builder.emit(StoreVar(src=member, slot=result_slot, name="__safe_result"))
        else:
            lowered_args = [self._lower_expr(arg) for arg in args]
            call = self.builder.new_reg("safe")
            self.builder.emit(Call(dest=call, callee=member, args=lowered_args))
            self.builder.emit(StoreVar(src=call, slot=result_slot, name="__safe_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("safe")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__safe_result"))
        return dest

    def _lower_pattern_match(self, expr: PatternMatchExpr) -> Operand:
        end_label = self.builder.new_label("match.end")
        result_slot = self.add_local(f"__match_result_{len(self.locals)}")
        saved_it_slot = self.add_local(f"__match_saved_it_{len(self.locals)}")
        saved_it = self.builder.new_reg("saved_it")
        self.builder.emit(LoadIt(dest=saved_it))
        self.builder.emit(StoreVar(src=saved_it, slot=saved_it_slot, name="__match_saved_it"))
        scrutinee = self._lower_expr(expr.scrutinee)

        for arm in expr.arms:
            next_label = self.builder.new_label("match.next")
            pattern = arm.pattern

            if pattern.kind == "result" and pattern.value == "Ok":
                check = self.builder.new_reg("is_ok")
                self.builder.emit(IsOk(dest=check, src=scrutinee))
                self.builder.emit(BranchFalse(cond=check, target=next_label))
            elif pattern.kind == "result" and pattern.value == "Err":
                check = self.builder.new_reg("is_err")
                self.builder.emit(IsErr(dest=check, src=scrutinee))
                self.builder.emit(BranchFalse(cond=check, target=next_label))
            elif pattern.kind == "type":
                callee = self.builder.new_reg("is_type_fn")
                self.builder.emit(LoadGlobal(dest=callee, name="__suma_is_type"))
                type_name = self.builder.new_reg("type_name")
                self.builder.emit(LoadConst(dest=type_name, value=pattern.value))
                check = self.builder.new_reg("is_type")
                self.builder.emit(Call(dest=check, callee=callee, args=[scrutinee, type_name]))
                self.builder.emit(BranchFalse(cond=check, target=next_label))
            elif pattern.kind == "enum":
                check = self.builder.new_reg("is_enum")
                self.builder.emit(IsEnumVariant(dest=check, src=scrutinee, tag=str(pattern.value)))
                self.builder.emit(BranchFalse(cond=check, target=next_label))
            elif pattern.kind == "literal":
                literal = self._lower_match_literal(pattern.value)  # type: ignore[arg-type]
                check = self.builder.new_reg("match_eq")
                self.builder.emit(Eq(dest=check, left=scrutinee, right=literal))
                self.builder.emit(BranchFalse(cond=check, target=next_label))

            if pattern.kind == "result":
                value = self.builder.new_reg("it")
                self.builder.emit(LoadMember(dest=value, obj=scrutinee, member="value"))
                self.builder.emit(SetIt(src=value))
            elif pattern.kind == "enum":
                if self._enum_variant_arity(str(pattern.value)) > 0:
                    value = self.builder.new_reg("it")
                    self.builder.emit(LoadMember(dest=value, obj=scrutinee, member="value"))
                    self.builder.emit(SetIt(src=value))
                else:
                    self.builder.emit(SetIt(src=scrutinee))
            elif pattern.kind in ("type", "literal", "wildcard"):
                self.builder.emit(SetIt(src=scrutinee))
            binding_scope = arm.binding is not None and arm.binding != "it"
            if binding_scope:
                self.push_scope()
                binding_slot = self.add_local(arm.binding or "it")
                bound_value = self.builder.new_reg(arm.binding or "it")
                self.builder.emit(LoadIt(dest=bound_value))
                self.builder.emit(
                    StoreVar(src=bound_value, slot=binding_slot, name=arm.binding or "it")
                )
            if isinstance(arm.body, BlockStmt):
                value = self._lower_block_value(arm.body)
                self.builder.emit(StoreVar(src=value, slot=result_slot, name="__match_result"))
            else:
                value = self._lower_expr(arm.body)
                self.builder.emit(StoreVar(src=value, slot=result_slot, name="__match_result"))
            if binding_scope:
                self.pop_scope()
            restored_it = self.builder.new_reg("restore_it")
            self.builder.emit(
                LoadVar(dest=restored_it, slot=saved_it_slot, name="__match_saved_it")
            )
            self.builder.emit(SetIt(src=restored_it))
            self.builder.emit(Jump(target=end_label))

            next_block = self.builder.add_block(next_label)
            self.builder.set_current(next_block)

        null_reg = self.builder.new_reg("null")
        self.builder.emit(LoadConst(dest=null_reg, value=None))
        self.builder.emit(StoreVar(src=null_reg, slot=result_slot, name="__match_result"))
        restored_it = self.builder.new_reg("restore_it")
        self.builder.emit(LoadVar(dest=restored_it, slot=saved_it_slot, name="__match_saved_it"))
        self.builder.emit(SetIt(src=restored_it))
        self.builder.emit(Jump(target=end_label))
        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        dest = self.builder.new_reg("match")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__match_result"))
        return dest

    def _lower_if_expr(self, expr: IfExpr) -> Operand:
        result_slot = self.add_local(f"__if_result_{len(self.locals)}")
        end_label = self.builder.new_label("ifexpr.end")
        next_label = self.builder.new_label("ifexpr.next")

        cond = self._lower_expr(expr.condition)
        self.builder.emit(BranchFalse(cond=cond, target=next_label))

        then_block = self.builder.add_block(self.builder.new_label("ifexpr.then"))
        self.builder.set_current(then_block)
        value = self._lower_block_value(expr.then_branch)
        self.builder.emit(StoreVar(src=value, slot=result_slot, name="__if_result"))
        self.builder.emit(Jump(target=end_label))

        for index, (elif_cond, elif_body) in enumerate(expr.elif_branches):
            cond_block = self.builder.add_block(next_label)
            self.builder.set_current(cond_block)
            following_label = (
                self.builder.new_label("ifexpr.next")
                if index + 1 < len(expr.elif_branches)
                else self.builder.new_label("ifexpr.else")
            )
            cond = self._lower_expr(elif_cond)
            self.builder.emit(BranchFalse(cond=cond, target=following_label))

            body_block = self.builder.add_block(self.builder.new_label("ifexpr.elif"))
            self.builder.set_current(body_block)
            value = self._lower_block_value(elif_body)
            self.builder.emit(StoreVar(src=value, slot=result_slot, name="__if_result"))
            self.builder.emit(Jump(target=end_label))
            next_label = following_label

        else_block = self.builder.add_block(next_label)
        self.builder.set_current(else_block)
        if expr.else_branch:
            value = self._lower_block_value(expr.else_branch)
        else:
            value = self.builder.new_reg("null")
            self.builder.emit(LoadConst(dest=value, value=None))
        self.builder.emit(StoreVar(src=value, slot=result_slot, name="__if_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("if_result")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__if_result"))
        return dest

    def _lower_block_value(self, block: BlockStmt) -> Operand:
        self.push_scope()
        statements = list(block.statements)
        try:
            if statements and isinstance(statements[-1], ExprStmt):
                for stmt in statements[:-1]:
                    self._lower_stmt(stmt)
                return self._lower_expr(statements[-1].expr)
            for stmt in statements:
                self._lower_stmt(stmt)
            null_reg = self.builder.new_reg("null")
            self.builder.emit(LoadConst(dest=null_reg, value=None))
            return null_reg
        finally:
            self.pop_scope()

    def _lower_match_literal(self, pattern: Expr | str | None) -> Operand:
        if isinstance(pattern, Identifier):
            return Immediate(pattern.name)
        if isinstance(pattern, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            return self._lower_expr(pattern)
        if isinstance(pattern, str) or pattern is None:
            return Immediate(pattern)
        return self._lower_expr(pattern)

    def _enum_variant_tag(self, member: MemberExpr) -> str | None:
        if not isinstance(member.obj, Identifier):
            return None
        if self.get_local(member.obj.name) is not None:
            return None
        variants = self._enum_variants.get(member.obj.name)
        if variants is None or member.member not in variants:
            return None
        return f"{member.obj.name}.{member.member}"

    def _enum_variant_arity(self, tag: str) -> int:
        enum_name, variant_name = tag.split(".", 1)
        payload_type = self._enum_variants.get(enum_name, {}).get(variant_name)
        return 1 if payload_type is not None else 0


def lower_to_ir(ast: Program) -> IRProgram:
    """Lower an AST program to IR."""
    program = IRProgram(py_imports=dict(ast.py_imports))
    program.enums = {
        decl.name: {variant.name: variant.payload_type for variant in decl.variants}
        for decl in ast.declarations
        if isinstance(decl, EnumDecl)
    }
    program.decorated_functions = [
        decl for decl in ast.declarations if isinstance(decl, FunctionDecl) and decl.decorators
    ]
    program.decorated_classes = [
        decl for decl in ast.declarations if isinstance(decl, ClassDecl) and decl.decorators
    ]
    program.decorated_methods = [
        (f"{decl.name}.{member.name}", member)
        for decl in ast.declarations
        if isinstance(decl, ClassDecl)
        for member in decl.members
        if isinstance(member, FunctionDecl) and member.decorators
    ]
    decorated_names = {decl.name for decl in program.decorated_functions}
    decorated_classes = {decl.name for decl in program.decorated_classes}
    class_info = {}
    func_overloads: dict[str, list[FunctionDecl]] = {}
    for decl in ast.declarations:
        if isinstance(decl, FunctionDecl):
            func_overloads.setdefault(decl.name, []).append(decl)
    overloaded_names = {name for name, funcs in func_overloads.items() if len(funcs) > 1}
    func_decls = {name: funcs[0] for name, funcs in func_overloads.items() if len(funcs) == 1}
    global_vars = [decl for decl in ast.declarations if isinstance(decl, VarDecl)]
    global_names = {decl.name for decl in global_vars}
    class_init_decls = {}
    func_name_to_idx = {}

    # Pre-register functions in final emission order for direct calls.
    emission_order: list[tuple[str, str | None]] = []

    for decl in ast.declarations:
        if isinstance(decl, ClassDecl):
            fields = []
            method_groups: dict[str, list[FunctionDecl]] = {}
            getters: dict[str, int] = {}
            setters: dict[str, int] = {}
            for member in decl.members:
                if isinstance(member, VarDecl):
                    fields.append(member.name)
                elif isinstance(member, FunctionDecl):
                    method_groups.setdefault(member.name, []).append(member)
                    if member.name == "init" and decl.name not in class_init_decls:
                        class_init_decls[decl.name] = member
                elif isinstance(member, GetterDecl):
                    getters[member.name] = -1
                elif isinstance(member, SetterDecl):
                    setters[member.name] = -1
            methods = {name: -1 for name, members in method_groups.items() if len(members) == 1}
            method_overloads = {
                name: [] for name, members in method_groups.items() if len(members) > 1
            }
            class_info[decl.name] = {
                "fields": fields,
                "methods": methods,
                "method_overloads": method_overloads,
                "getters": getters,
                "setters": setters,
            }

    top_counts: dict[str, int] = {}
    for decl in ast.declarations:
        if isinstance(decl, FunctionDecl):
            overload_index = top_counts.get(decl.name, 0)
            top_counts[decl.name] = overload_index + 1
            internal_name = (
                f"{decl.name}#{overload_index}" if decl.name in overloaded_names else decl.name
            )
            emission_order.append(
                (internal_name, None if decl.name in overloaded_names else decl.name)
            )
        elif isinstance(decl, ClassDecl):
            member_counts: dict[str, int] = {}
            member_totals: dict[str, int] = {}
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    member_totals[member.name] = member_totals.get(member.name, 0) + 1
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    overload_index = member_counts.get(member.name, 0)
                    member_counts[member.name] = overload_index + 1
                    internal_name = (
                        f"{decl.name}.{member.name}#{overload_index}"
                        if member_totals.get(member.name, 0) > 1
                        else member.name
                    )
                    emission_order.append((internal_name, member.name))
                elif isinstance(member, GetterDecl):
                    emission_order.append((f"get_{member.name}", None))
                elif isinstance(member, SetterDecl):
                    emission_order.append((f"set_{member.name}", None))

    for idx, (internal_name, public_name) in enumerate(emission_order):
        func_name_to_idx[internal_name] = idx
        if public_name is not None:
            func_name_to_idx[public_name] = idx

    reserved_func_count = len(emission_order)
    nested_functions: list[IRFunction] = []

    def reserve_func_idx(name: str) -> int:
        nonlocal reserved_func_count
        idx = reserved_func_count
        reserved_func_count += 1
        func_name_to_idx[name] = idx
        return idx

    top_emit_counts: dict[str, int] = {}
    for decl in ast.declarations:
        if isinstance(decl, FunctionDecl):
            overload_index = top_emit_counts.get(decl.name, 0)
            top_emit_counts[decl.name] = overload_index + 1
            is_overloaded = decl.name in overloaded_names
            internal_name = f"{decl.name}#{overload_index}" if is_overloaded else decl.name
            lowering = FuncLowering(
                internal_name, nested_functions=nested_functions, next_func_idx=reserve_func_idx
            )
            lowering._class_info = class_info
            lowering._func_name_to_idx = func_name_to_idx
            lowering._func_decls = func_decls
            lowering._class_init_decls = class_init_decls
            lowering._decorated_names = decorated_names
            lowering._decorated_classes = decorated_classes
            lowering._overloaded_names = overloaded_names
            lowering._global_names = global_names
            lowering._enum_variants = program.enums
            ir_func = lowering.lower(decl, global_vars if decl.name == "main" else None)
            func_idx = len(program.functions)
            program.functions.append(ir_func)
            if is_overloaded:
                program.overloads.setdefault(decl.name, []).append(func_idx)
            else:
                func_name_to_idx[decl.name] = func_idx
        elif isinstance(decl, ClassDecl):
            method_counts: dict[str, int] = {}
            method_totals: dict[str, int] = {}
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    method_totals[member.name] = method_totals.get(member.name, 0) + 1
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    method = member
                    method_name = member.name
                    overload_index = method_counts.get(method_name, 0)
                    method_counts[method_name] = overload_index + 1
                    is_method_overloaded = method_totals.get(method_name, 0) > 1
                    internal_name = (
                        f"{decl.name}.{method_name}#{overload_index}"
                        if is_method_overloaded
                        else method.name
                    )
                elif isinstance(member, GetterDecl):
                    method = _getter_function(member)
                    method_name = f"get_{member.name}"
                    internal_name = method.name
                    is_method_overloaded = False
                elif isinstance(member, SetterDecl):
                    method = _setter_function(member)
                    method_name = f"set_{member.name}"
                    internal_name = method.name
                    is_method_overloaded = False
                else:
                    continue
                lowering = FuncLowering(
                    internal_name,
                    is_method=True,
                    class_name=decl.name,
                    nested_functions=nested_functions,
                    next_func_idx=reserve_func_idx,
                )
                lowering._class_info = class_info
                lowering._func_name_to_idx = func_name_to_idx
                lowering._func_decls = func_decls
                lowering._class_init_decls = class_init_decls
                lowering._decorated_names = decorated_names
                lowering._decorated_classes = decorated_classes
                lowering._overloaded_names = overloaded_names
                lowering._global_names = global_names
                lowering._enum_variants = program.enums
                ir_func = lowering.lower(method)
                func_idx = len(program.functions)
                program.functions.append(ir_func)
                if is_method_overloaded:
                    class_info[decl.name]["method_overloads"][method_name].append(func_idx)
                elif isinstance(member, GetterDecl):
                    class_info[decl.name]["getters"][member.name] = func_idx
                elif isinstance(member, SetterDecl):
                    class_info[decl.name]["setters"][member.name] = func_idx
                else:
                    class_info[decl.name]["methods"][method_name] = func_idx

    nested_functions.sort(key=lambda fn: getattr(fn, "reserved_func_idx"))  # noqa: B009 — dynamic attr
    program.functions.extend(nested_functions)

    for i, fn in enumerate(program.functions):
        if fn.name == "main":
            program.entry = i
            break

    program.classes = class_info
    return program
