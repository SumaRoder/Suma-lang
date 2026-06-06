from dataclasses import dataclass
from enum import Enum


class TokenType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    RAW_STRING = "raw_string"
    TRUE = "true"
    FALSE = "false"
    NULL = "null"

    ID = "id"
    RETURN = "return"
    IF = "if"
    ELIF = "elif"
    ELSE = "else"
    WHILE = "while"
    FOR = "for"
    IN = "in"
    LOOP = "loop"
    BREAK = "break"
    CONTINUE = "continue"
    INIT = "init"
    THIS = "this"
    IMPORT = "import"
    PUBLIC = "pub"
    PRIVATE = "pri"
    CONST = "const"
    STATIC = "static"
    IS = "is"
    ENUM = "enum"
    MATCH = "match"
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
    FAT_ARROW = "=>"
    RANGE = ".."
    RANGE_INCLUSIVE = "..="
    PLUSPLUS = "++"
    MINUSMINUS = "--"
    NULL_COALESCE = "??"

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
    file: str | None
    line: int
    column: int


@dataclass(frozen=True)
class Token:
    literal: str | None
    info: TokenInfo
    type: TokenType
