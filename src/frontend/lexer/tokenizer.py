from typing import Optional

from .char_stream import CharStream
from .error_handler import ErrorHandler
from .token_types import Token, TokenInfo, TokenType


class Tokenizer:
    _KEYWORD_MAP: dict[str, TokenType] = {
        "return": TokenType.RETURN,
        "if": TokenType.IF,
        "elif": TokenType.ELIF,
        "else": TokenType.ELSE,
        "loop": TokenType.LOOP,
        "break": TokenType.BREAK,
        "continue": TokenType.CONTINUE,
        "init": TokenType.INIT,
        "this": TokenType.THIS,
        "import": TokenType.IMPORT,
        "true": TokenType.TRUE,
        "false": TokenType.FALSE,
        "null": TokenType.NULL,
        "getter": TokenType.GETTER,
        "setter": TokenType.SETTER,
        "pub": TokenType.PUBLIC,
        "pri": TokenType.PRIVATE,
        "const": TokenType.CONST,
        "static": TokenType.STATIC,
        "is": TokenType.IS,
        "try": TokenType.TRY,
        "catch": TokenType.CATCH,
        "finally": TokenType.FINALLY,
        "throw": TokenType.THROW,
    }

    @staticmethod
    def _add_token(
        token_list: list[Token], type: TokenType, info: TokenInfo, literal: Optional[str]
    ) -> None:
        token_list.append(Token(literal, info, type))

    @staticmethod
    def _read_string(cs: CharStream, info: TokenInfo, quote: str) -> str:
        closed = False
        chars = []

        while cs.has_next():
            ch = cs.next()
            if ch == quote:
                closed = True
                break
            if ch == "\\" and cs.has_next():
                nxt = cs.next()
                chars.append(
                    {
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        "\\": "\\",
                        '"': '"',
                        "'": "'",
                    }.get(nxt, f"\\{nxt}")
                )
            else:
                chars.append(ch)

        if not closed:
            ErrorHandler.report(
                info=info, reason="Unterminated String", source_line=cs.get_source_line(info.line)
            )
        return "".join(chars)

    @staticmethod
    def _read_number(cs: CharStream, info: TokenInfo, first: str) -> tuple[TokenType, str]:
        sb = [first]
        while cs.peek().isdigit():
            sb.append(cs.next())

        is_float = False
        if cs.peek() == ".":
            is_float = True
            sb.append(cs.next())
            if not cs.peek().isdigit():
                ErrorHandler.report(
                    info=info, reason="Invalid Float", source_line=cs.get_source_line(info.line)
                )
            else:
                while cs.peek().isdigit():
                    sb.append(cs.next())

        return (TokenType.FLOAT if is_float else TokenType.INT, "".join(sb))

    @staticmethod
    def _read_identifier(cs: CharStream, first: str) -> str:
        sb = [first]
        while cs.peek().isalnum() or cs.peek() == "_":
            sb.append(cs.next())
        return "".join(sb)

    @staticmethod
    def _handle_operator_or_delimiter(
        c: str, cs: CharStream, info: TokenInfo, token_list: list[Token]
    ) -> bool:
        match c:
            case "+":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.ADD_ASSIGN, info, "+=")
                else:
                    Tokenizer._add_token(token_list, TokenType.ADD, info, "+")
            case "-":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.MINUS_ASSIGN, info, "-=")
                elif cs.peek() == ">":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.ARROW, info, "->")
                else:
                    Tokenizer._add_token(token_list, TokenType.MINUS, info, "-")
            case "=":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.EQ, info, "==")
                else:
                    Tokenizer._add_token(token_list, TokenType.ASSIGN, info, "=")
            case "*":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.MULT_ASSIGN, info, "*=")
                else:
                    Tokenizer._add_token(token_list, TokenType.MULT, info, "*")
            case "/":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.DIV_ASSIGN, info, "/=")
                elif cs.peek() == "/":
                    cs.next()
                    while cs.has_next() and cs.peek() not in "\n\r":
                        cs.next()
                elif cs.peek() == "*":
                    cs.next()
                    cnt = 1
                    while cs.has_next() and cnt > 0:
                        cur = cs.next()
                        if cur == "*" and cs.peek() == "/":
                            cs.next()
                            cnt -= 1
                        elif cur == "/" and cs.peek() == "*":
                            cs.next()
                            cnt += 1
                else:
                    Tokenizer._add_token(token_list, TokenType.DIV, info, "/")
            case "%":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.REM_ASSIGN, info, "%=")
                else:
                    Tokenizer._add_token(token_list, TokenType.REM, info, "%")
            case "^":
                Tokenizer._add_token(token_list, TokenType.XOR, info, "^")
            case "~":
                Tokenizer._add_token(token_list, TokenType.NOTB, info, "~")
            case "&" | "|" | ">" | "<":
                if cs.peek() == c:
                    cs.next()
                    type_map = {
                        "&": TokenType.ANDL,
                        "|": TokenType.ORL,
                        ">": TokenType.SHIFTR,
                        "<": TokenType.SHIFTL,
                    }
                    Tokenizer._add_token(token_list, type_map[c], info, c + c)
                elif c in "><" and cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(
                        token_list, TokenType.GE if c == ">" else TokenType.LE, info, f"{c}="
                    )
                else:
                    type_map = {
                        "&": TokenType.ANDB,
                        "|": TokenType.ORB,
                        ">": TokenType.GT,
                        "<": TokenType.LT,
                    }
                    Tokenizer._add_token(token_list, type_map[c], info, c)
            case "!":
                if cs.peek() == "=":
                    cs.next()
                    Tokenizer._add_token(token_list, TokenType.NE, info, "!=")
                else:
                    Tokenizer._add_token(token_list, TokenType.NOTL, info, "!")
            case "(":
                Tokenizer._add_token(token_list, TokenType.LPAR, info, "(")
            case ")":
                Tokenizer._add_token(token_list, TokenType.RPAR, info, ")")
            case "[":
                Tokenizer._add_token(token_list, TokenType.LBRACK, info, "[")
            case "]":
                Tokenizer._add_token(token_list, TokenType.RBRACK, info, "]")
            case "{":
                Tokenizer._add_token(token_list, TokenType.LBRA, info, "{")
            case "}":
                Tokenizer._add_token(token_list, TokenType.RBRA, info, "}")
            case ";":
                Tokenizer._add_token(token_list, TokenType.SEM, info, ";")
            case ",":
                Tokenizer._add_token(token_list, TokenType.COMMA, info, ",")
            case ".":
                Tokenizer._add_token(token_list, TokenType.DOT, info, ".")
            case "#":
                Tokenizer._add_token(token_list, TokenType.HASH, info, "#")
            case "@":
                Tokenizer._add_token(token_list, TokenType.AT, info, "@")
            case ":":
                Tokenizer._add_token(token_list, TokenType.COLON, info, ":")
            case "?":
                Tokenizer._add_token(token_list, TokenType.QUEST, info, "?")
            case _:
                return False
        return True

    @staticmethod
    def _handle_slash(cs: CharStream, info: TokenInfo, token_list: list[Token]) -> None:
        if cs.peek() == "=":
            cs.next()
            Tokenizer._add_token(token_list, TokenType.DIV_ASSIGN, info, "/=")
        elif cs.peek() == "/":
            cs.next()
            while cs.has_next() and cs.peek() not in "\n\r":
                cs.next()
        elif cs.peek() == "*":
            cs.next()
            cnt = 1
            while cs.has_next() and cnt > 0:
                cur = cs.next()
                if cur == "*" and cs.peek() == "/":
                    cs.next()
                    cnt -= 1
                elif cur == "/" and cs.peek() == "*":
                    cs.next()
                    cnt += 1
        else:
            Tokenizer._add_token(token_list, TokenType.DIV, info, "/")

    @staticmethod
    def tokenize(src: str, file_name: Optional[str] = None) -> list[Token]:
        token_list: list[Token] = []
        cs = CharStream(src)

        while cs.has_next():
            info = TokenInfo(file_name, cs.line, cs.column)
            c = cs.next()

            if c in " \t\r\n":
                continue
            elif c == "/":
                Tokenizer._handle_slash(cs, info, token_list)
            elif c in "\"'":
                content = Tokenizer._read_string(cs, info, c)
                Tokenizer._add_token(token_list, TokenType.STRING, info, content)
            elif c.isdigit():
                ttype, literal = Tokenizer._read_number(cs, info, c)
                Tokenizer._add_token(token_list, ttype, info, literal)
            elif c.isalpha() or c == "_":
                lex = Tokenizer._read_identifier(cs, c)
                ttype = Tokenizer._KEYWORD_MAP.get(lex, TokenType.ID)
                Tokenizer._add_token(token_list, ttype, info, lex)
            elif not Tokenizer._handle_operator_or_delimiter(c, cs, info, token_list):
                ErrorHandler.report(
                    info=info, reason="Unexpected Char", source_line=cs.get_source_line(info.line)
                )

        Tokenizer._add_token(token_list, TokenType.EOF, TokenInfo(file_name, 0, 0), None)
        return token_list
