from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TokenType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    TRUE = "true"
    FALSE = "false"
    NULL = "null"

    ID = "id"
    RETURN = "return"
    IF = "if"
    ELIF = "elif"
    ELSE = "else"
    LOOP = "loop"
    BREAK = "break"
    CONTINUE = "continue"
    INIT = "init"
    THIS = "this"
    IMPORT = "import"
    GETTER = "getter"
    SETTER = "setter"
    PUBLIC = "pub"
    PRIVATE = "pri"
    CONST = "const"
    STATIC = "static"
    IS = "is"
    TRY = "try"
    CATCH = "catch"
    FINALLY = "finally"
    THROW = "throw"

    ADD = "+"
    MINUS = "-"
    MULT = "*"
    DIV = "/"
    REM = "%"
    XOR = "^"
    NOTB = "~"
    ANDB = "&"
    ORB = "|"
    ANDL = "&&"
    ORL = "||"
    SHIFTL = "<<"
    SHIFTR = ">>"
    EQ = "=="
    NE = "!="
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="
    NOTL = "!"
    ASSIGN = "="
    ADD_ASSIGN = "+="
    MINUS_ASSIGN = "-="
    MULT_ASSIGN = "*="
    DIV_ASSIGN = "/="
    REM_ASSIGN = "%="
    ARROW = "->"

    LPAR = "("
    RPAR = ")"
    LBRACK = "["
    RBRACK = "]"
    LBRA = "{"
    RBRA = "}"
    SEM = ";"
    COMMA = ","
    DOT = "."
    HASH = "#"
    AT = "@"
    COLON = ":"
    QUEST = "?"

    EOF = "eof"


@dataclass(frozen=True)
class TokenInfo:
    file: Optional[str]
    line: int
    column: int


@dataclass(frozen=True)
class Token:
    literal: Optional[str]
    info: TokenInfo
    type: TokenType
