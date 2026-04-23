package io.github.sumaroder.rosenfeld.tokenize

import io.github.sumaroder.rosenfeld.error.ErrorHandler

class CharStream(val src: String) {
    private val length: Int = src.length
    private var idx: Int = 0
    var line: Int = 1
    var column: Int = 1
    private val linesStartIndices: List<Int>

    init {
        val indices = mutableListOf(0)
        for (i in src.indices) {
            if (src[i] == '\n') {
                indices.add(i + 1)
            }
        }
        linesStartIndices = indices
    }

    fun hasNext(): Boolean = idx < length

    fun peek(): Char = if (hasNext()) src[idx] else '\u0000'

    fun next(): Char {
        if (!hasNext()) return '\u0000'

        val c = src[idx]
        idx++

        if (c == '\n') {
            line++
            column = 1
        } else if (c == '\r') {
            if (hasNext() && src[idx] == '\n') idx++
            line++
            column = 1
        } else {
            column++
        }

        return c
    }

    fun getSourceLine(targetLine: Int): String? {
        val lineIndex = targetLine - 1
        if (lineIndex !in linesStartIndices.indices) return null
        val startPos = linesStartIndices[lineIndex]
        val endPos = if (lineIndex + 1 < linesStartIndices.size) linesStartIndices[lineIndex + 1] else src.length
        return src.substring(startPos, endPos).trimEnd('\n', '\r')
    }
}

object Tokenizer {
    private val keywordMap: Map<String, TokenType> = mapOf(
        "return" to TokenType.RETURN,
        "if" to TokenType.IF,
        "elif" to TokenType.ELIF,
        "else" to TokenType.ELSE,
        "loop" to TokenType.LOOP,
        "break" to TokenType.BREAK,
        "continue" to TokenType.CONTINUE,
        "init" to TokenType.INIT,
        "this" to TokenType.THIS,
        "import" to TokenType.IMPORT,
        "true" to TokenType.TRUE,
        "false" to TokenType.FALSE,
        "null" to TokenType.NULL,
        "getter" to TokenType.GETTER,
        "setter" to TokenType.SETTER,
        "pub" to TokenType.PUBLIC,
        "pri" to TokenType.PRIVATE,
        "const" to TokenType.CONST
    )

    private fun addToken(tokenList: MutableList<Token>, type: TokenType, info: TokenInfo, literal: String?) {
        tokenList.add(Token(literal, info, type))
    }

    private fun readString(cs: CharStream, info: TokenInfo, quote: Char): String {
        var closed = false
        val content = buildString {
            while (cs.hasNext()) {
                val ch = cs.next()
                if (ch == quote) {
                    closed = true
                    return@buildString
                }
                if (ch == '\\' && cs.hasNext()) {
                    val next = cs.next()
                    append(
                        when (next) {
                            'n' -> '\n'
                            'r' -> '\r'
                            't' -> '\t'
                            '\\', '"', '\'' -> next
                            else -> {
                                append('\\')
                                next
                            }
                        }
                    )
                } else {
                    append(ch)
                }
            }
        }
        if (!closed) {
            ErrorHandler.report(
                info = info,
                reason = "Unterminated String",
                sourceLine = cs.getSourceLine(info.line)
            )
        }
        return content
    }

    private fun readNumber(cs: CharStream, info: TokenInfo, first: Char): Pair<TokenType, String> {
        val sb = StringBuilder()
        sb.append(first)
        while (cs.peek().isDigit()) sb.append(cs.next())
        var isFloat = false
        if (cs.peek() == '.') {
            isFloat = true
            sb.append(cs.next())
            if (!cs.peek().isDigit()) {
                ErrorHandler.report(
                    info = info,
                    reason = "Invalid Float",
                    sourceLine = cs.getSourceLine(info.line)
                )
            } else {
                while (cs.peek().isDigit()) sb.append(cs.next())
            }
        }
        return (if (isFloat) TokenType.FLOAT else TokenType.INT) to sb.toString()
    }

    private fun readIdentifier(cs: CharStream, first: Char): String {
        val id = StringBuilder().append(first)
        while (cs.peek().isLetterOrDigit() || cs.peek() == '_') id.append(cs.next())
        return id.toString()
    }

