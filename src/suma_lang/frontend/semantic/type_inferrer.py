"""Expression type inference for the semantic analyzer.

``TypeInferrer`` owns the expression/type-checking half of semantic analysis:
expression inference, overload call checking, member access typing, enum pattern
checks, assignability, and common-type selection. It delegates registry/scope
queries and diagnostics back to the owning ``Analyzer``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from suma_lang.frontend.lexer.token_types import TokenInfo
from suma_lang.frontend.parser.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BlockStmt,
    BoolLiteral,
    CallExpr,
    CompoundAssignExpr,
    ElvExpr,
    ErrExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    FunctionDecl,
    Identifier,
    IfExpr,
    IncrementExpr,
    IndexExpr,
    InterpolatedStringExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    MatchPattern,
    MemberExpr,
    NullCoalesceExpr,
    NullLiteral,
    OkExpr,
    OuterIdentifier,
    Param,
    PatternMatchExpr,
    PropagateExpr,
    RangeExpr,
    ReturnStmt,
    SafeCallExpr,
    SafeMemberExpr,
    SliceExpr,
    StrLiteral,
    ThisExpr,
    TupleExpr,
    UnaryExpr,
)
from suma_lang.frontend.semantic.symbol_table import Symbol
from suma_lang.frontend.semantic.types import (
    ERROR_TYPE,
    base_type,
    erase_type,
    function_arg_types,
    function_return_type,
    is_error_type,
    lambda_type,
    nullable_inner_type,
    nullable_type,
    result_err_type,
    result_ok_type,
    split_type_args,
    substitute_type,
)


class TypeInferrer:
    def __init__(self, analyzer: Any) -> None:
        object.__setattr__(self, "_analyzer", analyzer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._analyzer, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_analyzer":
            object.__setattr__(self, name, value)
        else:
            setattr(self._analyzer, name, value)

    def _analyze_expr(self, expr: Expr) -> None:
        self._infer_expr(expr)

    def _infer_expr(self, expr: Expr) -> str | None:
        if isinstance(expr, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            return self._literal_type(expr)
        if isinstance(expr, InterpolatedStringExpr):
            for part in expr.parts:
                self._infer_expr(part)
            return "Str"
        elif isinstance(expr, Identifier):
            sym = self.current_scope.resolve(expr.name)
            if not sym:
                # builtins
                if expr.name not in self.BUILTINS:
                    self._error(f"Undefined name '{expr.name}'", expr.info)
                return self.BUILTINS.get(expr.name, (None, None, None))[1]
            if sym.kind == "enum":
                self._error(f"Enum '{expr.name}' is a type; use '{expr.name}.Variant'", expr.info)
                return sym.type_name
            return self._narrowed_type(sym) or sym.type_name
        if isinstance(expr, OuterIdentifier):
            sym = self._resolve_outer(expr.name)
            if sym is None:
                self._error(f"Undefined outer name '{expr.name}'", expr.info)
                return None
            return self._narrowed_type(sym) or sym.type_name
        if isinstance(expr, ThisExpr):
            if not self.current_class:
                self._error("'this' used outside of a class", expr.info)
            return self._current_class_instance_type()
        if isinstance(expr, ItExpr):
            sym = self.current_scope.resolve("it")
            if sym is None:
                self._error("'it' is only available inside match arms", expr.info)
                return ERROR_TYPE
            if sym.type_name == ERROR_TYPE:
                self._error("'it' is not available for this match arm", expr.info)
                return ERROR_TYPE
            return sym.type_name if sym else None
        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expr(expr.operand)
            unary_methods = {"-": "op_neg", "~": "op_bit_not", "!": "op_not"}
            method_name = unary_methods.get(expr.op)
            candidates = self._class_method_candidates(operand_type, method_name or "")
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, method_name or "", operand_type, expr.info
                    )
                fake_call = CallExpr(
                    callee=MemberExpr(obj=expr.operand, member=method_name or "", info=expr.info),
                    args=(),
                    info=expr.info,
                )
                return self._infer_function_call(
                    f"{base_type(operand_type)}.{method_name}",
                    [method for _, method in candidates],
                    fake_call,
                )
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
                sym = self.current_scope.resolve_local(expr.target.name)
                if sym is None:
                    # Bare `name = expr` in a nested scope silently shadows an
                    # outer binding rather than updating it (use `@name = ...`
                    # to update). The trap is by design but easy to hit in
                    # loop counters; surface it as a diagnostic so users notice.
                    self._check_implicit_shadow(expr.target.name, expr.target.info)
                    err = self.current_scope.define(
                        Symbol(name=expr.target.name, type_name=value_type, kind="var")
                    )
                    if err:
                        self._error(err, expr.target.info)
                    return value_type
                target_type = sym.type_name
                if sym.type_name == "Any":
                    sym.type_name = value_type
                self._clear_narrowing(sym)
            elif isinstance(expr.target, OuterIdentifier):
                sym = self._resolve_outer(expr.target.name)
                if sym is None:
                    self._error(f"Undefined outer name '{expr.target.name}'", expr.target.info)
                    return value_type
                target_type = sym.type_name
                if sym.type_name == "Any":
                    sym.type_name = value_type
                self._clear_narrowing(sym)
            else:
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
        if isinstance(expr, IncrementExpr):
            target_type = self._infer_assignment_target(expr.target)
            self._expect_numeric(target_type, expr.info, "'++/--' target must be numeric")
            return target_type
        if isinstance(expr, CallExpr):
            return self._infer_call(expr)
        if isinstance(expr, MemberExpr):
            enum_member_type = self._infer_enum_member_expr(expr)
            if enum_member_type is not None:
                return enum_member_type
            obj_type = self._infer_expr(expr.obj)
            return self._member_type(obj_type, expr.member, expr.info)
        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expr(expr.obj)
            index_type = self._infer_expr(expr.index)
            self._expect_type(index_type, "Int", expr.index.info, "index must be Int")
            if base_type(obj_type) == "Tuple":
                args = split_type_args(obj_type)
                if isinstance(expr.index, IntLiteral):
                    index = expr.index.value
                    if index < 0:
                        index += len(args)
                    if 0 <= index < len(args):
                        return args[index]
                    self._error(f"Tuple index {expr.index.value} out of range", expr.index.info)
                    return None
                return self._common_sequence_type(args)
            if obj_type == "Str":
                return "Str"
            if base_type(obj_type) == "List":
                args = split_type_args(obj_type)
                return args[0] if args else None
            if base_type(obj_type) == "Range":
                return "Int"
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
            if base_type(obj_type) == "List":
                return obj_type
            if obj_type == "Str":
                return obj_type
            if obj_type is not None:
                self._error(f"Cannot slice {obj_type}", expr.info)
            return None
        if isinstance(expr, ListExpr):
            elem_type = None
            for elem in expr.elements:
                elem_type = self._common_type(elem_type, self._infer_expr(elem))
            return f"List<{elem_type}>" if elem_type else "List"
        if isinstance(expr, TupleExpr):
            element_types = [self._infer_expr(elem) or "Any" for elem in expr.elements]
            return f"Tuple<{','.join(element_types)}>"
        if isinstance(expr, OkExpr):
            value_type = self._infer_expr(expr.value)
            return f"Ok<{value_type}>" if value_type else "Ok"
        if isinstance(expr, ErrExpr):
            value_type = self._infer_expr(expr.value)
            return f"Err<{value_type}>" if value_type else "Err"
        if isinstance(expr, LambdaExpr):
            scope = self._push_scope("function")
            prev_func = self.current_function
            saved_narrowings = self._narrowed_types
            self._narrowed_types = []
            lambda_params = [
                Param(name=pname, type_annotation=ptype, default=None, is_optional=False)
                for pname, ptype in expr.params
            ]
            lambda_body = (
                expr.body
                if isinstance(expr.body, BlockStmt)
                else BlockStmt(
                    statements=(ReturnStmt(value=expr.body, info=expr.info),),
                    info=expr.info,
                )
            )
            self.current_function = FunctionDecl(
                name="<lambda>",
                params=lambda_params,
                return_type=expr.return_type,
                body=lambda_body,
                is_pub=False,
                is_static=False,
                info=expr.info,
            )
            for param in lambda_params:
                sym = Symbol(name=param.name, type_name=param.type_annotation, kind="param")
                scope.define(sym)
            try:
                if isinstance(expr.body, BlockStmt):
                    self._analyze_block(expr.body)
                    result_type = expr.return_type
                else:
                    result_type = self._infer_expr(expr.body)
            finally:
                self._narrowed_types = saved_narrowings
                self.current_function = prev_func
                self._pop_scope()
            self._check_assignable(
                expr.return_type, result_type, expr.info, f"Lambda returns {result_type}"
            )
            return lambda_type(lambda_params, expr.return_type, result_type)
        if isinstance(expr, ElvExpr):
            left_type = self._infer_expr(expr.left)
            right_type = self._infer_expr(expr.right)
            if base_type(left_type) not in (None, "R", "Ok", "Err"):
                self._error("'else' operator requires a Result value", expr.info)
            return self._common_type(result_ok_type(left_type), right_type)
        if isinstance(expr, NullCoalesceExpr):
            left_type = self._infer_expr(expr.left)
            right_type = self._infer_expr(expr.right)
            if left_type == "Null":
                return right_type
            nullable_inner = nullable_inner_type(left_type)
            if nullable_inner is not None:
                return self._common_type(nullable_inner, right_type)
            return self._common_type(left_type, right_type)
        if isinstance(expr, PropagateExpr):
            value_type = self._infer_expr(expr.value)
            if base_type(value_type) not in (None, "R", "Ok", "Err"):
                self._error("'?' operator requires a Result value", expr.info)
            if self.current_function and not self._is_assignable(
                self.current_function.return_type, "R"
            ):
                self._error("'?' operator requires the current function to return R", expr.info)
            return result_ok_type(value_type)
        if isinstance(expr, SafeCallExpr):
            obj_type = self._infer_expr(expr.obj)
            receiver_type = self._safe_receiver_type(obj_type)
            candidates = self._class_method_candidates(receiver_type, expr.member)
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, expr.member, receiver_type, expr.info
                    )
                fake_call = CallExpr(
                    callee=MemberExpr(obj=expr.obj, member=expr.member, info=expr.info),
                    args=expr.args,
                    info=expr.info,
                )
                return_type = self._infer_function_call(
                    f"{base_type(receiver_type)}.{expr.member}",
                    [method for _, method in candidates],
                    fake_call,
                )
                return self._safe_access_type(obj_type, return_type)
            for arg in expr.args:
                self._infer_expr(arg)
            if base_type(receiver_type) in (None, "R", "Ok", "Err", "PyObject", "PyCallable"):
                return None
            member_type = self._member_type(receiver_type, expr.member, expr.info)
            return self._safe_access_type(obj_type, member_type)
        if isinstance(expr, SafeMemberExpr):
            obj_type = self._infer_expr(expr.obj)
            receiver_type = self._safe_receiver_type(obj_type)
            if base_type(receiver_type) in (None, "R", "Ok", "Err", "PyObject", "PyCallable"):
                return None
            member_type = self._member_type(receiver_type, expr.member, expr.info)
            return self._safe_access_type(obj_type, member_type)
        if isinstance(expr, IfExpr):
            return self._infer_if_expr(expr)
        if isinstance(expr, RangeExpr):
            start_type = self._infer_expr(expr.start)
            end_type = self._infer_expr(expr.end)
            self._expect_type(start_type, "Int", expr.start.info, "range start must be Int")
            self._expect_type(end_type, "Int", expr.end.info, "range end must be Int")
            return "Range"
        if isinstance(expr, PatternMatchExpr):
            scrutinee_type = self._infer_expr(expr.scrutinee)
            result_type = None
            for arm in expr.arms:
                if arm.pattern.kind == "literal" and not isinstance(arm.pattern.value, Identifier):
                    self._infer_expr(arm.pattern.value)  # type: ignore[arg-type]
                if arm.pattern.kind == "enum":
                    self._check_enum_pattern(scrutinee_type, arm.pattern, arm.info)
                it_type = self._match_it_type(scrutinee_type, arm.pattern)
                bound_name = arm.binding or "it"
                bound_symbol = Symbol(name=bound_name, type_name=it_type, kind="var")
                if isinstance(arm.body, BlockStmt):
                    arm_type = self._infer_value_block(arm.body, (bound_symbol,))
                else:
                    # Expression-bodied arms get a synthetic scope so that the
                    # arm-local `it` does not leak; the compiler does not push
                    # a scope here, so suppress implicit-shadow warnings.
                    self._push_scope()
                    self._scopes.enter_synthetic()
                    self.current_scope.define(bound_symbol)
                    try:
                        arm_type = self._infer_expr(arm.body)
                    finally:
                        self._scopes.leave_synthetic()
                        self._pop_scope()
                result_type = self._merge_branch_type(
                    result_type, arm_type, arm.info, "match expression arm types must match"
                )
            self._check_enum_match_exhaustive(scrutinee_type, expr)
            return result_type
        return None

    def _match_it_type(self, scrutinee_type: str | None, pattern: MatchPattern) -> str | None:
        if pattern.kind == "result":
            if pattern.value == "Ok":
                return result_ok_type(scrutinee_type)
            if pattern.value == "Err":
                return result_err_type(scrutinee_type)
        if pattern.kind == "enum" and isinstance(pattern.value, str):
            enum_name, variant_name = pattern.value.split(".", 1)
            payload_type = self._enum_variant_payload(enum_name, variant_name)
            return payload_type if payload_type is not None else scrutinee_type
        if pattern.kind == "type" and isinstance(pattern.value, str):
            return pattern.value
        return scrutinee_type

    def _safe_receiver_type(self, obj_type: str | None) -> str | None:
        base = base_type(obj_type)
        if base in ("R", "Ok"):
            return result_ok_type(obj_type)
        nullable_inner = nullable_inner_type(obj_type)
        if nullable_inner is not None:
            return nullable_inner
        return obj_type

    def _safe_access_type(self, obj_type: str | None, member_type: str | None) -> str | None:
        if member_type in (None, "Function", "PyObject", "PyCallable"):
            return None
        obj_base = base_type(obj_type)
        if obj_type == "Null" or obj_base in ("Nullable", "R", "Err"):
            return nullable_type(member_type)
        return member_type

    def _infer_if_expr(self, expr: IfExpr) -> str | None:
        cond_type = self._infer_expr(expr.condition)
        self._expect_type(cond_type, "Bool", expr.condition.info, "if condition must be Bool")
        then_narrow, else_narrow = self._condition_narrowings(expr.condition)
        result_type = self._infer_value_block(expr.then_branch, narrowings=then_narrow)
        pending_else_narrow = else_narrow
        for elif_cond, elif_body in expr.elif_branches:
            self._push_narrowing(pending_else_narrow)
            try:
                elif_type = self._infer_expr(elif_cond)
                self._expect_type(elif_type, "Bool", elif_cond.info, "elif condition must be Bool")
                elif_then, elif_else = self._condition_narrowings(elif_cond)
            finally:
                self._pop_narrowing()
            arm_type = self._infer_value_block(
                elif_body, narrowings={**pending_else_narrow, **elif_then}
            )
            result_type = self._merge_branch_type(
                result_type, arm_type, elif_body.info, "if expression branch types must match"
            )
            pending_else_narrow = {**pending_else_narrow, **elif_else}
        if expr.else_branch is None:
            self._error("if expression must have an else branch", expr.info)
            return result_type
        else_type = self._infer_value_block(expr.else_branch, narrowings=pending_else_narrow)
        return self._merge_branch_type(
            result_type, else_type, expr.else_branch.info, "if expression branch types must match"
        )

    def _infer_value_block(
        self,
        block: BlockStmt,
        extra_symbols: Sequence[Symbol] = (),
        narrowings: dict[int, str | None] | None = None,
    ) -> str | None:
        self._push_scope()
        self._push_narrowing(narrowings)
        try:
            for sym in extra_symbols:
                self.current_scope.define(sym)
            statements = list(block.statements)
            result_type: str | None = "Null"
            if statements and isinstance(statements[-1], ExprStmt):
                for stmt in statements[:-1]:
                    self._analyze_stmt(stmt)
                result_type = self._infer_expr(statements[-1].expr)
            else:
                for stmt in statements:
                    self._analyze_stmt(stmt)
            return result_type
        finally:
            self._pop_narrowing()
            self._pop_scope()

    def _merge_branch_type(
        self, current: str | None, candidate: str | None, info: TokenInfo, message: str
    ) -> str | None:
        if (
            current is not None
            and candidate is not None
            and self._common_type(current, candidate) is None
        ):
            self._error(f"{message}; expected {current}, got {candidate}", info)
            return current
        return self._common_type(current, candidate)

    def _iter_item_type(self, iterable_type: str | None) -> str | None:
        base = base_type(iterable_type)
        if base == "Range":
            return "Int"
        if base == "Str":
            return "Str"
        if base == "List":
            args = split_type_args(iterable_type)
            return args[0] if args else None
        if base == "Tuple":
            return self._common_sequence_type(split_type_args(iterable_type))
        if iterable_type not in (None, "PyObject", "PyCallable"):
            self._error(f"Cannot iterate over {iterable_type}")
        return None

    def _common_sequence_type(self, types: Sequence[str | None]) -> str | None:
        item_type = None
        for type_name in types:
            item_type = self._common_type(item_type, type_name)
        return item_type

    def _destructure_element_types(
        self, value_type: str | None, target_count: int, info: TokenInfo
    ) -> list[str | None]:
        if base_type(value_type) == "Tuple":
            element_types = split_type_args(value_type)
            if len(element_types) != target_count:
                self._error(
                    f"Cannot destructure {value_type} into {target_count} targets; "
                    f"expected {len(element_types)}",
                    info,
                )
            return [
                *element_types[:target_count],
                *([None] * max(0, target_count - len(element_types))),
            ]
        if base_type(value_type) == "List":
            return [self._iter_item_type(value_type)] * target_count
        item_type = self._iter_item_type(value_type)
        return [item_type] * target_count

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

    def _resolve_decl_type(self, declared: str | None, inferred: str | None) -> str | None:
        if declared == "Any" and inferred is not None:
            return inferred
        return declared or inferred

    def _infer_assignment_target(self, target: Expr) -> str | None:
        if isinstance(target, Identifier):
            sym = self.current_scope.resolve_local(target.name)
            if not sym:
                self._error(
                    f"'{target.name}' is not defined in the current scope; "
                    f"use '{target.name} = ...' to introduce a local or '@{target.name}' "
                    "to modify an outer binding",
                    target.info,
                )
                return None
            return sym.type_name
        if isinstance(target, OuterIdentifier):
            sym = self._resolve_outer(target.name)
            if sym is None:
                self._error(f"Undefined outer name '{target.name}'", target.info)
                return None
            return sym.type_name
        if isinstance(target, MemberExpr):
            obj_type = self._infer_expr(target.obj)
            return self._assignment_member_type(obj_type, target.member, target.info)
        if isinstance(target, IndexExpr):
            obj_type = self._infer_expr(target.obj)
            index_type = self._infer_expr(target.index)
            self._expect_type(index_type, "Int", target.index.info, "index must be Int")
            obj_base = base_type(obj_type)
            if obj_base == "List":
                args = split_type_args(obj_type)
                return args[0] if args else None
            if obj_base not in (None, "Any", "PyObject"):
                self._error(f"Cannot assign through index on {obj_type}", target.info)
            return None
        self._error("Invalid assignment target", target.info)
        return None

    def _infer_binary(self, expr: BinaryExpr) -> str | None:
        left_type = self._infer_expr(expr.left)
        if expr.op == "is":
            if not isinstance(expr.right, Identifier):
                self._error("right operand of 'is' must be a type name", expr.right.info)
            return "Bool"
        right_type = self._infer_expr(expr.right)
        operator_methods = {
            "+": "op_add",
            "-": "op_sub",
            "*": "op_mul",
            "/": "op_div",
            "%": "op_mod",
            "&": "op_bit_and",
            "|": "op_bit_or",
            "^": "op_bit_xor",
            "<<": "op_shl",
            ">>": "op_shr",
            "==": "op_eq",
            "!=": "op_ne",
            ">": "op_gt",
            "<": "op_lt",
            ">=": "op_ge",
            "<=": "op_le",
        }
        method_name = operator_methods.get(expr.op)
        candidates = self._class_method_candidates(left_type, method_name or "")
        if candidates:
            for owner_class, method in candidates:
                self._check_member_access(
                    owner_class, method.is_pub, method_name or "", left_type, expr.info
                )
            fake_call = CallExpr(
                callee=MemberExpr(obj=expr.left, member=method_name or "", info=expr.info),
                args=(expr.right,),
                info=expr.info,
            )
            return self._infer_function_call(
                f"{base_type(left_type)}.{method_name}",
                [method for _, method in candidates],
                fake_call,
            )
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

    def _infer_call(self, expr: CallExpr) -> str | None:
        if isinstance(expr.callee, MemberExpr):
            enum_call_type = self._infer_enum_variant_call(expr.callee, expr)
            if enum_call_type is not None:
                return enum_call_type
            obj_type = self._infer_expr(expr.callee.obj)
            candidates = self._class_method_candidates(obj_type, expr.callee.member)
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, expr.callee.member, obj_type, expr.info
                    )
                return self._infer_function_call(
                    f"{base_type(obj_type)}.{expr.callee.member}",
                    [method for _, method in candidates],
                    expr,
                )
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
            if name == "List":
                elem_type = None
                for arg in expr.args:
                    elem_type = self._common_type(elem_type, self._infer_expr(arg))
                return f"List<{elem_type}>" if elem_type else "List"
            if name in self.BUILTINS:
                _, return_type, arity = self.BUILTINS[name]
                self._check_arity(name, len(expr.args), arity, expr.info)
                arg_types = [self._infer_expr(arg) for arg in expr.args]
                if name == "Ok":
                    ok_type = arg_types[0] if arg_types else None
                    return f"Ok<{ok_type}>" if ok_type else "Ok"
                if name == "Err":
                    err_type = arg_types[0] if arg_types else None
                    return f"Err<{err_type}>" if err_type else "Err"
                if name == "unwrap":
                    if arg_types and base_type(arg_types[0]) not in (None, "R", "Ok", "Err"):
                        self._error("'unwrap' expects a Result value", expr.args[0].info)
                    return result_ok_type(arg_types[0] if arg_types else None)
                if name == "unwrap_or":
                    result_type = arg_types[0] if arg_types else None
                    default_type = arg_types[1] if len(arg_types) > 1 else None
                    if base_type(result_type) not in (None, "R", "Ok", "Err"):
                        self._error("'unwrap_or' expects a Result value", expr.args[0].info)
                    ok_type = result_ok_type(result_type)
                    if ok_type is not None and default_type is not None:
                        self._check_assignable(
                            ok_type,
                            default_type,
                            expr.args[1].info,
                            f"'unwrap_or' default expects {ok_type}, got {default_type}",
                        )
                    return self._common_type(ok_type, default_type)
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
                return self._infer_constructor_call(name, expr)
            if sym.kind == "func":
                if (
                    self.current_class is not None
                    and name in self._class_method_overloads.get(self.current_class, {})
                    and sym is not self.global_scope.resolve_local(name)
                ):
                    self._error(
                        f"Method '{name}' must be called through 'this.{name}(...)'",
                        expr.info,
                    )
                    for arg in expr.args:
                        self._infer_expr(arg)
                    return None
                overloads = self._function_overloads.get(name)
                if overloads:
                    return self._infer_function_call(name, overloads, expr)
                if isinstance(sym.decl, FunctionDecl):
                    return self._infer_function_call(name, [sym.decl], expr)
        callee_type = self._infer_expr(expr.callee)
        arg_types = [self._infer_expr(arg) for arg in expr.args]
        if base_type(callee_type) == "Function":
            return self._infer_function_value_call(callee_type, arg_types, expr)
        if callee_type not in (None, "Function", "PyObject", "PyCallable"):
            self._error(f"Cannot call value of type {callee_type}", expr.info)
        return None

    def _infer_function_value_call(
        self, callee_type: str | None, arg_types: Sequence[str | None], expr: CallExpr
    ) -> str | None:
        expected_arg_types = function_arg_types(callee_type)
        return_type = function_return_type(callee_type)
        if not expected_arg_types and return_type is None:
            return None
        if len(arg_types) != len(expected_arg_types):
            self._error(
                f"Function value expects {len(expected_arg_types)} args, got {len(arg_types)}",
                expr.info,
            )
            return return_type
        for arg, expected, actual in zip(expr.args, expected_arg_types, arg_types, strict=False):
            self._check_assignable(
                expected,
                actual,
                arg.info,
                f"Function value argument expects {expected}, got {actual}",
            )
        return return_type

    def _check_function_call(
        self,
        func: FunctionDecl,
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        bindings = dict(initial_mapping or {})
        required = sum(1 for param in func.params if param.default is None)
        if len(expr.args) < required or len(expr.args) > len(func.params):
            self._error(
                f"Function '{func.name}' expects {required}-{len(func.params)} args, got {len(expr.args)}",
                expr.info,
            )
        for arg, param in zip(expr.args, func.params, strict=False):
            arg_type = self._infer_expr(arg)
            expected = substitute_type(param.type_annotation, bindings)
            if not self._match_type_pattern(expected, arg_type, func.type_params, bindings):
                self._error(f"Argument '{param.name}' expects {expected}, got {arg_type}", arg.info)
                continue
            expected = substitute_type(param.type_annotation, bindings)
            if expected != "Any":
                self._check_assignable(
                    expected,
                    arg_type,
                    arg.info,
                    f"Argument '{param.name}' expects {expected}, got {arg_type}",
                )
        return bindings

    def _infer_constructor_call(self, class_name: str, expr: CallExpr) -> str | None:
        cls = self._class_decls.get(class_name)
        init_overloads = self._class_method_overloads.get(class_name, {}).get("init")
        if init_overloads and cls and cls.type_params:
            init_overloads = [
                replace(init, type_params=tuple(cls.type_params) + tuple(init.type_params))
                for init in init_overloads
            ]
        mapping: dict[str, str | None] = {}
        selected = None
        if init_overloads:
            selected, mapping, _ = self._resolve_overload(
                f"{class_name}.init", init_overloads, expr
            )
        else:
            if expr.args:
                self._error(
                    f"Class '{class_name}' constructor expects 0 args, got {len(expr.args)}",
                    expr.info,
                )
            for arg in expr.args:
                self._infer_expr(arg)
        if selected is not None:
            for type_param in cls.type_params if cls else ():
                mapping.setdefault(type_param, None)
        if cls and cls.type_params:
            args = [mapping.get(type_param) or "Any" for type_param in cls.type_params]
            return f"{class_name}<{','.join(args)}>"
        return class_name

    def _enum_variant_payload(self, enum_name: str, variant_name: str) -> str | None:
        return self._enum_variants.get(enum_name, {}).get(variant_name)

    def _enum_variant_exists(self, enum_name: str, variant_name: str) -> bool:
        return variant_name in self._enum_variants.get(enum_name, {})

    def _enum_variant_tag(self, member: MemberExpr) -> tuple[str, str] | None:
        if not isinstance(member.obj, Identifier):
            return None
        enum_name = member.obj.name
        sym = self.current_scope.resolve(enum_name)
        if sym is None or sym.kind != "enum" or enum_name not in self._enum_decls:
            return None
        return enum_name, member.member

    def _infer_enum_member_expr(self, expr: MemberExpr) -> str | None:
        tag = self._enum_variant_tag(expr)
        if tag is None:
            return None
        enum_name, variant_name = tag
        if not self._enum_variant_exists(enum_name, variant_name):
            self._error(f"Enum '{enum_name}' has no variant '{variant_name}'", expr.info)
            return enum_name
        payload_type = self._enum_variant_payload(enum_name, variant_name)
        if payload_type is not None:
            self._error(
                f"Enum variant '{enum_name}.{variant_name}' expects 1 payload argument",
                expr.info,
            )
        return enum_name

    def _infer_enum_variant_call(self, callee: MemberExpr, expr: CallExpr) -> str | None:
        tag = self._enum_variant_tag(callee)
        if tag is None:
            return None
        enum_name, variant_name = tag
        if not self._enum_variant_exists(enum_name, variant_name):
            self._error(f"Enum '{enum_name}' has no variant '{variant_name}'", callee.info)
            for arg in expr.args:
                self._infer_expr(arg)
            return enum_name
        payload_type = self._enum_variant_payload(enum_name, variant_name)
        if payload_type is None:
            if expr.args:
                self._error(
                    f"Enum variant '{enum_name}.{variant_name}' expects 0 args, got {len(expr.args)}",
                    expr.info,
                )
            for arg in expr.args:
                self._infer_expr(arg)
            return enum_name
        if len(expr.args) != 1:
            self._error(
                f"Enum variant '{enum_name}.{variant_name}' expects 1 arg, got {len(expr.args)}",
                expr.info,
            )
        for arg in expr.args:
            arg_type = self._infer_expr(arg)
            self._check_assignable(
                payload_type,
                arg_type,
                arg.info,
                f"Enum variant '{enum_name}.{variant_name}' payload expects {payload_type}, got {arg_type}",
            )
        return enum_name

    def _check_enum_pattern(
        self, scrutinee_type: str | None, pattern: MatchPattern, info: TokenInfo
    ) -> None:
        if not isinstance(pattern.value, str) or "." not in pattern.value:
            self._error("Enum match pattern must be Enum.Variant", info)
            return
        enum_name, variant_name = pattern.value.split(".", 1)
        if enum_name not in self._enum_variants:
            self._error(f"Unknown enum '{enum_name}' in match pattern", info)
            return
        if not self._enum_variant_exists(enum_name, variant_name):
            self._error(f"Enum '{enum_name}' has no variant '{variant_name}'", info)
            return
        if scrutinee_type is not None and not self._is_assignable(enum_name, scrutinee_type):
            self._error(
                f"Enum pattern '{enum_name}.{variant_name}' cannot match {scrutinee_type}",
                info,
            )

    def _check_enum_match_exhaustive(
        self, scrutinee_type: str | None, expr: PatternMatchExpr
    ) -> None:
        enum_name = base_type(scrutinee_type)
        if enum_name not in self._enum_variants:
            return
        if any(arm.pattern.kind == "wildcard" for arm in expr.arms):
            return
        variants = self._enum_variants[enum_name]
        covered: set[str] = set()
        for arm in expr.arms:
            pattern = arm.pattern
            if pattern.kind != "enum" or not isinstance(pattern.value, str):
                continue
            pattern_enum, _, variant_name = pattern.value.partition(".")
            if pattern_enum == enum_name and variant_name in variants:
                covered.add(variant_name)
        missing = [variant for variant in variants if variant not in covered]
        if missing:
            formatted = ", ".join(f"{enum_name}.{variant}" for variant in missing)
            self._error(
                f"Non-exhaustive match for enum '{enum_name}'; missing variants: {formatted}",
                expr.info,
            )

    def _check_arity(self, name: str, got: int, arity: int, info: TokenInfo) -> None:
        if arity >= 0 and got != arity:
            self._error(f"Function '{name}' expects {arity} args, got {got}", info)

    def _member_type(self, obj_type: str | None, member: str, info: TokenInfo) -> str | None:
        if obj_type is None:
            return None
        base = base_type(obj_type)
        if base in ("PyModule", "PyObject", "PyCallable"):
            return "PyObject"
        if base == "Str":
            if member == "size":
                return "Int"
            self._error(f"No member '{member}' on Str", info)
            return None
        if base == "List":
            if member == "size":
                return "Int"
            if member == "add":
                return "Function"
            self._error(f"No member '{member}' on List", info)
            return None
        if base == "Tuple":
            if member == "size":
                return "Int"
            self._error(f"No member '{member}' on Tuple", info)
            return None
        if base == "Range":
            if member in ("size", "start", "end"):
                return "Int"
            if member == "inclusive":
                return "Bool"
            self._error(f"No member '{member}' on Range", info)
            return None
        if base == "R":
            if member == "value":
                return None
            return None
        if base in self._enum_decls:
            if member == "value":
                value_type = self._common_sequence_type(
                    [
                        payload_type
                        for payload_type in self._enum_variants.get(base, {}).values()
                        if payload_type is not None
                    ]
                )
                if value_type is None:
                    self._error(f"Enum '{base}' has no payload values", info)
                    return ERROR_TYPE
                if any(
                    payload_type is None
                    for payload_type in self._enum_variants.get(base, {}).values()
                ):
                    return nullable_type(value_type)
                return value_type
            if member in ("variant", "enum"):
                return "Str"
            self._error(f"No member '{member}' on {obj_type}", info)
            return None
        if base == "Nullable":
            self._error(f"Cannot access member '{member}' on nullable {obj_type}; use '?.'", info)
            return None
        getter_candidate = self._class_getter_candidate(obj_type, member)
        if getter_candidate is not None:
            owner_class, getter = getter_candidate
            self._check_member_access(owner_class, getter.is_pub, member, obj_type, info)
            return getter.return_type
        field_candidate = self._class_field_candidate(obj_type, member)
        if field_candidate is not None:
            owner_class, field = field_candidate
            self._check_member_access(owner_class, field.is_pub, member, obj_type, info)
            return substitute_type(
                self._class_field_types.get(owner_class, {}).get(member),
                self._class_type_mapping_for(obj_type, owner_class),
            )
        method_candidates = self._class_method_candidates(obj_type, member)
        if method_candidates:
            for owner_class, method in method_candidates:
                self._check_member_access(owner_class, method.is_pub, member, obj_type, info)
            return "Function"
        if base in self._class_decls:
            self._error(f"No member '{member}' on {obj_type}", info)
        return None

    def _assignment_member_type(
        self, obj_type: str | None, member: str, info: TokenInfo
    ) -> str | None:
        setter_candidate = self._class_setter_candidate(obj_type, member)
        if setter_candidate is not None:
            owner_class, setter = setter_candidate
            self._check_member_access(owner_class, setter.is_pub, member, obj_type, info)
            if setter.params:
                return setter.params[0].type_annotation
            return None
        return self._member_type(obj_type, member, info)

    def _can_access_member(self, class_name: str, is_pub: bool) -> bool:
        return is_pub or self.current_class == class_name

    def _check_member_access(
        self, class_name: str, is_pub: bool, member: str, obj_type: str | None, info: TokenInfo
    ) -> None:
        if not self._can_access_member(class_name, is_pub):
            self._error(f"Cannot access private member '{member}' on {obj_type}", info)

    def _check_binary_operands(
        self, op: str, left: str | None, right: str | None, info: TokenInfo
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

    def _expect_numeric(self, actual: str | None, info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable", "Int", "Float"):
            return
        if is_error_type(actual):
            return
        self._error(f"{msg}, got {actual}", info)

    def _expect_type(self, actual: str | None, expected: str, info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable"):
            return
        if is_error_type(actual):
            return
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}, got {actual}", info)

    def _check_assignable(
        self, expected: str | None, actual: str | None, info: TokenInfo, msg: str
    ) -> None:
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}; expected {expected}", info)

    def _is_assignable(self, expected: str | None, actual: str | None) -> bool:
        cache_key = (expected, actual)
        if cache_key in self._assignable_cache:
            return self._assignable_cache[cache_key]
        result = self._is_assignable_uncached(expected, actual)
        self._assignable_cache[cache_key] = result
        return result

    def _is_assignable_uncached(self, expected: str | None, actual: str | None) -> bool:
        if expected is None or actual is None:
            return True
        if is_error_type(expected) or is_error_type(actual):
            return False
        if expected == "Any" or actual in ("PyObject", "PyCallable"):
            return True
        if expected == actual:
            return True
        if expected == "Float" and actual == "Int":
            return True
        expected_base = base_type(expected)
        actual_base = base_type(actual)
        if expected_base == "Nullable":
            expected_inner = nullable_inner_type(expected)
            if actual == "Null":
                return True
            if actual_base == "Nullable":
                actual_inner = nullable_inner_type(actual)
                return self._is_assignable(expected_inner, actual_inner)
            return self._is_assignable(expected_inner, actual)
        if actual_base == "Nullable":
            return False
        if expected_base == "Tuple" and actual_base == "Tuple":
            expected_args = split_type_args(expected)
            actual_args = split_type_args(actual)
            if not expected_args or not actual_args:
                return True
            if len(expected_args) != len(actual_args):
                return False
            return all(
                self._is_assignable(exp, act)
                for exp, act in zip(expected_args, actual_args, strict=False)
            )
        if expected_base == "Function" and actual_base == "Function":
            expected_args = split_type_args(expected)
            actual_args = split_type_args(actual)
            if not expected_args or not actual_args:
                return True
            if len(expected_args) != len(actual_args):
                return False
            return all(
                self._is_assignable(exp, act)
                for exp, act in zip(expected_args, actual_args, strict=False)
            )
        if expected_base == "R":
            expected_args = split_type_args(expected)
            if actual_base == "R":
                actual_args = split_type_args(actual)
                if not expected_args or not actual_args:
                    return True
                if len(expected_args) != len(actual_args):
                    return False
                return all(
                    self._is_assignable(exp, act)
                    for exp, act in zip(expected_args, actual_args, strict=False)
                )
            if actual_base == "Ok":
                ok_type = result_ok_type(actual)
                if not expected_args:
                    return True
                if len(expected_args) == 1:
                    return self._is_assignable(expected_args[0], ok_type)
                if len(expected_args) >= 2:
                    return self._is_assignable(expected_args[0], ok_type)
            if actual_base == "Err":
                err_type = result_err_type(actual)
                if not expected_args:
                    return True
                if len(expected_args) == 1:
                    return self._is_assignable(expected_args[0], err_type)
                if len(expected_args) >= 2:
                    return self._is_assignable(expected_args[1], err_type)
            return False
        if expected_base == actual_base:
            expected_args = split_type_args(expected)
            actual_args = split_type_args(actual)
            if not expected_args or not actual_args:
                return True
            return expected_args == actual_args
        projected_actual = self._project_type_to_base(actual, expected_base)
        if projected_actual is not None:
            expected_args = split_type_args(expected)
            actual_args = split_type_args(projected_actual)
            if not expected_args or not actual_args:
                return True
            return expected_args == actual_args
        return False

    def _common_type(self, left: str | None, right: str | None) -> str | None:
        if left is None:
            return right
        if right is None:
            return left
        if base_type(left) == "Tuple" and base_type(right) == "Tuple":
            left_args = split_type_args(left)
            right_args = split_type_args(right)
            if len(left_args) != len(right_args):
                return None
            merged = [
                self._common_type(left_item, right_item)
                for left_item, right_item in zip(left_args, right_args, strict=False)
            ]
            if any(item is None for item in merged):
                return None
            return f"Tuple<{','.join(item for item in merged if item is not None)}>"
        if left == "Null":
            return nullable_type(right)
        if right == "Null":
            return nullable_type(left)
        if self._is_assignable(left, right):
            return left
        if self._is_assignable(right, left):
            return right
        return None

    def _match_type_pattern(
        self,
        expected: str | None,
        actual: str | None,
        type_params: Sequence[str],
        bindings: dict[str, str | None],
    ) -> bool:
        if expected is None or expected == "Any" or actual is None:
            return True
        if expected in type_params:
            bound = bindings.get(expected)
            if bound is None:
                bindings[expected] = actual
                return True
            return self._is_assignable(bound, actual) or self._is_assignable(actual, bound)
        expected_base = base_type(expected)
        actual_base = base_type(actual)
        if expected_base != actual_base:
            return self._is_assignable(expected, actual)
        expected_args = split_type_args(expected)
        actual_args = split_type_args(actual)
        if not expected_args:
            return self._is_assignable(expected, actual)
        if not actual_args:
            return True
        if len(expected_args) != len(actual_args):
            return False
        return all(
            self._match_type_pattern(exp, act, type_params, bindings)
            for exp, act in zip(expected_args, actual_args, strict=False)
        )

    def _overload_score(
        self,
        func: FunctionDecl,
        arg_types: Sequence[str | None],
        initial_mapping: dict[str, str | None] | None = None,
    ) -> tuple[int, dict[str, str | None]] | None:
        required = sum(1 for param in func.params if param.default is None)
        if len(arg_types) < required or len(arg_types) > len(func.params):
            return None
        bindings = dict(initial_mapping or {})
        score = 0
        for arg_type, param in zip(arg_types, func.params, strict=False):
            expected = substitute_type(param.type_annotation, bindings)
            if not self._match_type_pattern(expected, arg_type, func.type_params, bindings):
                return None
            expected_after = substitute_type(param.type_annotation, bindings)
            if expected_after == arg_type:
                score += 4
            elif erase_type(expected_after) == erase_type(arg_type):
                score += 3
            elif self._is_assignable(expected_after, arg_type):
                score += 2
            else:
                score += 1
        return score, bindings

    def _resolve_overload(
        self,
        name: str,
        funcs: Sequence[FunctionDecl],
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> tuple[FunctionDecl | None, dict[str, str | None], list[str | None]]:
        arg_types = [self._infer_expr(arg) for arg in expr.args]
        matches: list[tuple[int, FunctionDecl, dict[str, str | None]]] = []
        for func in funcs:
            scored = self._overload_score(func, arg_types, initial_mapping)
            if scored is not None:
                score, bindings = scored
                matches.append((score, func, bindings))
        if not matches:
            self._error(f"No overload of '{name}' matches argument types {arg_types}", expr.info)
            return None, {}, arg_types
        matches.sort(key=lambda item: item[0], reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            self._error(f"Ambiguous overload of '{name}' for argument types {arg_types}", expr.info)
            return None, {}, arg_types
        return matches[0][1], matches[0][2], arg_types

    def _infer_function_call(
        self,
        name: str,
        funcs: Sequence[FunctionDecl],
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> str | None:
        if len(funcs) > 1:
            selected, bindings, _ = self._resolve_overload(name, funcs, expr, initial_mapping)
            if selected is None:
                return None
            return substitute_type(selected.return_type, bindings)
        bindings = self._check_function_call(funcs[0], expr, initial_mapping)
        return substitute_type(funcs[0].return_type, bindings)
