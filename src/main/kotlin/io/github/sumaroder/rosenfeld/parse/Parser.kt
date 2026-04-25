package io.github.sumaroder.rosenfeld.parse

import io.github.sumaroder.rosenfeld.ast.*
import io.github.sumaroder.rosenfeld.error.ErrorHandler
import io.github.sumaroder.rosenfeld.tokenize.Token
import io.github.sumaroder.rosenfeld.tokenize.TokenInfo
import io.github.sumaroder.rosenfeld.tokenize.TokenType
import io.github.sumaroder.rosenfeld.tokenize.TokenType.*

class Parser(private val tokens: List<Token>) {
    private var current = 0

    private fun peek(): Token = tokens[current]
    private fun previous(): Token = tokens[current - 1]

    private fun isAtEnd(): Boolean = peek().type == EOF

    private fun advance(): Token {
        if (!isAtEnd()) current++
        return previous()
    }

    private fun check(type: TokenType): Boolean {
        return if (isAtEnd()) false else peek().type == type
    }

    private fun checkNext(type: TokenType): Boolean {
        return if (current + 1 >= tokens.size) false else tokens[current + 1].type == type
    }

    private fun match(vararg types: TokenType): Boolean {
        for (type in types) {
            if (check(type)) {
                advance()
                return true
            }
        }
        return false
    }

    private fun expect(type: TokenType, message: String): Token {
        if (check(type)) return advance()
        error(peek().info, message)
        return previous()
    }

    private fun error(info: TokenInfo, message: String): Nothing {
        ErrorHandler.report(info, message, null)
        throw ParseException(message)
    }

    fun parse(): Program {
        val declarations = mutableListOf<Decl>()
        while (!isAtEnd()) {
            declarations.add(parseDeclaration())
        }
        return Program(declarations, TokenInfo(null, 1, 1))
    }

    private fun parseDeclaration(): Decl {
        return when {
            check(PUBLIC) || check(PRIVATE) -> {
                val access = advance()
                when {
                    check(ID) && peekNext().type == LBRA -> parseClass(access.type == PUBLIC)
                    check(ID) && peekNext().type == LPAR -> parseFunction(access.type == PUBLIC)
                    else -> error(peek().info, "expected class or function declaration after access modifier")
                }
            }
            check(IMPORT) -> parseImport()
            check(ID) && peekNext().type == LPAR -> parseFunction(true)
            check(ID) && peekNext().type == LBRA -> parseClass(true)
            else -> error(peek().info, "expected declaration")
        }
    }

    private fun peekNext(): Token {
        return if (current + 1 < tokens.size) tokens[current + 1] else tokens.last()
    }

    private fun peekNextNext(): Token {
        return if (current + 2 < tokens.size) tokens[current + 2] else tokens.last()
    }

    private fun isClassMethodFollowing(): Boolean {
        return when (peekNext().type) {
            LPAR -> true
            COLON -> {
                val afterColon = peekNextNext()
                afterColon.type == LPAR ||
                (afterColon.type == ID && tokens.getOrNull(current + 4)?.type == LPAR)
            }
            else -> false
        }
    }

    private fun isMethodAfterType(): Boolean {
        return tokens.getOrNull(current + 1)?.type == LPAR
    }

    private fun parseImport(): ImportDecl {
        val info = advance().info
        val path = expect(STRING, "expected import path").literal!!
        return ImportDecl(path, info)
    }

    private fun parseClass(isPublic: Boolean): ClassDecl {
        val name = expect(ID, "expected class name").literal!!
        expect(LBRA, "expected '{' after class name")

        val members = mutableListOf<ClassMember>()
        while (!check(RBRA) && !isAtEnd()) {
            members.add(parseClassMember())
        }
        val info = expect(RBRA, "expected '}' after class body").info

        return ClassDecl(name, isPublic, members, info)
    }

