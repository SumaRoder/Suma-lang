package io.github.sumaroder.rosenfeld.tokenize

data class TokenInfo(val file: String?, val line: Int, val column: Int) {
    override fun toString(): String = if (file != null) "$file:$line:$column" else "$line:$column"
}

enum class TokenType {
    ID, INT, FLOAT, STRING, NULL,
    ADD, MINUS, MULT, DIV, REM,
    ANDB, ORB, NOTB, XOR, SHIFTL, SHIFTR,
    GT, LT, GE, LE, EQ, NE,
    ANDL, ORL, NOTL,
    ASSIGN, ADD_ASSIGN, MINUS_ASSIGN, MULT_ASSIGN, DIV_ASSIGN, REM_ASSIGN,
    LPAR, RPAR, LBRACK, RBRACK, LBRA, RBRA,
    DOT, SEM, COMMA, HASH, ARROW, COLON, QUEST,
    RETURN, IF, ELIF, ELSE, LOOP, BREAK, CONTINUE, INIT, THIS, IMPORT,
    TRUE, FALSE, PUBLIC, PRIVATE, SETTER, GETTER, CONST,
    EOF
}

data class Token(
    var literal: String?,
    val info: TokenInfo,
    val type: TokenType,
) {
    override fun toString(): String = "TOKEN[$type]($literal) @ $info"
}