    private fun handleOperatorOrDelimiter(
        c: Char,
        cs: CharStream,
        info: TokenInfo,
        tokenList: MutableList<Token>
    ): Boolean {
        when (c) {
            '+' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.ADD_ASSIGN, info, "+=")
                } else addToken(tokenList, TokenType.ADD, info, "+")
            }
            '-' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.MINUS_ASSIGN, info, "-=")
                } else if (cs.peek() == '>') {
                    cs.next()
                    addToken(tokenList, TokenType.ARROW, info, "->")
                } else addToken(tokenList, TokenType.MINUS, info, "-")
            }
            '=' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.EQ, info, "==")
                } else addToken(tokenList, TokenType.ASSIGN, info, "=")
            }
            '*' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.MULT_ASSIGN, info, "*=")
                } else addToken(tokenList, TokenType.MULT, info, "*")
            }
            '/' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.DIV_ASSIGN, info, "/=")
                } else if (cs.peek() == '/') {
                    cs.next()
                    while (cs.hasNext() && cs.peek() != '\n' && cs.peek() != '\r') cs.next()
                } else {
                    addToken(tokenList, TokenType.DIV, info, "/")
                }
            }
            '%' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.REM_ASSIGN, info, "%=")
                } else addToken(tokenList, TokenType.REM, info, "%")
            }
            '^' -> addToken(tokenList, TokenType.XOR, info, "^")
            '~' -> addToken(tokenList, TokenType.NOTB, info, "~")
            '&', '|', '>', '<' -> {
                if (cs.peek() == c) {
                    cs.next()
                    val type: TokenType = when (c) {
                        '&' -> TokenType.ANDL
                        '|' -> TokenType.ORL
                        '>' -> TokenType.SHIFTR
                        else -> TokenType.SHIFTL
                    }
                    addToken(tokenList, type, info, "$c$c")
                } else if ((c == '>' || c == '<') && cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, if (c == '>') TokenType.GE else TokenType.LE, info, "$c=")
                } else {
                    val type: TokenType = when (c) {
                        '&' -> TokenType.ANDB
                        '|' -> TokenType.ORB
                        '>' -> TokenType.GT
                        else -> TokenType.LT
                    }
                    addToken(tokenList, type, info, "$c")
                }
            }
            '!' -> {
                if (cs.peek() == '=') {
                    cs.next()
                    addToken(tokenList, TokenType.NE, info, "!=")
                } else {
                    addToken(tokenList, TokenType.NOTL, info, "!")
                }
            }
            '(' -> addToken(tokenList, TokenType.LPAR, info, "(")
            ')' -> addToken(tokenList, TokenType.RPAR, info, ")")
            '[' -> addToken(tokenList, TokenType.LBRACK, info, "[")
            ']' -> addToken(tokenList, TokenType.RBRACK, info, "]")
            '{' -> addToken(tokenList, TokenType.LBRA, info, "{")
            '}' -> addToken(tokenList, TokenType.RBRA, info, "}")
            ';' -> addToken(tokenList, TokenType.SEM, info, ";")
            ',' -> addToken(tokenList, TokenType.COMMA, info, ",")
            '.' -> addToken(tokenList, TokenType.DOT, info, ".")
            '#' -> addToken(tokenList, TokenType.HASH, info, "#")
            ':' -> addToken(tokenList, TokenType.COLON, info, ":")
            '?' -> addToken(tokenList, TokenType.QUEST, info, "?")
            else -> return false
        }
        return true
    }

    fun tokenize(src: String, fileName: String? = null): MutableList<Token> {
        val tokenList = mutableListOf<Token>()
        val cs = CharStream(src)
        while (cs.hasNext()) {
            val info = TokenInfo(fileName, cs.line, cs.column)
            val c = cs.next()
            when (c) {
                ' ', '\t', '\r', '\n' -> { }
                '/' -> {
                    if (cs.peek() == '/') {
                        cs.next()
                        while (cs.hasNext() && cs.peek() != '\n' && cs.peek() != '\r') cs.next()
                    } else {
                        addToken(tokenList, TokenType.DIV, info, "/")
                    }
                }
                '"', '\'' -> {
                    val content = readString(cs, info, c)
                    addToken(tokenList, TokenType.STRING, info, content)
                }
                else -> {
                    when {
                        c.isDigit() -> {
                            val (type, literal) = readNumber(cs, info, c)
                            addToken(tokenList, type, info, literal)
                        }
                        c.isLetter() || c == '_' -> {
                            val lex = readIdentifier(cs, c)
                            addToken(tokenList, keywordMap[lex] ?: TokenType.ID, info, lex)
                        }
                        handleOperatorOrDelimiter(c, cs, info, tokenList) -> { }
                        else -> ErrorHandler.report(
                            info = info,
                            reason = "Unexpected Char",
                            sourceLine = cs.getSourceLine(info.line)
                        )
                    }
                }
            }
        }
        addToken(tokenList, TokenType.EOF, TokenInfo(fileName, 0, 0), null)
        return tokenList
    }
}