    private fun parseClassMember(): ClassMember {
        val isPublic = when {
            match(PUBLIC) -> true
            match(PRIVATE) -> false
            else -> false
        }
        val isConst = match(CONST)
    
        val isMethod = isClassMethodFollowing()
    
        return when {
            check(INIT) -> parseConstructor(isPublic)
            isMethod -> parseMethod(isPublic)
            else -> {
                val name = expect(ID, "expected property name").literal!!
                
                val typeAnnotation: String? = if (match(COLON)) {
                    parseTypeAnnotation()
                } else null
                
                val initializer: Expr? = if (match(ASSIGN)) {
                    parseExpression()
                } else null
                
                if (typeAnnotation == null && initializer == null) {
                    error(peek().info, "Property '$name' must have either type annotation or initializer")
                }
                
                var getter: GetterDecl? = null
                var setter: SetterDecl? = null
    
                while (match(DOT)) {
                    when {
                        match(GETTER) -> {
                            getter = if (match(ASSIGN)) {
                                GetterDecl(parseExpression(), true, peek().info)
                            } else if (check(LBRA)) {
                                val block = parseBlock()
                                GetterDecl(BlockExpr(block), false, block.info)
                            } else {
                                GetterDecl(Identifier("__field__", peek().info), true, peek().info)
                            }
                        }
                        match(SETTER) -> {
                            setter = if (check(LBRA)) {
                                SetterDecl(parseBlock(), peek().info)
                            } else {
                                SetterDecl(null, peek().info)
                            }
                        }
                        else -> error(peek().info, "expected 'getter' or 'setter'")
                    }
                }
    
                PropertyDecl(name, typeAnnotation, initializer, isPublic, isConst, getter, setter, peek().info)
            }
        }
    }

    private fun parseConstructor(isPublic: Boolean): MethodDecl {
        val info = advance().info
        val params = parseParameters()

        val body = if (check(ASSIGN)) {
            advance()
            BlockStmt(listOf(ReturnStmt(parseExpression(), peek().info)), peek().info)
        } else if (check(LBRA)) {
            parseBlock()
        } else {
            error(peek().info, "expected '=' or '{' after constructor parameters")
        }

        return MethodDecl("init", params, null, body, isPublic, true, info)
    }

    private fun parseMethod(isPublic: Boolean): MethodDecl {
        val name = expect(ID, "expected method name").literal!!
        val params = parseParameters()
        val returnType = if (match(COLON)) {
            parseTypeAnnotation()
        } else null

        val body = if (check(ASSIGN)) {
            advance()
            BlockStmt(listOf(ReturnStmt(parseExpression(), peek().info)), peek().info)
        } else if (check(LBRA)) {
            parseBlock()
        } else {
            error(peek().info, "expected '=' or '{' after method signature")
        }

        return MethodDecl(name, params, returnType, body, isPublic, false, peek().info)
    }

    private fun parseProperty(isPublic: Boolean, isConst: Boolean = false): PropertyDecl {
        val name = expect(ID, "expected property name").literal!!
    
        val typeAnnotation: String? = if (match(COLON)) {
            parseTypeAnnotation()
        } else null
    
        val initializer: Expr? = if (match(ASSIGN)) {
            parsePropertyInitializer()
        } else null
    
        if (typeAnnotation == null && initializer == null) {
            error(peek().info, "Property '$name' must have either a type annotation or an initializer")
        }
    
        var getter: GetterDecl? = null
        var setter: SetterDecl? = null
    
        while (match(DOT)) {
            when {
                match(GETTER) -> {
                    getter = if (match(ASSIGN)) {
                        GetterDecl(parseExpression(), true, peek().info)
                    } else if (check(LBRA)) {
                        val block = parseBlock()
                        GetterDecl(BlockExpr(block), false, block.info)
                    } else {
                        GetterDecl(Identifier("__field__", peek().info), true, peek().info)
                    }
                }
                match(SETTER) -> {
                    setter = if (check(LBRA)) {
                        SetterDecl(parseBlock(), peek().info)
                    } else {
                        SetterDecl(null, peek().info)
                    }
                }
                else -> error(peek().info, "expected 'getter' or 'setter'")
            }
        }
    
        return PropertyDecl(name, typeAnnotation, initializer, isPublic, isConst, getter, setter, peek().info)
    }

    private fun parsePropertyInitializer(): Expr {
        return parseAssignment()
    }

