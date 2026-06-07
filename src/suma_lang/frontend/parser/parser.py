from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn

from suma_lang.frontend.lexer.token_types import Token, TokenInfo, TokenType
from suma_lang.frontend.parser._expressions import _ExpressionsMixin
from suma_lang.frontend.parser.ast_nodes import (
    BlockStmt,
    BoolLiteral,
    BreakStmt,
    ClassDecl,
    ContinueStmt,
    Decorator,
    DestructureAssignStmt,
    DestructureDeclStmt,
    EnumDecl,
    EnumVariantDecl,
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
    ImportDecl,
    InterpolatedStringExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MatchArm,
    MatchPattern,
    NullLiteral,
    OkExpr,
    OuterIdentifier,
    Param,
    PatternMatchExpr,
    Program,
    ReturnStmt,
    SetterDecl,
    Stmt,
    StrLiteral,
    ThisExpr,
    ThrowStmt,
    TopLevel,
    TryCatchStmt,
    TupleExpr,
    VarDecl,
    WhileStmt,
)


class ParseError(SyntaxError):
    pass


class Parser(_ExpressionsMixin):
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self.errors: list[str] = []
        self._matching_rpar_cache: dict[int, int | None] = {}

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

    def _match(self, *types: TokenType) -> Token | None:
        if self._at(*types):
            return self._advance()
        return None

    def _at_contextual(self, literal: str) -> bool:
        return self._at(TokenType.ID) and self._cur().literal == literal

    def _synchronize_top_level(self) -> None:
        if not self._at(TokenType.EOF):
            self._advance()
        depth = 0
        while not self._at(TokenType.EOF):
            tok_type = self._cur().type
            if tok_type == TokenType.LBRA:
                depth += 1
            elif tok_type == TokenType.RBRA:
                if depth == 0:
                    self._advance()
                    break
                depth -= 1
            elif depth == 0 and tok_type in (
                TokenType.AT,
                TokenType.PUBLIC,
                TokenType.PRIVATE,
                TokenType.IMPORT,
                TokenType.CONST,
                TokenType.ENUM,
                TokenType.ID,
            ):
                break
            self._advance()

    def _next_after_optional_type_params(self, index: int) -> int:
        if index >= len(self._tokens) or self._tokens[index].type != TokenType.LT:
            return index
        index += 1
        expect_name = True
        while index < len(self._tokens):
            token_type = self._tokens[index].type
            if expect_name:
                if token_type != TokenType.ID:
                    return index
                index += 1
                expect_name = False
                continue
            if token_type == TokenType.COMMA:
                index += 1
                expect_name = True
                continue
            if token_type == TokenType.GT:
                return index + 1
            return index
        return index

    def _parse_type_params(self) -> tuple[str, ...]:
        if not self._match(TokenType.LT):
            return ()
        params: list[str] = []
        if self._at(TokenType.GT):
            self._error("Generic parameter list cannot be empty")
        while True:
            params.append(self._literal(self._expect(TokenType.ID)))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.GT)
        if len(params) != len(set(params)):
            self._error("Generic parameter names must be unique")
        return tuple(params)

    def _next_after_type_name(self, index: int) -> int | None:
        if index >= len(self._tokens) or self._tokens[index].type != TokenType.ID:
            return None
        depth = 0
        saw_token = False
        while index < len(self._tokens):
            token_type = self._tokens[index].type
            if (
                depth == 0
                and saw_token
                and token_type
                in {
                    TokenType.COMMA,
                    TokenType.RPAR,
                    TokenType.ASSIGN,
                    TokenType.LBRA,
                    TokenType.RBRA,
                    TokenType.SEM,
                    TokenType.DOT,
                    TokenType.ARROW,
                }
            ):
                return index
            if depth == 0 and saw_token and token_type == TokenType.ID:
                return index
            if token_type == TokenType.ID:
                saw_token = True
                index += 1
            elif token_type == TokenType.LT:
                saw_token = True
                depth += 1
                index += 1
            elif token_type == TokenType.GT:
                if depth <= 0:
                    return index
                depth -= 1
                index += 1
            elif token_type == TokenType.SHIFTR:
                if depth < 2:
                    return None
                depth -= 2
                index += 1
            elif depth > 0 and (
                token_type == TokenType.COMMA or (token_type == TokenType.QUEST and saw_token)
            ):
                index += 1
            elif token_type == TokenType.QUEST and depth == 0 and saw_token:
                index += 1
                return index
            else:
                return None
        return index if saw_token and depth == 0 else None

    def _skip_type_annotation_in_range(self, index: int, end: int) -> int | None:
        if index >= end or self._tokens[index].type != TokenType.ID:
            return None
        depth = 0
        saw_token = False
        while index < end:
            token_type = self._tokens[index].type
            if depth == 0 and saw_token and token_type == TokenType.COMMA:
                break
            if token_type == TokenType.ID:
                saw_token = True
                index += 1
            elif token_type == TokenType.LT:
                saw_token = True
                depth += 1
                index += 1
            elif token_type == TokenType.GT:
                depth -= 1
                if depth < 0:
                    return None
                index += 1
            elif token_type == TokenType.SHIFTR:
                depth -= 2
                if depth < 0:
                    return None
                index += 1
            elif depth > 0 and (
                token_type == TokenType.COMMA or (token_type == TokenType.QUEST and saw_token)
            ):
                index += 1
            elif token_type == TokenType.QUEST and depth == 0 and saw_token:
                index += 1
                break
            else:
                return None
        return index if saw_token and depth == 0 else None

    def _parse_type_name(self) -> str:
        if self._at(TokenType.LPAR):
            return self._parse_tuple_type_name()
        if not self._at(TokenType.ID):
            self._error(f"Expected type name, got {self._cur().type.value}")

        parts: list[str] = []
        depth = 0
        saw_token = False
        terminators = {
            TokenType.COMMA,
            TokenType.RPAR,
            TokenType.ASSIGN,
            TokenType.LBRA,
            TokenType.RBRA,
            TokenType.SEM,
            TokenType.DOT,
            TokenType.QUEST,
            TokenType.ARROW,
        }

        while not self._at(TokenType.EOF):
            tok = self._cur()
            token_type = tok.type
            if depth == 0 and saw_token and token_type in terminators:
                break
            if depth == 0 and saw_token and token_type == TokenType.ID:
                break
            if token_type == TokenType.ID:
                parts.append(self._literal(tok))
                self._advance()
                saw_token = True
            elif token_type == TokenType.LT:
                parts.append("<")
                self._advance()
                depth += 1
                saw_token = True
            elif token_type == TokenType.GT:
                if depth <= 0:
                    break
                parts.append(">")
                self._advance()
                depth -= 1
            elif token_type == TokenType.SHIFTR:
                if depth < 2:
                    self._error("Unexpected '>>' in type annotation")
                parts.append(">>")
                self._advance()
                depth -= 2
            elif token_type == TokenType.COMMA and depth > 0:
                parts.append(",")
                self._advance()
            elif token_type == TokenType.QUEST and depth > 0 and saw_token:
                parts.append("?")
                self._advance()
            else:
                if depth > 0:
                    self._error(f"Unexpected token {token_type.value} in type annotation")
                break

        if not saw_token:
            self._error("Expected type name")
        if depth != 0:
            self._error("Unterminated generic type annotation")
        type_name = self._normalize_type_name("".join(parts))
        if self._match(TokenType.QUEST):
            return f"Nullable<{type_name}>"
        return type_name

    def _normalize_type_name(self, type_name: str) -> str:
        def parse(index: int) -> tuple[str, int]:
            start = index
            while index < len(type_name) and (
                type_name[index].isalnum() or type_name[index] == "_"
            ):
                index += 1
            if start == index:
                return type_name[start:], len(type_name)
            base = type_name[start:index]
            if base == "Result":
                base = "R"
            if index < len(type_name) and type_name[index] == "<":
                index += 1
                args: list[str] = []
                while index < len(type_name) and type_name[index] != ">":
                    arg, index = parse(index)
                    args.append(arg)
                    if index < len(type_name) and type_name[index] == ",":
                        index += 1
                        continue
                    break
                if index < len(type_name) and type_name[index] == ">":
                    index += 1
                base = f"{base}<{','.join(args)}>"
            if index < len(type_name) and type_name[index] == "?":
                index += 1
                base = f"Nullable<{base}>"
            return base, index

        normalized, index = parse(0)
        return normalized + type_name[index:]

    def _parse_tuple_type_name(self) -> str:
        self._expect(TokenType.LPAR)
        types = [self._parse_type_name()]
        if not self._match(TokenType.COMMA):
            self._error("Tuple type must contain at least two elements")
        types.append(self._parse_type_name())
        while self._match(TokenType.COMMA):
            types.append(self._parse_type_name())
        self._expect(TokenType.RPAR)
        type_name = f"Tuple<{','.join(types)}>"
        if self._match(TokenType.QUEST):
            return f"Nullable<{type_name}>"
        return type_name

    def _matching_rpar_index(self, start: int) -> int | None:
        cached = self._matching_rpar_cache.get(start)
        if cached is not None or start in self._matching_rpar_cache:
            return cached
        depth = 0
        for i in range(start, len(self._tokens)):
            token_type = self._tokens[i].type
            if token_type == TokenType.LPAR:
                depth += 1
            elif token_type == TokenType.RPAR:
                depth -= 1
                if depth == 0:
                    self._matching_rpar_cache[start] = i
                    return i
        self._matching_rpar_cache[start] = None
        return None

    def _looks_like_lambda_params(self, start: int, end: int) -> bool:
        if start == end:
            return True
        i = start
        expect_param = True
        while i < end:
            if not expect_param:
                if self._tokens[i].type != TokenType.COMMA:
                    return False
                i += 1
                expect_param = True
                continue
            if self._tokens[i].type != TokenType.ID:
                return False
            i += 1
            if i < end and self._tokens[i].type == TokenType.COLON:
                i += 1
                next_i = self._skip_type_annotation_in_range(i, end)
                if next_i is None:
                    return False
                i = next_i
            expect_param = False
        return not expect_param

    def _is_paren_lambda_ahead(self) -> bool:
        """Lookahead for the modern `(params) -> body` lambda syntax."""
        return self._paren_primary_kind() == "lambda"

    def _has_top_level_comma_before_rpar(self, start: int, rpar: int) -> bool:
        depth = 0
        for index in range(start + 1, rpar):
            token_type = self._tokens[index].type
            if token_type == TokenType.LPAR:
                depth += 1
            elif token_type == TokenType.RPAR:
                depth -= 1
            elif token_type == TokenType.COMMA and depth == 0:
                return True
        return False

    def _paren_primary_kind(self) -> str:
        if not self._at(TokenType.LPAR):
            return "none"
        rpar = self._matching_rpar_index(self._pos)
        if rpar is None:
            return "grouped"
        if self._looks_like_lambda_params(self._pos + 1, rpar):
            next_index = rpar + 1
            if next_index < len(self._tokens):
                next_token = self._tokens[next_index]
                if next_token.type == TokenType.ARROW:
                    return "lambda"
                if next_token.type == TokenType.COLON:
                    after_type = self._next_after_type_name(next_index + 1)
                    if after_type is not None and self._tokens[after_type].type == TokenType.ARROW:
                        return "lambda"
        if self._has_top_level_comma_before_rpar(self._pos, rpar):
            return "tuple"
        return "grouped"

    @staticmethod
    def parse(tokens: list[Token]) -> Program:
        p = Parser(tokens)
        decls: list[TopLevel] = []
        while not p._at(TokenType.EOF):
            try:
                decls.append(p._parse_top_level())
            except ParseError as err:
                p.errors.append(str(err))
                p._synchronize_top_level()
        if p.errors:
            raise ParseError("\n".join(p.errors))
        return Program(declarations=decls)

    def _parse_top_level(self) -> TopLevel:
        decorators = self._parse_decorators()

        is_pub = False
        saw_visibility = False
        is_const = False
        if self._match(TokenType.PUBLIC):
            is_pub = True
            saw_visibility = True
        elif self._match(TokenType.PRIVATE):
            saw_visibility = True

        if self._at(TokenType.IMPORT):
            if saw_visibility:
                self._error("import declarations cannot be marked pub or pri")
            if decorators:
                self._error("Decorators can only be applied to functions")
            return self._parse_import()

        if self._match(TokenType.CONST):
            is_const = True

        if self._at(TokenType.ENUM):
            if decorators:
                self._error("Decorators cannot be applied to enum declarations")
            if is_const:
                self._error("Enums cannot be const")
            return self._parse_enum(is_pub)

        if self._at(TokenType.ID):
            after_name = self._next_after_optional_type_params(self._pos + 1)
            if after_name < len(self._tokens):
                if self._tokens[after_name].type == TokenType.LBRA:
                    return self._parse_class(is_pub, tuple(decorators))
                if self._tokens[after_name].type == TokenType.COLON:
                    after_base = self._next_after_type_name(after_name + 1)
                    if (
                        after_base is not None
                        and after_base < len(self._tokens)
                        and self._tokens[after_base].type == TokenType.LBRA
                    ):
                        return self._parse_class(is_pub, tuple(decorators))

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
        if not self._at(TokenType.STRING, TokenType.RAW_STRING):
            self._error(f"Expected {TokenType.STRING.value}, got {self._cur().type.value}")
        path_tok = self._advance()
        self._match(TokenType.SEM)
        return ImportDecl(path=self._literal(path_tok), info=info)

    def _parse_enum(self, is_pub: bool) -> EnumDecl:
        info = self._cur().info
        self._expect(TokenType.ENUM)
        name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.LBRA)
        variants: list[EnumVariantDecl] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            variant_tok = self._expect(TokenType.ID)
            payload_type = None
            if self._match(TokenType.LPAR):
                if self._at(TokenType.RPAR):
                    self._error("Enum variant payload type cannot be empty")
                payload_type = self._parse_type_name()
                self._expect(TokenType.RPAR)
            variants.append(
                EnumVariantDecl(
                    name=self._literal(variant_tok),
                    payload_type=payload_type,
                    info=variant_tok.info,
                )
            )
            self._match(TokenType.COMMA, TokenType.SEM)
        self._expect(TokenType.RBRA)
        if not variants:
            self._error(f"Enum '{name}' must declare at least one variant")
        return EnumDecl(name=name, variants=tuple(variants), is_pub=is_pub, info=info)

    def _parse_class(self, is_pub: bool, decorators: Sequence[Decorator] = ()) -> ClassDecl:
        name_tok = self._expect(TokenType.ID)
        type_params = self._parse_type_params()
        base_type = None
        if self._match(TokenType.COLON):
            base_type = self._parse_type_name()
        self._expect(TokenType.LBRA)
        members: list[FunctionDecl | VarDecl | GetterDecl | SetterDecl] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            members.append(self._parse_class_member())
        self._expect(TokenType.RBRA)
        return ClassDecl(
            name=self._literal(name_tok),
            members=members,
            is_pub=is_pub,
            info=name_tok.info,
            type_params=type_params,
            base_type=base_type,
            decorators=tuple(decorators),
        )

    def _parse_class_member(self) -> FunctionDecl | VarDecl | GetterDecl | SetterDecl:
        decorators = self._parse_decorators()

        is_pub = False
        is_static = False
        if self._match(TokenType.PUBLIC):
            is_pub = True
        elif self._match(TokenType.PRIVATE):
            is_pub = False

        if self._match(TokenType.STATIC):
            is_static = True

        if self._at(TokenType.INIT):
            if decorators:
                self._error("Decorators cannot be applied to init")
            return self._parse_init(is_pub)

        if self._at_contextual("get") and self._peek(1).type == TokenType.ID:
            if decorators:
                self._error("Decorators cannot be applied to getters")
            if is_static:
                self._error("Getters cannot be static")
            return self._parse_getter(is_pub)
        if self._at_contextual("set") and self._peek(1).type == TokenType.ID:
            if decorators:
                self._error("Decorators cannot be applied to setters")
            if is_static:
                self._error("Setters cannot be static")
            return self._parse_setter(is_pub)

        if self._at(TokenType.ID) and self._peek(1).type == TokenType.COLON:
            if decorators:
                self._error("Decorators can only be applied to functions")
            return self._parse_var_decl(is_pub, False)

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
        self._expect(TokenType.ID)
        name = self._literal(self._expect(TokenType.ID))
        params = self._parse_params()
        if params:
            self._error("Getters cannot have parameters")
        if not self._match(TokenType.COLON):
            self._error("Getters must declare a return type")
        return_type = self._parse_type_name()
        body = self._parse_block()
        return GetterDecl(name=name, return_type=return_type, body=body, is_pub=is_pub, info=info)

    def _parse_setter(self, is_pub: bool) -> SetterDecl:
        info = self._cur().info
        self._expect(TokenType.ID)
        name = self._literal(self._expect(TokenType.ID))
        params = self._parse_params()
        if len(params) != 1:
            self._error("Setters must have exactly one parameter")
        param = params[0]
        if param.type_annotation is None:
            self._error("Setter parameter must declare a type")
        if param.default is not None:
            self._error("Setter parameter cannot be optional or have a default value")
        if self._match(TokenType.COLON):
            self._error("Setters cannot declare a return type")
        body = self._parse_block()
        return SetterDecl(
            name=name,
            param_name=param.name,
            param_type=param.type_annotation,
            body=body,
            is_pub=is_pub,
            info=info,
        )

    def _parse_func_or_var(
        self, is_pub: bool, is_const: bool, decorators: Sequence[Decorator] = ()
    ) -> TopLevel:
        if self._at(TokenType.ID):
            after_name = self._next_after_optional_type_params(self._pos + 1)
            if after_name < len(self._tokens) and self._tokens[after_name].type == TokenType.LPAR:
                return self._parse_function_decl(is_pub, False, decorators)
            elif self._peek(1).type in (TokenType.COLON, TokenType.ASSIGN):
                if decorators:
                    self._error("Decorators can only be applied to functions")
                return self._parse_var_decl(is_pub, is_const)
            else:
                self._error("Expected '(' for function or ':'/'=' for variable")
        self._error(f"Unexpected token {self._cur().type.value}")

    def _parse_function_decl(
        self, is_pub: bool, is_static: bool, decorators: Sequence[Decorator] = ()
    ) -> FunctionDecl:
        name_tok = self._expect(TokenType.ID)
        type_params = self._parse_type_params()
        params = self._parse_params()
        return_type = None
        if self._match(TokenType.COLON):
            return_type = self._parse_type_name()
        body = self._parse_block()
        return FunctionDecl(
            name=self._literal(name_tok),
            params=params,
            return_type=return_type,
            body=body,
            is_pub=is_pub,
            is_static=is_static,
            info=name_tok.info,
            type_params=type_params,
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
            type_ann = self._parse_type_name()
        if self._match(TokenType.ASSIGN):
            default = self._parse_expression()
            is_optional = True
        return Param(name=name, type_annotation=type_ann, default=default, is_optional=is_optional)

    def _parse_var_decl(self, is_pub: bool, is_const: bool) -> VarDecl:
        name_tok = self._expect(TokenType.ID)
        type_ann = None
        if self._match(TokenType.COLON):
            type_ann = self._parse_type_name()
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
        if self._at(TokenType.WHILE):
            return self._parse_while()
        if self._at(TokenType.FOR):
            return self._parse_for_in()
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
        if self._is_destructure_assignment_ahead():
            return self._parse_destructure_assignment()

        if self._at(TokenType.ID) and self._peek(1).type == TokenType.COLON:
            is_pub = False
            is_const = False
            decl = self._parse_var_decl(is_pub, is_const)
            if decl.initializer is None:
                self._error("local declarations must include an initializer")
            return decl

        return self._parse_expr_stmt()

    def _parse_destructure_decl(self, info: TokenInfo) -> DestructureDeclStmt:
        self._expect(TokenType.LPAR)
        targets = [self._literal(self._expect(TokenType.ID))]
        if not self._match(TokenType.COMMA):
            self._error("Destructuring declarations require at least two targets")
        targets.append(self._literal(self._expect(TokenType.ID)))
        while self._match(TokenType.COMMA):
            targets.append(self._literal(self._expect(TokenType.ID)))
        self._expect(TokenType.RPAR)
        self._expect(TokenType.ASSIGN)
        value = self._parse_expression()
        self._match(TokenType.SEM)
        return DestructureDeclStmt(targets=tuple(targets), value=value, info=info)

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
        cond = self._parse_paren_or_bare_condition(allow_result_else=False)
        then = self._parse_block()

        elifs: list[tuple[Expr, BlockStmt]] = []
        while self._match(TokenType.ELIF):
            elif_cond = self._parse_paren_or_bare_condition(allow_result_else=False)
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

    def _parse_if_expr(self) -> IfExpr:
        info = self._cur().info
        self._expect(TokenType.IF)
        cond = self._parse_paren_or_bare_condition(allow_result_else=False)
        then = self._parse_block()

        elifs: list[tuple[Expr, BlockStmt]] = []
        while self._match(TokenType.ELIF):
            elif_cond = self._parse_paren_or_bare_condition(allow_result_else=False)
            elif_body = self._parse_block()
            elifs.append((elif_cond, elif_body))

        else_branch = None
        if self._match(TokenType.ELSE):
            else_branch = self._parse_block()

        return IfExpr(
            condition=cond,
            then_branch=then,
            elif_branches=elifs,
            else_branch=else_branch,
            info=info,
        )

    def _parse_while(self) -> WhileStmt:
        info = self._cur().info
        self._expect(TokenType.WHILE)
        condition = self._parse_paren_or_bare_condition(allow_result_else=False)
        body = self._parse_block()
        return WhileStmt(condition=condition, body=body, info=info)

    def _parse_paren_or_bare_condition(self, *, allow_result_else: bool = True) -> Expr:
        if self._match(TokenType.LPAR):
            condition = self._parse_expression()
            self._expect(TokenType.RPAR)
            return condition
        return self._parse_expression(allow_result_else=allow_result_else)

    def _parse_for_in(self) -> ForInStmt:
        info = self._cur().info
        self._expect(TokenType.FOR)
        name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.IN)
        iterable = self._parse_expression()
        body = self._parse_block()
        return ForInStmt(var_name=name, iterable=iterable, body=body, info=info)

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

    def _is_destructure_assignment_ahead(self) -> bool:
        if not self._at(TokenType.LPAR):
            return False
        index = self._pos + 1
        if index >= len(self._tokens) or self._tokens[index].type != TokenType.ID:
            return False
        index += 1
        seen_comma = False
        while index < len(self._tokens):
            token_type = self._tokens[index].type
            if token_type == TokenType.COMMA:
                seen_comma = True
                index += 1
                if index >= len(self._tokens) or self._tokens[index].type != TokenType.ID:
                    return False
                index += 1
                continue
            if token_type == TokenType.RPAR:
                return seen_comma and self._peek(index - self._pos + 1).type == TokenType.ASSIGN
            return False
        return False

    def _parse_destructure_assignment(self) -> DestructureAssignStmt:
        info = self._cur().info
        self._expect(TokenType.LPAR)
        targets = [self._literal(self._expect(TokenType.ID))]
        while self._match(TokenType.COMMA):
            targets.append(self._literal(self._expect(TokenType.ID)))
        self._expect(TokenType.RPAR)
        self._expect(TokenType.ASSIGN)
        value = self._parse_expression()
        self._match(TokenType.SEM)
        return DestructureAssignStmt(targets=tuple(targets), value=value, info=info)

    def _parse_match_expr(self) -> PatternMatchExpr:
        info = self._cur().info
        self._expect(TokenType.MATCH)
        scrutinee = self._parse_expression()
        self._expect(TokenType.LBRA)
        arms = self._parse_match_arms()
        self._expect(TokenType.RBRA)
        return PatternMatchExpr(scrutinee=scrutinee, arms=arms, info=info)

    def _parse_match_arms(self) -> list[MatchArm]:
        arms: list[MatchArm] = []
        while not self._at(TokenType.RBRA, TokenType.EOF):
            arm_info = self._cur().info
            pattern, binding = self._parse_match_pattern()
            self._expect(TokenType.FAT_ARROW)
            body = self._parse_block() if self._at(TokenType.LBRA) else self._parse_expression()
            self._match(TokenType.SEM)
            arms.append(MatchArm(pattern=pattern, binding=binding, body=body, info=arm_info))
        return arms

    def _parse_optional_binding(self) -> str | None:
        if not self._match(TokenType.LPAR):
            return None
        name = self._literal(self._expect(TokenType.ID))
        self._expect(TokenType.RPAR)
        return name

    def _parse_match_pattern(self) -> tuple[MatchPattern, str | None]:
        if self._match(TokenType.IS):
            type_name = self._parse_type_name()
            return MatchPattern(kind="type", value=type_name), self._parse_optional_binding()
        if self._at(
            TokenType.STRING,
            TokenType.RAW_STRING,
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.TRUE,
            TokenType.FALSE,
            TokenType.NULL,
        ):
            pattern = MatchPattern(kind="literal", value=self._parse_primary())
            return pattern, self._parse_optional_binding()
        tok = self._expect(TokenType.ID)
        name = self._literal(tok)
        if self._match(TokenType.DOT):
            variant = self._literal(self._expect(TokenType.ID))
            return MatchPattern(
                kind="enum", value=f"{name}.{variant}"
            ), self._parse_optional_binding()
        if name in ("Ok", "Err"):
            return MatchPattern(kind="result", value=name), self._parse_optional_binding()
        if name == "_":
            return MatchPattern(kind="wildcard", value=None), self._parse_optional_binding()
        return (
            MatchPattern(kind="literal", value=Identifier(name=name, info=tok.info)),
            self._parse_optional_binding(),
        )

    def _parse_primary(self) -> Expr:
        tok = self._cur()

        if self._at(TokenType.IF):
            return self._parse_if_expr()

        if self._at(TokenType.MATCH):
            return self._parse_match_expr()

        if self._at(TokenType.AT):
            info = self._advance().info
            name = self._literal(self._expect(TokenType.ID))
            return OuterIdentifier(name=name, info=info)

        if self._at(TokenType.INT):
            self._advance()
            return IntLiteral(value=int(self._literal(tok), 0), info=tok.info)

        if self._at(TokenType.FLOAT):
            self._advance()
            return FloatLiteral(value=float(self._literal(tok)), info=tok.info)

        if self._at(TokenType.STRING, TokenType.RAW_STRING):
            self._advance()
            return self._parse_string_literal(
                self._literal(tok),
                tok.info,
                allow_interpolation=tok.type == TokenType.STRING,
            )

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

        # Lambda/tuple/grouped expressions all start with '('; classify once so
        # the common path does not repeatedly scan the same parenthesized span.
        if self._at(TokenType.LPAR):
            paren_kind = self._paren_primary_kind()
            if paren_kind == "lambda":
                return self._parse_lambda()
            if paren_kind == "tuple":
                return self._parse_tuple_literal()

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

    def _is_tuple_literal_ahead(self) -> bool:
        return self._paren_primary_kind() == "tuple"

    def _parse_tuple_literal(self) -> TupleExpr:
        info = self._cur().info
        self._expect(TokenType.LPAR)
        elements = [self._parse_expression()]
        if not self._match(TokenType.COMMA):
            self._error("Tuple literal must contain at least two elements")
        elements.append(self._parse_expression())
        while self._match(TokenType.COMMA):
            elements.append(self._parse_expression())
        self._expect(TokenType.RPAR)
        return TupleExpr(elements=tuple(elements), info=info)

    def _find_interpolation_end(self, value: str, start: int) -> int | None:
        depth = 1
        index = start + 1
        quote: str | None = None

        while index < len(value):
            ch = value[index]
            if quote is not None:
                if ch == "\\":
                    index += 2
                    continue
                if ch == quote:
                    quote = None
                index += 1
                continue
            if ch in "\"'":
                quote = ch
                index += 1
                continue
            if ch == "{":
                depth += 1
                index += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return index
                index += 1
                continue
            index += 1
        return None

    def _parse_string_literal(
        self, value: str, info: TokenInfo, *, allow_interpolation: bool = True
    ) -> Expr:
        if not allow_interpolation:
            return StrLiteral(value=value, info=info)

        parts: list[Expr] = []
        literal: list[str] = []
        index = 0

        def flush_literal() -> None:
            if literal:
                parts.append(StrLiteral(value="".join(literal), info=info))
                literal.clear()

        while index < len(value):
            ch = value[index]
            if ch == "\\" and index + 1 < len(value) and value[index + 1] in "{}":
                literal.append(value[index + 1])
                index += 2
                continue
            if ch != "{":
                literal.append(ch)
                index += 1
                continue

            end = self._find_interpolation_end(value, index)
            if end is None:
                literal.append(ch)
                index += 1
                continue
            expr_text = value[index + 1 : end].strip()
            if not expr_text:
                literal.append("{}")
                index = end + 1
                continue
            try:
                interpolated = self._parse_interpolation_expr(expr_text, info)
            except (ParseError, SyntaxError):
                literal.append(value[index : end + 1])
                index = end + 1
                continue
            flush_literal()
            parts.append(interpolated)
            index = end + 1

        flush_literal()
        if not parts:
            return StrLiteral(value=value, info=info)

        return InterpolatedStringExpr(parts=tuple(parts), info=info)

    def _parse_interpolation_expr(self, source: str, info: TokenInfo) -> Expr:
        from suma_lang.frontend.lexer.tokenizer import Tokenizer

        tokens = Tokenizer.tokenize(source, file_name=info.file)
        parser = Parser(tokens)
        expr = parser._parse_expression()
        if not parser._at(TokenType.EOF):
            self._error("Invalid string interpolation expression")
        return expr

    def _parse_lambda_params(self) -> list[tuple[str, str | None]]:
        self._expect(TokenType.LPAR)
        params: list[tuple[str, str | None]] = []
        if not self._at(TokenType.RPAR):
            while True:
                pname = self._literal(self._expect(TokenType.ID))
                ptype = None
                if self._match(TokenType.COLON):
                    ptype = self._parse_type_name()
                params.append((pname, ptype))
                if not self._match(TokenType.COMMA):
                    break
        self._expect(TokenType.RPAR)
        return params

    def _parse_lambda_body(self) -> Expr | BlockStmt:
        if self._at(TokenType.LBRA):
            return self._parse_block()
        if self._at(
            TokenType.RETURN,
            TokenType.IF,
            TokenType.LOOP,
            TokenType.BREAK,
            TokenType.CONTINUE,
            TokenType.THROW,
            TokenType.TRY,
        ):
            stmt = self._parse_statement()
            return BlockStmt(statements=(stmt,), info=stmt.info)
        return self._parse_expression()

    def _parse_lambda(self) -> LambdaExpr:
        info = self._cur().info
        params = self._parse_lambda_params()

        return_type = None
        if self._match(TokenType.COLON):
            return_type = self._parse_type_name()

        self._expect(TokenType.ARROW)

        body = self._parse_lambda_body()
        return LambdaExpr(params=params, return_type=return_type, body=body, info=info)
