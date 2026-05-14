"""Lower AST to IR.

Converts the parsed AST into the IR representation.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.frontend.parser.ast_nodes import *

from . import *


class LowerError(Exception):
    pass


class IRBuilder:
    """Helper to build IR basic blocks."""

    def __init__(self) -> None:
        self.blocks: list[BasicBlock] = []
        self._current: Optional[BasicBlock] = None
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


class FuncLowering:
    """Lowers a single function from AST to IR."""

    def __init__(
        self,
        func_name: str,
        is_method: bool = False,
        class_name: Optional[str] = None,
        nested_functions: Optional[list[IRFunction]] = None,
        next_func_idx: Optional[callable] = None,
    ) -> None:
        self.func_name = func_name
        self.is_method = is_method
        self.class_name = class_name
        self.builder = IRBuilder()
        self.locals: dict[str, int] = {}
        self.local_count = 0
        self._break_labels: list[Label] = []
        self._continue_labels: list[Label] = []
        self._string_pool: dict[str, int] = {}
        self._constants: list[object] = []
        self._class_info: dict = {}
        self._func_name_to_idx: dict = {}
        self._func_decls: dict[str, FunctionDecl] = {}
        self._class_init_decls: dict[str, FunctionDecl] = {}
        self._decorated_names: set[str] = set()
        self._global_names: set[str] = set()
        self._nested_functions = nested_functions if nested_functions is not None else []
        self._next_func_idx = next_func_idx
        self._lambda_counter = 0
        self._throw_handlers: list[tuple[Optional[int], Label]] = []

    def add_local(self, name: str) -> int:
        if name in self.locals:
            return self.locals[name]
        idx = self.local_count
        self.locals[name] = idx
        self.local_count += 1
        return idx

    def get_local(self, name: str) -> Optional[int]:
        return self.locals.get(name)

    def _const(self, value: object) -> int:
        for i, c in enumerate(self._constants):
            if type(c) is type(value) and c == value:
                return i
        idx = len(self._constants)
        self._constants.append(value)
        return idx

    def _string_const(self, value: str) -> int:
        if value in self._string_pool:
            return self._string_pool[value]
        idx = self._const(value)
        self._string_pool[value] = idx
        return idx

    def lower(self, func: FunctionDecl, global_vars: Optional[list[VarDecl]] = None) -> IRFunction:
        """Lower a function declaration to IR."""
        entry_label = self.builder.new_label(f"{self.func_name}.entry")
        entry_block = self.builder.add_block(entry_label)
        self.builder.set_current(entry_block)

        params = []
        if self.is_method:
            self.add_local("this")
            params.append("this")
        for p in func.params:
            self.add_local(p.name)
            params.append(p.name)

        if global_vars:
            for decl in global_vars:
                self._lower_global_var(decl)

        for stmt in func.body.statements:
            self._lower_stmt(stmt)

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
            self.builder.emit(Return(value=val))
        elif isinstance(stmt, BlockStmt):
            for s in stmt.statements:
                self._lower_stmt(s)
        elif isinstance(stmt, IfStmt):
            self._lower_if(stmt)
        elif isinstance(stmt, LoopStmt):
            self._lower_loop(stmt)
        elif isinstance(stmt, BreakStmt):
            if not self._break_labels:
                raise LowerError("'break' outside of loop")
            self.builder.emit(Jump(target=self._break_labels[-1]))
            new_label = self.builder.new_label("after_break")
            new_block = self.builder.add_block(new_label)
            self.builder.set_current(new_block)
        elif isinstance(stmt, ContinueStmt):
            if not self._continue_labels:
                raise LowerError("'continue' outside of loop")
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

    def _lower_global_var(self, stmt: VarDecl) -> None:
        if stmt.initializer:
            val = self._lower_expr(stmt.initializer)
        else:
            val = self.builder.new_reg("null")
            self.builder.emit(LoadConst(dest=val, value=None))
        self.builder.emit(StoreGlobal(src=val, name=stmt.name))

    def _lower_if(self, stmt: IfStmt) -> None:
        end_label = self.builder.new_label("if.end")
        else_label = self.builder.new_label("if.else")
        next_label = self.builder.new_label("if.next")

        cond = self._lower_expr(stmt.condition)
        self.builder.emit(BranchFalse(cond=cond, target=next_label))

        then_block = self.builder.add_block(self.builder.new_label("if.then"))
        self.builder.set_current(then_block)
        for s in stmt.then_branch.statements:
            self._lower_stmt(s)
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
            for s in elif_body.statements:
                self._lower_stmt(s)
            self.builder.emit(Jump(target=end_label))
            next_label = following_label

        else_block = self.builder.add_block(next_label if not stmt.elif_branches else else_label)
        self.builder.set_current(else_block)
        if stmt.else_branch:
            for s in stmt.else_branch.statements:
                self._lower_stmt(s)
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
        for s in stmt.body.statements:
            self._lower_stmt(s)
        self.builder.emit(Jump(target=continue_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        self._break_labels.pop()
        self._continue_labels.pop()

    def _lower_try_catch(self, stmt: TryCatchStmt) -> None:
        end_label = self.builder.new_label("try.end")
        catch_label = self.builder.new_label("catch")
        catch_slot = self.add_local(stmt.catch_var) if stmt.catch_body and stmt.catch_var else None
        if stmt.catch_body:
            self._throw_handlers.append((catch_slot, catch_label))
        for s in stmt.try_body.statements:
            self._lower_stmt(s)
        if stmt.catch_body:
            self._throw_handlers.pop()
        if stmt.catch_body:
            self.builder.emit(Jump(target=end_label))
            catch_block = self.builder.add_block(catch_label)
            self.builder.set_current(catch_block)
        if stmt.catch_body:
            for s in stmt.catch_body.statements:
                self._lower_stmt(s)
        if stmt.catch_body:
            self.builder.emit(Jump(target=end_label))
            end_block = self.builder.add_block(end_label)
            self.builder.set_current(end_block)
        if stmt.finally_body:
            for s in stmt.finally_body.statements:
                self._lower_stmt(s)

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
        elif isinstance(expr, ThisExpr):
            dest = self.builder.new_reg("this")
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
        elif isinstance(expr, CallExpr):
            return self._lower_call(expr)
        elif isinstance(expr, MemberExpr):
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
        elif isinstance(expr, SafeCallExpr):
            return self._lower_safe_call(expr)
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
        if isinstance(expr.body, BlockStmt):
            body = expr.body
        else:
            body = BlockStmt(
                statements=(ReturnStmt(value=expr.body, info=expr.info),), info=expr.info
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
        lowering = FuncLowering(
            lambda_name,
            nested_functions=self._nested_functions,
            next_func_idx=self._next_func_idx,
        )
        lowering._class_info = self._class_info
        lowering._func_name_to_idx = self._func_name_to_idx
        lowering._decorated_names = self._decorated_names
        lowering._global_names = self._global_names
        ir_func = lowering.lower(func_decl)
        setattr(ir_func, "reserved_func_idx", func_idx)
        self._nested_functions.append(ir_func)

        dest = self.builder.new_reg("lambda")
        self.builder.emit(MakeLambda(dest=dest, func_idx=func_idx, captures=[]))
        return dest

    def _lower_binary(self, expr: BinaryExpr) -> Operand:
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

    def _lower_assign(self, expr: AssignExpr) -> Operand:
        val = self._lower_expr(expr.value)
        if isinstance(expr.target, Identifier):
            slot = self.get_local(expr.target.name)
            if slot is None and expr.target.name in self._global_names:
                self.builder.emit(StoreGlobal(src=val, name=expr.target.name))
                return val
            if slot is None:
                slot = self.add_local(expr.target.name)
            self.builder.emit(StoreVar(src=val, slot=slot, name=expr.target.name))
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
            slot = self.get_local(expr.target.name)
            if slot is not None:
                left = self.builder.new_reg(expr.target.name)
                self.builder.emit(LoadVar(dest=left, slot=slot, name=expr.target.name))
            else:
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
        return self._lower_expr(expr.value)

    def _lower_call(self, expr: CallExpr) -> Operand:
        if isinstance(expr.callee, Identifier) and expr.callee.name in self._class_info:
            init = self._class_init_decls.get(expr.callee.name)
            args = self._lower_args(expr.args, init.params if init else None)
            dest = self.builder.new_reg("obj")
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
                if func_idx is not None and expr.callee.name not in self._decorated_names:
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

    def _lower_args(self, args: Sequence[Expr], params: Optional[Sequence[Param]]) -> list[Operand]:
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
        self.builder.emit(StoreVar(src=left, slot=result_slot, name="__elv_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("elv")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__elv_result"))
        return dest

    def _lower_safe_call(self, expr: SafeCallExpr) -> Operand:
        obj = self._lower_expr(expr.obj)
        call_label = self.builder.new_label("safe.call")
        end_label = self.builder.new_label("safe.end")
        result_slot = self.add_local(f"__safe_result_{len(self.locals)}")

        is_err = self.builder.new_reg("is_err")
        self.builder.emit(IsErr(dest=is_err, src=obj))
        self.builder.emit(BranchFalse(cond=is_err, target=call_label))

        null_reg = self.builder.new_reg("null")
        self.builder.emit(LoadConst(dest=null_reg, value=None))
        self.builder.emit(StoreVar(src=null_reg, slot=result_slot, name="__safe_result"))
        self.builder.emit(Jump(target=end_label))

        call_block = self.builder.add_block(call_label)
        self.builder.set_current(call_block)
        member = self.builder.new_reg("member")
        self.builder.emit(LoadMember(dest=member, obj=obj, member=expr.member))
        args = [self._lower_expr(arg) for arg in expr.args]
        call = self.builder.new_reg("safe")
        self.builder.emit(Call(dest=call, callee=member, args=args))
        self.builder.emit(StoreVar(src=call, slot=result_slot, name="__safe_result"))
        self.builder.emit(Jump(target=end_label))

        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)
        dest = self.builder.new_reg("safe")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__safe_result"))
        return dest

    def _lower_pattern_match(self, expr: PatternMatchExpr) -> Operand:
        scrutinee = self._lower_expr(expr.scrutinee)
        end_label = self.builder.new_label("match.end")
        result_slot = self.add_local(f"__match_result_{len(self.locals)}")

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
            elif pattern.kind == "literal":
                literal = self._lower_match_literal(pattern.value)  # type: ignore[arg-type]
                check = self.builder.new_reg("match_eq")
                self.builder.emit(Eq(dest=check, left=scrutinee, right=literal))
                self.builder.emit(BranchFalse(cond=check, target=next_label))

            if pattern.kind == "result":
                value = self.builder.new_reg("it")
                self.builder.emit(LoadMember(dest=value, obj=scrutinee, member="value"))
                self.builder.emit(SetIt(src=value))
            elif pattern.kind in ("type", "literal", "wildcard"):
                self.builder.emit(SetIt(src=scrutinee))
            if isinstance(arm.body, BlockStmt):
                for s in arm.body.statements:
                    self._lower_stmt(s)
                null_reg = self.builder.new_reg("null")
                self.builder.emit(LoadConst(dest=null_reg, value=None))
                self.builder.emit(StoreVar(src=null_reg, slot=result_slot, name="__match_result"))
            else:
                value = self._lower_expr(arm.body)
                self.builder.emit(StoreVar(src=value, slot=result_slot, name="__match_result"))
            self.builder.emit(Jump(target=end_label))

            next_block = self.builder.add_block(next_label)
            self.builder.set_current(next_block)

        null_reg = self.builder.new_reg("null")
        self.builder.emit(LoadConst(dest=null_reg, value=None))
        self.builder.emit(StoreVar(src=null_reg, slot=result_slot, name="__match_result"))
        self.builder.emit(Jump(target=end_label))
        end_block = self.builder.add_block(end_label)
        self.builder.set_current(end_block)

        dest = self.builder.new_reg("match")
        self.builder.emit(LoadVar(dest=dest, slot=result_slot, name="__match_result"))
        return dest

    def _lower_match_literal(self, pattern: Expr | str | None) -> Operand:
        if isinstance(pattern, Identifier):
            return Immediate(pattern.name)
        if isinstance(pattern, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            return self._lower_expr(pattern)
        if isinstance(pattern, str) or pattern is None:
            return Immediate(pattern)
        return self._lower_expr(pattern)


def lower_to_ir(ast: Program) -> IRProgram:
    """Lower an AST program to IR."""
    program = IRProgram(py_imports=dict(ast.py_imports))
    program.decorated_functions = [
        decl for decl in ast.declarations if isinstance(decl, FunctionDecl) and decl.decorators
    ]
    decorated_names = {decl.name for decl in program.decorated_functions}
    class_info = {}
    func_decls = {decl.name: decl for decl in ast.declarations if isinstance(decl, FunctionDecl)}
    global_vars = [decl for decl in ast.declarations if isinstance(decl, VarDecl)]
    global_names = {decl.name for decl in global_vars}
    class_init_decls = {}
    func_name_to_idx = {}

    # Pre-register functions in final emission order for direct calls.
    emission_order: list[str] = []

    for decl in ast.declarations:
        if isinstance(decl, ClassDecl):
            fields = []
            methods = {}
            for member in decl.members:
                if isinstance(member, VarDecl):
                    fields.append(member.name)
                elif isinstance(member, FunctionDecl):
                    methods[member.name] = -1
                elif isinstance(member, GetterDecl):
                    methods[f"get_{member.name}"] = -1
                elif isinstance(member, SetterDecl):
                    methods[f"set_{member.name}"] = -1
                if isinstance(member, FunctionDecl) and member.name == "init":
                    class_init_decls[decl.name] = member
            class_info[decl.name] = {"fields": fields, "methods": methods}

    for decl in ast.declarations:
        if isinstance(decl, FunctionDecl):
            emission_order.append(decl.name)
        elif isinstance(decl, ClassDecl):
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    emission_order.append(member.name)
                elif isinstance(member, GetterDecl):
                    emission_order.append(f"get_{member.name}")
                elif isinstance(member, SetterDecl):
                    emission_order.append(f"set_{member.name}")

    for idx, name in enumerate(emission_order):
        func_name_to_idx[name] = idx

    reserved_func_count = len(emission_order)
    nested_functions: list[IRFunction] = []

    def reserve_func_idx(name: str) -> int:
        nonlocal reserved_func_count
        idx = reserved_func_count
        reserved_func_count += 1
        func_name_to_idx[name] = idx
        return idx

    for decl in ast.declarations:
        if isinstance(decl, FunctionDecl):
            lowering = FuncLowering(
                decl.name, nested_functions=nested_functions, next_func_idx=reserve_func_idx
            )
            lowering._class_info = class_info
            lowering._func_name_to_idx = func_name_to_idx
            lowering._func_decls = func_decls
            lowering._class_init_decls = class_init_decls
            lowering._decorated_names = decorated_names
            lowering._global_names = global_names
            ir_func = lowering.lower(decl, global_vars if decl.name == "main" else None)
            func_idx = len(program.functions)
            program.functions.append(ir_func)
            func_name_to_idx[decl.name] = func_idx
        elif isinstance(decl, ClassDecl):
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    method = member
                    method_name = member.name
                elif isinstance(member, GetterDecl):
                    method = FunctionDecl(
                        name=f"get_{member.name}",
                        params=[],
                        return_type=member.return_type,
                        body=member.body,
                        is_pub=True,
                        is_static=False,
                        info=member.info,
                    )
                    method_name = f"get_{member.name}"
                elif isinstance(member, SetterDecl):
                    method = FunctionDecl(
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
                    method_name = f"set_{member.name}"
                else:
                    continue
                lowering = FuncLowering(
                    method.name,
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
                lowering._global_names = global_names
                ir_func = lowering.lower(method)
                func_idx = len(program.functions)
                program.functions.append(ir_func)
                class_info[decl.name]["methods"][method_name] = func_idx

    nested_functions.sort(key=lambda fn: getattr(fn, "reserved_func_idx"))
    program.functions.extend(nested_functions)

    for i, fn in enumerate(program.functions):
        if fn.name == "main":
            program.entry = i
            break

    program.classes = class_info
    return program