    private fun parseFunction(isPublic: Boolean): FunctionDecl {
        val name = expect(ID, "expected function name").literal!!
        val params = parseParameters()

        val returnType = if (match(COLON)) {
            parseTypeAnnotation()
        } else null

        val body = if (check(ASSIGN)) {
            advance()
            BlockStmt(listOf(ReturnStmt(parseExpression(), peek().info)), peek().info)
        } else if (check(LBRA)) {
            parseBlock()
        } else {
            error(peek().info, "expected '=' or '{' after function signature")
        }

        return FunctionDecl(name, params, returnType, body, isPublic, peek().info)
    }

    private fun parseParameters(): List<Parameter> {
        expect(LPAR, "expected '('")
        val params = mutableListOf<Parameter>()

        while (!check(RPAR) && !isAtEnd()) {
            val name = expect(ID, "expected parameter name").literal!!
            val isOptional = match(QUEST)
            val typeAnnotation = if (match(COLON)) parseTypeAnnotation() else null
            val defaultValue = if (match(ASSIGN)) parseExpression() else null

            params.add(Parameter(name, typeAnnotation, defaultValue, isOptional))

            if (!match(COMMA)) break
        }

        expect(RPAR, "expected ')'")
        return params
    }

    private fun parseTypeAnnotation(): String {
        val sb = StringBuilder()
        if (check(ID)) {
            sb.append(advance().literal)
            if (match(LT)) {
                sb.append("<")
                while (!check(GT) && !isAtEnd()) {
                    sb.append(parseTypeAnnotation())
                    if (match(COMMA)) sb.append(", ")
                }
                expect(GT, "expected '>'")
                sb.append(">")
            }
        }
        return sb.toString()
    }

    private fun parseStatement(): Stmt {
        return when {
            check(LBRA) -> parseBlock()
            check(IF) -> parseIf()
            check(LOOP) -> parseLoop()
            check(RETURN) -> parseReturn()
            check(BREAK) -> BreakStmt(advance().info)
            check(CONTINUE) -> ContinueStmt(advance().info)
            check(ID) && peekNext().type == COLON -> parseVarDecl()
            else -> parseExprStmt()
        }
    }

        private fun parseBlock(): BlockStmt {
            val info = advance().info
            val statements = mutableListOf<Stmt>()
            while (!check(RBRA) && !isAtEnd()) {
                statements.add(parseStatement())
            }
            expect(RBRA, "expected '}'")
            return BlockStmt(statements, info)
        }
    
    private fun parseVarDecl(): VarDecl {
        val nameTok = advance()
        val name = nameTok.literal!!
        val info = nameTok.info
        
        val typeAnnotation: String? = if (check(COLON)) {
            advance()
            parseTypeAnnotation()
        } else null
        
        val varInit: Expr? = if (match(ASSIGN)) {
            parseExpression()
        } else null
        
        if (typeAnnotation == null && varInit == null) {
            error(info, "Variable '$name' must have either type annotation or initializer")
        }
        
        return VarDecl(name, typeAnnotation, varInit, true, false, info)
    }

    private fun parseVarStmt(): VarStmt {
        val nameTok = advance()
        val name = nameTok.literal!!
        
        val typeAnnotation: String? = if (check(COLON)) {
            advance()
            parseTypeAnnotation()
        } else null
        
        expect(ASSIGN, "Variable declaration must have an initializer")
        val initializer = parseExpression()
        
        return VarStmt(name, typeAnnotation, initializer, nameTok.info)
    }

    private fun parseIf(): IfStmt {
        val info = advance().info
        val condition = parseExpression()
        val thenBranch = parseStatement()
        val elseBranch = if (match(ELSE)) parseStatement() else null
        return IfStmt(condition, thenBranch, elseBranch, info)
    }

    private fun parseLoop(): LoopStmt {
        val info = advance().info
        val body = parseStatement()
        return LoopStmt(body, info)
    }

    private fun parseReturn(): ReturnStmt {
        val info = advance().info
        val value = if (!check(RBRA) && !check(SEM) && !isAtEnd()) parseExpression() else null
        return ReturnStmt(value, info)
    }

