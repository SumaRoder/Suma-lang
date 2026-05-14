from __future__ import annotations

from typing import NoReturn, Optional, Sequence

from src.frontend.lexer.token_types import Token, TokenInfo, TokenType
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
    ElvExpr,
    ErrExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    FunctionDecl,
    GetterDecl,
    Identifier,
    IfStmt,
    ImportDecl,
    IndexExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MatchArm,
    MatchPattern,
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


class ParseError(SyntaxError):
    pass


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _cur(self) -> Token:
        return self._tokens[self._pos]

    def _peek(self, offset: int = 0) -> Token:
        p = self._pos + offset
        return self._tokens[p] if p < len(self._tokens) else self._tokens[-1]

    def _at(self, *types: TokenType) -> bool:
        return self._cur().type in types

    def _advance(self) -> Token:
        tok = self._cur()
        if tok.type != TokenType.EOF:
            self._pos += 1
        return tok

    def _expect(self, tt: TokenType) -> Token:
        tok = self._cur()
        if tok.type != tt:
            self._error(f"Expected {tt.value}, got {tok.type.value}")
        return self._advance()

    def _error(self, msg: str) -> NoReturn:
        tok = self._cur()
        loc = f"{tok.info.file or '<unknown>'}:{tok.info.line}:{tok.info.column}"
        raise ParseError(f"[ParseError] {loc} — {msg}")

    def _literal(self, tok: Token) -> str:
        if tok.literal is None:
            self._error(f"Expected literal for {tok.type.value}")
        return tok.literal

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._at(*types):
            return self._advance()
        return None

    def _is_lambda_ahead(self) -> bool:
        """Lookahead to check if 'fn' at current position starts a lambda definition."""
        pos = self._pos
        if pos + 1 >= len(self._tokens) or self._tokens[pos + 1].type != TokenType.LPAR:
            return False
        depth = 0
        i = pos + 1
        has_type_annotation = False
        while i < len(self._tokens):
            t = self._tokens[i]
            if t.type == TokenType.LPAR:
                depth += 1
            elif t.type == TokenType.RPAR:
                depth -= 1
                if depth == 0:
                    if i + 1 < len(self._tokens):
                        next_tok = self._tokens[i + 1]
                        if next_tok.type in (TokenType.LBRA, TokenType.COLON):
                            return True
                        if has_type_annotation:
                            return True
                    return False
            elif t.type == TokenType.COLON and depth == 1:
                has_type_annotation = True
            i += 1
        return False

    @staticmethod
    def parse(tokens: list[Token]) -> Program:
        p = Parser(tokens)
        decls: list[TopLevel] = []
        while not p._at(TokenType.EOF):
            decls.append(p._parse_top_level())
        return Program(declarations=decls)

    def _parse_top_level(self) -> TopLevel:
        decorators = self._parse_decorators()

        is_pub = False
        is_const = False
        if self._match(TokenType.PUBLIC):
            is_pub = True
        else:
            self._match(TokenType.PRIVATE)

        if self._at(TokenType.IMPORT):
            if decorators:
                self._error("Decorators can only be applied to functions")
            return self._parse_import()

        if self._match(TokenType.CONST):
            is_const = True

        if self._at(TokenType.ID) and self._peek(1).type == TokenType.LBRA:
            if decorators:
                self._error("Decorators can only be applied to functions")
            name_tok = self._advance()
            return self._parse_class(self._literal(name_tok), is_pub, name_tok.info)

        return self._parse_func_or_var(is_pub, is_const, decorators)

    def _parse_decorators(self) -> list[Decorator]:
        decorators: list[Decorator] = []
        while self._match(TokenType.AT):
            info = self._tokens[self._pos - 1].info
            expr = self._parse_expression()
            self._match(TokenType.SEM)
            decorators.append(Decorator(expr=expr, info=info))
        return decorators

    def _parse_import(self) -> ImportDecl:
        info = self._cur().info
        self._expect(TokenType.IMPORT)
        path_tok = self._expect(TokenType.STRING)
        self._match(TokenType.SEM)
        return ImportDecl(path=self._literal(path_tok), info=info)

    def _parse_class(self, name: str, is_pub: bool, info: TokenInfo) -> ClassDecl:
        self._expect(TokenType.LBRA)
        members: list[FunctionDecl | VarDecl | GetterDecl | SetterDecl] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            members.append(self._parse_class_member())
        self._expect(TokenType.RBRA)
        return ClassDecl(name=name, members=members, is_pub=is_pub, info=info)

    def _parse_class_member(self) -> FunctionDecl | VarDecl | GetterDecl | SetterDecl:
        decorators = self._parse_decorators()

        is_pub = False
        is_static = False
        if self._match(TokenType.PUBLIC):
            is_pub = True
        else:
            self._match(TokenType.PRIVATE)

        if self._match(TokenType.STATIC):
            is_static = True

        if self._at(TokenType.INIT):
            if decorators:
                self._error("Decorators cannot be applied to init")
            return self._parse_init(is_pub)

        if self._at(TokenType.GETTER):
            if decorators:
                self._error("Decorators cannot be applied to getters")
            return self._parse_getter(is_pub)
        if self._at(TokenType.SETTER):
            if decorators:
                self._error("Decorators cannot be applied to setters")
            return self._parse_setter(is_pub)

        if self._at(TokenType.ID) and self._peek(1).type == TokenType.COLON:
            if decorators:
                self._error("Decorators can only be applied to functions")
            var = self._parse_var_decl(is_pub, False)
            if self._match(TokenType.DOT):
                if self._at(TokenType.GETTER):
                    return self._parse_getter_after_var(var)
                elif self._at(TokenType.SETTER):
                    return self._parse_setter_after_var(var)
            return var

        if decorators:
            self._error("Decorators on class methods are not supported yet")
        return self._parse_function_decl(is_pub, is_static, decorators)

    def _parse_init(self, is_pub: bool) -> FunctionDecl:
        info = self._cur().info
        self._expect(TokenType.INIT)
        params = self._parse_params()
        body = self._parse_block()
        return FunctionDecl(
            name="init",
            params=params,
            return_type=None,
            body=body,
            is_pub=is_pub,
            is_static=False,
            info=info,
        )

    def _parse_getter(self, is_pub: bool) -> GetterDecl:
        info = self._cur().info
        self._expect(TokenType.GETTER)
        name = self._literal(self._expect(TokenType.ID))
        body = self._parse_block()
        return GetterDecl(name=name, return_type=None, body=body, info=info)

    def _parse_getter_after_var(self, var: VarDecl) -> GetterDecl:
        self._expect(TokenType.GETTER)
        body = self._parse_block()
        return GetterDecl(name=var.name, return_type=var.type_annotation, body=body, info=var.info)

    def _parse_setter(self, is_pub: bool) -> SetterDecl:
        info = self._cur().info
        self._expect(TokenType.SETTER)
        name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.LPAR)
        param_name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.RPAR)
        body = self._parse_block()
        return SetterDecl(name=name, param_name=param_name, body=body, info=info)

    def _parse_setter_after_var(self, var: VarDecl) -> SetterDecl:
        self._expect(TokenType.SETTER)
        self._expect(TokenType.LPAR)
        param_name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.RPAR)
        body = self._parse_block()
        return SetterDecl(name=var.name, param_name=param_name, body=body, info=var.info)

    def _parse_func_or_var(
        self, is_pub: bool, is_const: bool, decorators: Sequence[Decorator] = ()
    ) -> TopLevel:
        if self._at(TokenType.ID):
            if self._peek(1).type == TokenType.LPAR:
                return self._parse_function_decl(is_pub, False, decorators)
            elif self._peek(1).type == TokenType.COLON:
                if decorators:
                    self._error("Decorators can only be applied to functions")
                return self._parse_var_decl(is_pub, is_const)
            else:
                self._error("Expected '(' for function or ':' for variable")
        self._error(f"Unexpected token {self._cur().type.value}")

    def _parse_function_decl(
        self, is_pub: bool, is_static: bool, decorators: Sequence[Decorator] = ()
    ) -> FunctionDecl:
        name_tok = self._expect(TokenType.ID)
        params = self._parse_params()
        return_type = None
        if self._match(TokenType.COLON):
            return_type = self._literal(self._expect(TokenType.ID))
        body = self._parse_block()
        return FunctionDecl(
            name=self._literal(name_tok),
            params=params,
            return_type=return_type,
            body=body,
            is_pub=is_pub,
            is_static=is_static,
            info=name_tok.info,
            decorators=tuple(decorators),
        )

    def _parse_params(self) -> list[Param]:
        self._expect(TokenType.LPAR)
        params: list[Param] = []
        if not self._at(TokenType.RPAR):
            params.append(self._parse_param())
            while self._match(TokenType.COMMA):
                params.append(self._parse_param())
        self._expect(TokenType.RPAR)
        return params

    def _parse_param(self) -> Param:
        name = self._literal(self._expect(TokenType.ID))
        type_ann = None
        default = None
        is_optional = False
        if self._match(TokenType.COLON):
            type_ann = self._literal(self._expect(TokenType.ID))
        if self._match(TokenType.QUEST):
            is_optional = True
        if self._match(TokenType.ASSIGN):
            default = self._parse_expression()
            is_optional = True
        return Param(name=name, type_annotation=type_ann, default=default, is_optional=is_optional)

    def _parse_var_decl(self, is_pub: bool, is_const: bool) -> VarDecl:
        name_tok = self._expect(TokenType.ID)
        type_ann = None
        if self._match(TokenType.COLON):
            type_ann = self._literal(self._expect(TokenType.ID))
        init = None
        if self._match(TokenType.ASSIGN):
            init = self._parse_expression()
        self._match(TokenType.SEM)
        return VarDecl(
            name=self._literal(name_tok),
            type_annotation=type_ann,
            initializer=init,
            is_const=is_const,
            is_pub=is_pub,
            info=name_tok.info,
        )

    def _parse_block(self) -> BlockStmt:
        info = self._cur().info
        self._expect(TokenType.LBRA)
        stmts: list[Stmt] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            stmts.append(self._parse_statement())
        self._expect(TokenType.RBRA)
        return BlockStmt(statements=stmts, info=info)

    def _parse_statement(self) -> Stmt:
        if self._at(TokenType.RETURN):
            return self._parse_return()
        if self._at(TokenType.IF):
            return self._parse_if()
        if self._at(TokenType.LOOP):
            return self._parse_loop()
        if self._at(TokenType.BREAK):
            return self._parse_break()
        if self._at(TokenType.CONTINUE):
            return self._parse_continue()
        if self._at(TokenType.THROW):
            return self._parse_throw()
        if self._at(TokenType.TRY):
            return self._parse_try_catch()
        if self._at(TokenType.LBRA):
            return self._parse_block()

        if self._at(TokenType.ID) and self._peek(1).type == TokenType.COLON:
            is_pub = False
            is_const = False
            return self._parse_var_decl(is_pub, is_const)

        return self._parse_expr_stmt()

    def _parse_return(self) -> ReturnStmt:
        info = self._cur().info
        self._expect(TokenType.RETURN)
        value = None
        if not self._at(TokenType.SEM, TokenType.RBRA):
            value = self._parse_expression()
        self._match(TokenType.SEM)
        return ReturnStmt(value=value, info=info)

    def _parse_if(self) -> IfStmt:
        info = self._cur().info
        self._expect(TokenType.IF)
        self._expect(TokenType.LPAR)
        cond = self._parse_expression()
        self._expect(TokenType.RPAR)
        then = self._parse_block()

        elifs: list[tuple[Expr, BlockStmt]] = []
        while self._match(TokenType.ELIF):
            self._expect(TokenType.LPAR)
            elif_cond = self._parse_expression()
            self._expect(TokenType.RPAR)
            elif_body = self._parse_block()
            elifs.append((elif_cond, elif_body))

        else_branch = None
        if self._match(TokenType.ELSE):
            else_branch = self._parse_block()

        return IfStmt(
            condition=cond,
            then_branch=then,
            elif_branches=elifs,
            else_branch=else_branch,
            info=info,
        )

    def _parse_loop(self) -> LoopStmt:
        info = self._cur().info
        self._expect(TokenType.LOOP)
        body = self._parse_block()
        return LoopStmt(body=body, info=info)

    def _parse_break(self) -> BreakStmt:
        info = self._cur().info
        self._expect(TokenType.BREAK)
        self._match(TokenType.SEM)
        return BreakStmt(info=info)

    def _parse_continue(self) -> ContinueStmt:
        info = self._cur().info
        self._expect(TokenType.CONTINUE)
        self._match(TokenType.SEM)
        return ContinueStmt(info=info)

    def _parse_throw(self) -> ThrowStmt:
        info = self._cur().info
        self._expect(TokenType.THROW)
        value = self._parse_expression()
        self._match(TokenType.SEM)
        return ThrowStmt(value=value, info=info)

    def _parse_try_catch(self) -> TryCatchStmt:
        info = self._cur().info
        self._expect(TokenType.TRY)
        try_body = self._parse_block()

        catch_var = None
        catch_body = None
        if self._match(TokenType.CATCH):
            self._expect(TokenType.LPAR)
            catch_var = self._literal(self._expect(TokenType.ID))
            self._expect(TokenType.RPAR)
            catch_body = self._parse_block()

        finally_body = None
        if self._match(TokenType.FINALLY):
            finally_body = self._parse_block()

        return TryCatchStmt(
            try_body=try_body,
            catch_var=catch_var,
            catch_body=catch_body,
            finally_body=finally_body,
            info=info,
        )

    def _parse_expr_stmt(self) -> ExprStmt:
        expr = self._parse_expression()
        self._match(TokenType.SEM)
        return ExprStmt(expr=expr, info=expr.info)

    def _parse_expression(self) -> Expr:
        return self._parse_assignment()

    def _parse_assignment(self) -> Expr:
        left = self._parse_elvis()
        if self._at(TokenType.ASSIGN):
            info = self._advance().info
            right = self._parse_assignment()
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
                right = self._parse_assignment()
                return CompoundAssignExpr(op=op_str, target=left, value=right, info=info)
        return left

    def _parse_elvis(self) -> Expr:
        left = self._parse_or()
        if self._at(TokenType.QUEST) and self._peek(1).type == TokenType.COLON:
            self._advance()
            self._advance()
            right = self._parse_or()
            return ElvExpr(left=left, right=right, info=left.info)
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
                if self._at(TokenType.LPAR):
                    self._advance()
                    if not self._at(TokenType.RPAR):
                        args.append(self._parse_expression())
                        while self._match(TokenType.COMMA):
                            args.append(self._parse_expression())
                    self._expect(TokenType.RPAR)
                expr = SafeCallExpr(obj=expr, member=member, args=args, info=expr.info)
            elif self._at(TokenType.ARROW):
                expr = self._parse_pattern_match(expr)
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

    def _parse_pattern_match(self, scrutinee: Expr) -> PatternMatchExpr:
        info = self._cur().info
        self._expect(TokenType.ARROW)
        self._expect(TokenType.LBRA)
        arms: list[MatchArm] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            arm_info = self._cur().info
            pattern = self._parse_match_pattern()
            # body can be = then expr or { block }
            if self._at(TokenType.LBRA):
                body = self._parse_block()
            elif self._match(TokenType.ASSIGN):
                if self._at(TokenType.LBRA):
                    body = self._parse_block()
                else:
                    body = self._parse_expression()
                self._match(TokenType.SEM)
            else:
                body = self._parse_expression()
                self._match(TokenType.SEM)
            arms.append(MatchArm(pattern=pattern, body=body, info=arm_info))
        self._expect(TokenType.RBRA)
        return PatternMatchExpr(scrutinee=scrutinee, arms=arms, info=info)

    def _parse_match_pattern(self) -> MatchPattern:
        if self._match(TokenType.IS):
            type_name = self._literal(self._expect(TokenType.ID))
            return MatchPattern(kind="type", value=type_name)
        if self._at(
            TokenType.STRING,
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.TRUE,
            TokenType.FALSE,
            TokenType.NULL,
        ):
            return MatchPattern(kind="literal", value=self._parse_primary())
        tok = self._expect(TokenType.ID)
        name = self._literal(tok)
        if name in ("Ok", "Err"):
            return MatchPattern(kind="result", value=name)
        if name == "_":
            return MatchPattern(kind="wildcard", value=None)
        return MatchPattern(kind="literal", value=Identifier(name=name, info=tok.info))

    def _parse_primary(self) -> Expr:
        tok = self._cur()

        if self._at(TokenType.INT):
            self._advance()
            return IntLiteral(value=int(self._literal(tok)), info=tok.info)

        if self._at(TokenType.FLOAT):
            self._advance()
            return FloatLiteral(value=float(self._literal(tok)), info=tok.info)

        if self._at(TokenType.STRING):
            self._advance()
            return StrLiteral(value=self._literal(tok), info=tok.info)

        if self._at(TokenType.TRUE):
            self._advance()
            return BoolLiteral(value=True, info=tok.info)

        if self._at(TokenType.FALSE):
            self._advance()
            return BoolLiteral(value=False, info=tok.info)

        if self._at(TokenType.NULL):
            self._advance()
            return NullLiteral(info=tok.info)

        if self._at(TokenType.THIS):
            self._advance()
            return ThisExpr(info=tok.info)

        # 'it'
        if self._at(TokenType.ID) and tok.literal == "it":
            self._advance()
            return ItExpr(info=tok.info)

        if self._at(TokenType.ID) and tok.literal == "Ok":
            self._advance()
            self._expect(TokenType.LPAR)
            val = self._parse_expression()
            self._expect(TokenType.RPAR)
            return OkExpr(value=val, info=tok.info)

        if self._at(TokenType.ID) and tok.literal == "Err":
            self._advance()
            self._expect(TokenType.LPAR)
            val = self._parse_expression()
            self._expect(TokenType.RPAR)
            return ErrExpr(value=val, info=tok.info)

        # List(...)
        if self._at(TokenType.ID) and tok.literal == "List":
            self._advance()
            self._expect(TokenType.LPAR)
            elems: list[Expr] = []
            if not self._at(TokenType.RPAR):
                elems.append(self._parse_expression())
                while self._match(TokenType.COMMA):
                    elems.append(self._parse_expression())
            self._expect(TokenType.RPAR)
            return ListExpr(elements=elems, info=tok.info)

        # Lambda: fn(params) { body } or fn(params) expr
        if self._at(TokenType.ID) and tok.literal == "fn" and self._is_lambda_ahead():
            return self._parse_lambda()

        # Identifier
        if self._at(TokenType.ID):
            self._advance()
            return Identifier(name=self._literal(tok), info=tok.info)

        # Grouped Expr: (expr)
        if self._at(TokenType.LPAR):
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAR)
            return expr

        self._error(f"Unexpected token {tok.type.value}")

    def _parse_lambda(self) -> LambdaExpr:
        info = self._cur().info
        self._advance()  # fn
        self._expect(TokenType.LPAR)
        params: list[tuple[str, Optional[str]]] = []
        if not self._at(TokenType.RPAR):
            pname = self._literal(self._expect(TokenType.ID))
            ptype = None
            if self._match(TokenType.COLON):
                ptype = self._literal(self._expect(TokenType.ID))
            params.append((pname, ptype))
            while self._match(TokenType.COMMA):
                pname = self._literal(self._expect(TokenType.ID))
                ptype = None
                if self._match(TokenType.COLON):
                    ptype = self._literal(self._expect(TokenType.ID))
                params.append((pname, ptype))
        self._expect(TokenType.RPAR)

        return_type = None
        if self._match(TokenType.COLON):
            return_type = self._literal(self._expect(TokenType.ID))

        if self._at(TokenType.LBRA):
            body = self._parse_block()
        else:
            body = self._parse_expression()
        return LambdaExpr(params=params, return_type=return_type, body=body, info=info)
