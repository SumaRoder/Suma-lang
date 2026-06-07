"""Expression-precedence parsing methods.

This is a mixin used by :class:`suma_lang.frontend.parser.parser.Parser`. It
holds the recursive-descent precedence ladder for expressions
(``_parse_expression`` through ``_parse_postfix`` plus the call/index/member
helpers) so that the core ``Parser`` class can focus on declarations,
statements, and primary expressions.

The mixin assumes the host class provides the token-stream helpers
``_at``, ``_advance``, ``_match``, ``_cur``, ``_peek``, ``_literal``,
``_expect``, ``_error`` and the ``_parse_primary`` entry point. Splitting these
out is a presentation concern — the parser is still a single logical recursive
descent.
"""

from __future__ import annotations

from typing import NoReturn

from suma_lang.frontend.lexer.token_types import Token, TokenType
from suma_lang.frontend.parser.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    CompoundAssignExpr,
    ElvExpr,
    Expr,
    IncrementExpr,
    IndexExpr,
    MemberExpr,
    NullCoalesceExpr,
    PropagateExpr,
    RangeExpr,
    SafeCallExpr,
    SafeMemberExpr,
    SliceExpr,
    UnaryExpr,
)


class _ExpressionsMixin:
    """Recursive-descent expression parsing, layered by operator precedence.

    Inherited by ``Parser``. Methods here reference helper methods
    (``_advance``, ``_match``, …) and ``_parse_primary`` that live on the host
    class; the resolution happens via normal method lookup on ``self``.
    """

    def _cur(self) -> Token:
        raise NotImplementedError

    def _peek(self, offset: int = 0) -> Token:
        raise NotImplementedError

    def _at(self, *types: TokenType) -> bool:
        raise NotImplementedError

    def _advance(self) -> Token:
        raise NotImplementedError

    def _expect(self, tt: TokenType) -> Token:
        raise NotImplementedError

    def _error(self, msg: str) -> NoReturn:
        raise NotImplementedError

    def _literal(self, tok: Token) -> str:
        raise NotImplementedError

    def _match(self, *types: TokenType) -> Token | None:
        raise NotImplementedError

    def _parse_primary(self) -> Expr:
        raise NotImplementedError

    def _parse_expression(self, *, allow_result_else: bool = True) -> Expr:
        return self._parse_assignment(allow_result_else=allow_result_else)

    def _parse_assignment(self, *, allow_result_else: bool = True) -> Expr:
        left = self._parse_range(allow_result_else=allow_result_else)
        if self._at(TokenType.ASSIGN):
            info = self._advance().info
            right = self._parse_assignment(allow_result_else=allow_result_else)
            return AssignExpr(target=left, value=right, info=info)
        for op_tt, op_str in [
            (TokenType.ADD_ASSIGN, "+="),
            (TokenType.MINUS_ASSIGN, "-="),
            (TokenType.MULT_ASSIGN, "*="),
            (TokenType.DIV_ASSIGN, "/="),
            (TokenType.REM_ASSIGN, "%="),
        ]:
            if self._at(op_tt):
                info = self._advance().info
                right = self._parse_assignment(allow_result_else=allow_result_else)
                return CompoundAssignExpr(op=op_str, target=left, value=right, info=info)
        return left

    def _parse_elvis(self, *, allow_result_else: bool = True) -> Expr:
        left = self._parse_or()
        if allow_result_else and self._match(TokenType.ELSE):
            right = self._parse_elvis(allow_result_else=allow_result_else)
            return ElvExpr(left=left, right=right, info=left.info)
        if self._match(TokenType.NULL_COALESCE):
            right = self._parse_elvis(allow_result_else=allow_result_else)
            return NullCoalesceExpr(left=left, right=right, info=left.info)
        return left

    def _parse_range(self, *, allow_result_else: bool = True) -> Expr:
        left = self._parse_elvis(allow_result_else=allow_result_else)
        if self._at(TokenType.RANGE, TokenType.RANGE_INCLUSIVE):
            inclusive = self._cur().type == TokenType.RANGE_INCLUSIVE
            info = self._advance().info
            right = self._parse_elvis(allow_result_else=allow_result_else)
            return RangeExpr(start=left, end=right, inclusive=inclusive, info=info)
        return left

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._match(TokenType.ORL):
            right = self._parse_and()
            left = BinaryExpr(op="||", left=left, right=right, info=left.info)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_bit_or()
        while self._match(TokenType.ANDL):
            right = self._parse_bit_or()
            left = BinaryExpr(op="&&", left=left, right=right, info=left.info)
        return left

    def _parse_bit_or(self) -> Expr:
        left = self._parse_bit_xor()
        while self._match(TokenType.ORB):
            right = self._parse_bit_xor()
            left = BinaryExpr(op="|", left=left, right=right, info=left.info)
        return left

    def _parse_bit_xor(self) -> Expr:
        left = self._parse_bit_and()
        while self._match(TokenType.XOR):
            right = self._parse_bit_and()
            left = BinaryExpr(op="^", left=left, right=right, info=left.info)
        return left

    def _parse_bit_and(self) -> Expr:
        left = self._parse_equality()
        while self._match(TokenType.ANDB):
            right = self._parse_equality()
            left = BinaryExpr(op="&", left=left, right=right, info=left.info)
        return left

    def _parse_equality(self) -> Expr:
        left = self._parse_comparison()
        while True:
            if self._match(TokenType.EQ):
                right = self._parse_comparison()
                left = BinaryExpr(op="==", left=left, right=right, info=left.info)
            elif self._match(TokenType.NE):
                right = self._parse_comparison()
                left = BinaryExpr(op="!=", left=left, right=right, info=left.info)
            else:
                break
        return left

    def _parse_comparison(self) -> Expr:
        left = self._parse_shift()
        while True:
            if self._match(TokenType.GT):
                right = self._parse_shift()
                left = BinaryExpr(op=">", left=left, right=right, info=left.info)
            elif self._match(TokenType.LT):
                right = self._parse_shift()
                left = BinaryExpr(op="<", left=left, right=right, info=left.info)
            elif self._match(TokenType.GE):
                right = self._parse_shift()
                left = BinaryExpr(op=">=", left=left, right=right, info=left.info)
            elif self._match(TokenType.LE):
                right = self._parse_shift()
                left = BinaryExpr(op="<=", left=left, right=right, info=left.info)
            elif self._match(TokenType.IS):
                right = self._parse_shift()
                left = BinaryExpr(op="is", left=left, right=right, info=left.info)
            else:
                break
        return left

    def _parse_shift(self) -> Expr:
        left = self._parse_additive()
        while True:
            if self._match(TokenType.SHIFTL):
                right = self._parse_additive()
                left = BinaryExpr(op="<<", left=left, right=right, info=left.info)
            elif self._match(TokenType.SHIFTR):
                right = self._parse_additive()
                left = BinaryExpr(op=">>", left=left, right=right, info=left.info)
            else:
                break
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while True:
            if self._match(TokenType.ADD):
                right = self._parse_multiplicative()
                left = BinaryExpr(op="+", left=left, right=right, info=left.info)
            elif self._match(TokenType.MINUS):
                right = self._parse_multiplicative()
                left = BinaryExpr(op="-", left=left, right=right, info=left.info)
            else:
                break
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while True:
            if self._match(TokenType.MULT):
                right = self._parse_unary()
                left = BinaryExpr(op="*", left=left, right=right, info=left.info)
            elif self._match(TokenType.DIV):
                right = self._parse_unary()
                left = BinaryExpr(op="/", left=left, right=right, info=left.info)
            elif self._match(TokenType.REM):
                right = self._parse_unary()
                left = BinaryExpr(op="%", left=left, right=right, info=left.info)
            else:
                break
        return left

    def _parse_unary(self) -> Expr:
        if self._at(TokenType.PLUSPLUS, TokenType.MINUSMINUS):
            token = self._advance()
            target = self._parse_unary()
            delta = 1 if token.type == TokenType.PLUSPLUS else -1
            return IncrementExpr(
                target=target,
                delta=delta,
                info=token.info,
            )
        if self._at(TokenType.NOTL):
            info = self._advance().info
            operand = self._parse_unary()
            return UnaryExpr(op="!", operand=operand, info=info)
        if self._at(TokenType.MINUS):
            info = self._advance().info
            operand = self._parse_unary()
            return UnaryExpr(op="-", operand=operand, info=info)
        if self._at(TokenType.NOTB):
            info = self._advance().info
            operand = self._parse_unary()
            return UnaryExpr(op="~", operand=operand, info=info)
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._at(TokenType.LPAR):
                expr = self._parse_call(expr)
            elif self._at(TokenType.LBRACK):
                expr = self._parse_index(expr)
            elif self._at(TokenType.DOT):
                expr = self._parse_member(expr)
            elif self._at(TokenType.QUEST) and self._peek(1).type == TokenType.DOT:
                self._advance()
                self._advance()
                member = self._literal(self._expect(TokenType.ID))
                args: list[Expr] = []
                has_call = False
                if self._at(TokenType.LPAR):
                    has_call = True
                    self._advance()
                    if not self._at(TokenType.RPAR):
                        args.append(self._parse_expression())
                        while self._match(TokenType.COMMA):
                            args.append(self._parse_expression())
                    self._expect(TokenType.RPAR)
                expr = (
                    SafeCallExpr(obj=expr, member=member, args=args, info=expr.info)
                    if has_call
                    else SafeMemberExpr(obj=expr, member=member, info=expr.info)
                )
            elif self._at(TokenType.QUEST) and self._peek(1).type != TokenType.COLON:
                info = self._advance().info
                expr = PropagateExpr(value=expr, info=info)
            elif self._at(TokenType.PLUSPLUS, TokenType.MINUSMINUS) and not isinstance(
                expr, IncrementExpr
            ):
                token = self._advance()
                delta = 1 if token.type == TokenType.PLUSPLUS else -1
                expr = IncrementExpr(
                    target=expr,
                    delta=delta,
                    info=token.info,
                )
            else:
                break
        return expr

    def _parse_call(self, callee: Expr) -> CallExpr:
        self._expect(TokenType.LPAR)
        args: list[Expr] = []
        if not self._at(TokenType.RPAR):
            args.append(self._parse_expression())
            while self._match(TokenType.COMMA):
                args.append(self._parse_expression())
        self._expect(TokenType.RPAR)
        return CallExpr(callee=callee, args=args, info=callee.info)

    def _parse_index(self, obj: Expr) -> IndexExpr | SliceExpr:
        info = self._cur().info
        self._expect(TokenType.LBRACK)
        # slice: [:end] or [start:] or [start:end]
        start = None
        end = None
        if not self._at(TokenType.COLON):
            start = self._parse_expression()
        if self._match(TokenType.COLON):
            if not self._at(TokenType.RBRACK):
                end = self._parse_expression()
            self._expect(TokenType.RBRACK)
            return SliceExpr(obj=obj, start=start, end=end, info=info)
        self._expect(TokenType.RBRACK)
        if start is None:
            self._error("Expected index expression")
        return IndexExpr(obj=obj, index=start, info=info)

    def _parse_member(self, obj: Expr) -> MemberExpr:
        self._expect(TokenType.DOT)
        member = self._literal(self._expect(TokenType.ID))
        return MemberExpr(obj=obj, member=member, info=obj.info)