    private fun parseExprStmt(): ExprStmt {
        val expr = parseExpression()
        return ExprStmt(expr, expr.info)
    }

    private fun parseExpression(): Expr {
        return parseAssignment()
    }

    private fun parseAssignment(): Expr {
        val expr = parseArrowMatch()

        when {
            match(ASSIGN) -> {
                val value = parseAssignment()
                return when (expr) {
                    is Identifier -> BinaryExpr(expr, BinaryOp.ASSIGN, value, expr.info)
                    is MemberExpr -> BinaryExpr(expr, BinaryOp.ASSIGN, value, expr.info)
                    is IndexExpr -> BinaryExpr(expr, BinaryOp.ASSIGN, value, expr.info)
                    else -> error(expr.info, "Invalid assignment target")
                }
            }
            match(ADD_ASSIGN) -> return parseCompoundAssign(expr, BinaryOp.ADD)
            match(MINUS_ASSIGN) -> return parseCompoundAssign(expr, BinaryOp.MINUS)
            match(MULT_ASSIGN) -> return parseCompoundAssign(expr, BinaryOp.MULT)
            match(DIV_ASSIGN) -> return parseCompoundAssign(expr, BinaryOp.DIV)
            match(REM_ASSIGN) -> return parseCompoundAssign(expr, BinaryOp.REM)
        }
        return expr
    }

    private fun parseCompoundAssign(target: Expr, op: BinaryOp): Expr {
        val value = parseAssignment()
        return when (target) {
            is Identifier -> BinaryExpr(target, BinaryOp.ASSIGN, BinaryExpr(target, op, value, target.info), target.info)
            is MemberExpr -> BinaryExpr(target, BinaryOp.ASSIGN, BinaryExpr(target, op, value, target.info), target.info)
            is IndexExpr -> BinaryExpr(target, BinaryOp.ASSIGN, BinaryExpr(target, op, value, target.info), target.info)
            else -> error(target.info, "Invalid assignment target")
        }
    }

    private fun parseArrowMatch(): Expr {
        val expr = parseElvis()

        if (match(ARROW)) {
            val branches = mutableListOf<MatchBranch>()
            expect(LBRA, "expected '{' after '->'")

            while (!check(RBRA) && !isAtEnd()) {
                val pattern = expect(ID, "expected pattern name").literal!!

                if (check(LBRA)) {
                    val block = parseBlock()
                    branches.add(MatchBranch(pattern, BlockExpr(block), true))
                } else if (match(ASSIGN)) {
                    val body = parseExpression()
                    branches.add(MatchBranch(pattern, body, false))
                } else {
                    error(peek().info, "expected '{' or '=' after pattern")
                }
            }

            expect(RBRA, "expected '}' after match branches")
            return ArrowMatchExpr(expr, branches, expr.info)
        }

        return expr
    }

    private fun parseElvis(): Expr {
        var expr = parseOr()

        if (match(QUEST)) {
            if (match(ASSIGN)) {
                val right = parseElvis()
                expr = ElvisExpr(expr, right, expr.info)
            } else {
                val thenExpr = parseExpression()
                expect(COLON, "expected ':' after '?' in conditional expression")
                val elseExpr = parseElvis()
                expr = ConditionalExpr(expr, thenExpr, elseExpr, expr.info)
            }
        }

        return expr
    }

    private fun parseOr(): Expr {
        var expr = parseAnd()

        while (match(ORL)) {
            val right = parseAnd()
            expr = BinaryExpr(expr, BinaryOp.ORL, right, expr.info)
        }

        return expr
    }

    private fun parseAnd(): Expr {
        var expr = parseEquality()

        while (match(ANDL)) {
            val right = parseEquality()
            expr = BinaryExpr(expr, BinaryOp.ANDL, right, expr.info)
        }

        return expr
    }

    private fun parseEquality(): Expr {
        var expr = parseComparison()

        while (match(EQ, NE)) {
            val op = if (previous().type == EQ) BinaryOp.EQ else BinaryOp.NE
            val right = parseComparison()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseComparison(): Expr {
        var expr = parseBitwise()

        while (match(GT, GE, LT, LE)) {
            val op = when (previous().type) {
                GT -> BinaryOp.GT
                GE -> BinaryOp.GE
                LT -> BinaryOp.LT
                LE -> BinaryOp.LE
                else -> throw IllegalStateException()
            }
            val right = parseBitwise()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseBitwise(): Expr {
        var expr = parseShift()

        while (match(ANDB, ORB, XOR)) {
            val op = when (previous().type) {
                ANDB -> BinaryOp.ANDB
                ORB -> BinaryOp.ORB
                XOR -> BinaryOp.XOR
                else -> throw IllegalStateException()
            }
            val right = parseShift()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseShift(): Expr {
        var expr = parseAdditive()

        while (match(SHIFTL, SHIFTR)) {
            val op = if (previous().type == SHIFTL) BinaryOp.SHIFTL else BinaryOp.SHIFTR
            val right = parseAdditive()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseAdditive(): Expr {
        var expr = parseMultiplicative()

        while (match(ADD, MINUS)) {
            val op = if (previous().type == ADD) BinaryOp.ADD else BinaryOp.MINUS
            val right = parseMultiplicative()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseMultiplicative(): Expr {
        var expr = parseUnary()

        while (match(MULT, DIV, REM)) {
            val op = when (previous().type) {
                MULT -> BinaryOp.MULT
                DIV -> BinaryOp.DIV
                REM -> BinaryOp.REM
                else -> throw IllegalStateException()
            }
            val right = parseUnary()
            expr = BinaryExpr(expr, op, right, expr.info)
        }

        return expr
    }

    private fun parseUnary(): Expr {
        if (match(MINUS, NOTL, NOTB)) {
            val op = when (previous().type) {
                MINUS -> UnaryOp.MINUS
                NOTL -> UnaryOp.NOTL
                NOTB -> UnaryOp.NOTB
                else -> throw IllegalStateException()
            }
            val operand = parseUnary()
            return UnaryExpr(op, operand, previous().info)
        }

        return parsePostfix()
    }

    private fun parsePostfix(): Expr {
        var expr = parsePrimary()

        while (true) {
            expr = when {
                match(LPAR) -> {
                    val args = mutableListOf<Expr>()
                    while (!check(RPAR) && !isAtEnd()) {
                        args.add(parseExpression())
                        if (!match(COMMA)) break
                    }
                    expect(RPAR, "expected ')'")
                    CallExpr(expr, args, expr.info)
                }
                check(DOT) && (peekNext().type == GETTER || peekNext().type == SETTER) -> {
                    return expr
                }
                match(DOT) -> {
                    val name = expect(ID, "expected property name").literal!!
                    MemberExpr(expr, name, expr.info)
                }
                match(LBRACK) -> {
                    val index = parseExpression()
                    expect(RBRACK, "expected ']'")
                    IndexExpr(expr, index, expr.info)
                }
                check(QUEST) && checkNext(DOT) -> {
                    advance()
                    advance()
                    val name = expect(ID, "expected property name").literal!!
                    SafeCallExpr(expr, MemberExpr(expr, name, expr.info), expr.info)
                }
                else -> break
            }
        }

        return expr
    }

    private fun parsePrimary(): Expr {
        return when {
            match(TRUE) -> BoolLiteral(true, previous().info)
            match(FALSE) -> BoolLiteral(false, previous().info)
            match(NULL) -> NullLiteral(previous().info)
            match(THIS) -> ThisExpr(previous().info)
            match(INT) -> IntLiteral(previous().literal!!.toLong(), previous().info)
            match(FLOAT) -> FloatLiteral(previous().literal!!.toDouble(), previous().info)
            match(STRING) -> StringLiteral(previous().literal!!, previous().info)
            match(ID) -> Identifier(previous().literal!!, previous().info)
            match(LPAR) -> {
                val expr = parseExpression()
                expect(RPAR, "expected ')'")
                expr
            }
            else -> error(peek().info, "Unexpected token: ${peek().type}")
        }
    }
}

class ParseException(message: String) : Exception(message)
