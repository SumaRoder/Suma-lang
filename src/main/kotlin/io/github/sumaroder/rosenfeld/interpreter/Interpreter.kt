package io.github.sumaroder.rosenfeld.interpreter

import io.github.sumaroder.rosenfeld.ast.*
import io.github.sumaroder.rosenfeld.tokenize.TokenInfo
import kotlin.math.pow

class Interpreter {
    private val globals = Environment()
    private var environment = globals
    private val locals = mutableMapOf<Expr, Int>()

    init {
        defineNativeFunctions()
    }

    fun interpret(program: Program) {
        try {
            for (decl in program.declarations) {
                executeDeclaration(decl)
            }
        } catch (e: ReturnException) {
        }
    }

    private fun executeDeclaration(decl: Decl) {
        when (decl) {
            is FunctionDecl -> {
                val function = FunctionValue(
                    decl.name,
                    decl.params,
                    decl.body,
                    environment
                )
                environment.define(decl.name, function)
            }
            is ClassDecl -> {
                val methods = mutableMapOf<String, FunctionValue>()
                val properties = mutableMapOf<String, PropertyDecl>()
                var init: FunctionValue? = null

                for (member in decl.members) {
                    when (member) {
                        is MethodDecl -> {
                            val fn = FunctionValue(
                                member.name,
                                member.params,
                                member.body!!,
                                environment,
                                member.isInit
                            )
                            if (member.isInit) {
                                init = fn
                            } else {
                                methods[member.name] = fn
                            }
                        }
                        is PropertyDecl -> {
                            properties[member.name] = member
                        }
                    }
                }

                val clazz = ClassValue(decl.name, methods, properties, init)
                environment.define(decl.name, clazz)
            }
            is VarDecl -> {
                val value = decl.initializer?.let { evaluate(it) } ?: NullValue
                environment.define(decl.name, value)
            }
            is ImportDecl -> {
            }
            is Stmt -> execute(decl)
        }
    }

    fun execute(stmt: Stmt) {
        when (stmt) {
            is ExprStmt -> evaluate(stmt.expr)
            is BlockStmt -> {
                val previous = environment
                environment = Environment(previous)
                try {
                    for (s in stmt.statements) {
                        execute(s)
                    }
                } finally {
                    environment = previous
                }
            }
            is IfStmt -> {
                if (evaluate(stmt.condition).isTruthy()) {
                    execute(stmt.thenBranch)
                } else if (stmt.elseBranch != null) {
                    execute(stmt.elseBranch)
                }
            }
            is LoopStmt -> {
                while (true) {
                    try {
                        execute(stmt.body)
                    } catch (e: BreakException) {
                        break
                    } catch (e: ContinueException) {
                        continue
                    }
                }
            }
            is ReturnStmt -> {
                val value = stmt.value?.let { evaluate(it) } ?: NullValue
                throw ReturnException(value)
            }
            is BreakStmt -> throw BreakException()
            is ContinueStmt -> throw ContinueException()
            is VarDecl -> executeDeclaration(stmt)
            is VarStmt -> {
                val value = evaluate(stmt.initializer)
                environment.define(stmt.name, value)
            }
            else -> throw RuntimeException("Unknown statement type: ${stmt.javaClass}")
        }
    }

    fun evaluate(expr: Expr): RosenfeldValue {
        return when (expr) {
            is io.github.sumaroder.rosenfeld.ast.BlockExpr -> {
                var result: RosenfeldValue = NullValue
                for (stmt in expr.block.statements) {
                    result = when (stmt) {
                        is ExprStmt -> evaluate(stmt.expr)
                        else -> {
                            execute(stmt)
                            NullValue
                        }
                    }
                }
                result
            }
            is IntLiteral -> IntValue(expr.value)
            is FloatLiteral -> FloatValue(expr.value)
            is StringLiteral -> StringValue(expr.value)
            is BoolLiteral -> BoolValue(expr.value)
            is NullLiteral -> NullValue
            is Identifier -> environment.get(expr.name)
            is ThisExpr -> environment.get("this")
            is ItExpr -> environment.get("it")
            is BinaryExpr -> evaluateBinary(expr)
            is UnaryExpr -> evaluateUnary(expr)
            is CallExpr -> evaluateCall(expr)
            is MemberExpr -> evaluateMember(expr)
            is IndexExpr -> evaluateIndex(expr)
            is ConditionalExpr -> {
                if (evaluate(expr.condition).isTruthy()) evaluate(expr.thenExpr)
                else evaluate(expr.elseExpr)
            }
            is ElvisExpr -> {
                val left = evaluate(expr.left)
                if (left != NullValue) left else evaluate(expr.right)
            }
            is SafeCallExpr -> {
                val obj = evaluate((expr.obj as MemberExpr).obj)
                if (obj == NullValue) NullValue
                else evaluate(expr.call)
            }
            is ArrowMatchExpr -> evaluateArrowMatch(expr)
            else -> throw RuntimeException("Unknown expression type: ${expr.javaClass}")
        }
    }

    private fun evaluateBinary(expr: BinaryExpr): RosenfeldValue {
        if (expr.operator == BinaryOp.ANDL) {
            val left = evaluate(expr.left)
            return if (left.isTruthy()) evaluate(expr.right) else left
        }
        if (expr.operator == BinaryOp.ORL) {
            val left = evaluate(expr.left)
            return if (left.isTruthy()) left else evaluate(expr.right)
        }
        
        if (expr.operator == BinaryOp.ASSIGN) {
            val right = evaluate(expr.right)
            return when (val l = expr.left) {
                is Identifier -> {
                    if (!environment.contains(l.name)) {
                        environment.define(l.name, right)
                    } else {
                        environment.assign(l.name, right)
                    }
                    right
                }
                is MemberExpr -> {
                    val obj = evaluate(l.obj)
                    if (obj is InstanceValue) {
                        obj.set(l.property, right, this)
                        right
                    } else throw RuntimeException("Cannot assign to member of ${obj.typeName()}")
                }
                is IndexExpr -> {
                    val obj = evaluate(l.obj)
                    val index = evaluate(l.index)
                    when {
                        obj is ListValue && index is IntValue -> {
                            val i = index.value.toInt()
                            if (i < 0 || i >= obj.elements.size) {
                                throw RuntimeException("Index out of bounds: $i")
                            }
                            obj.elements[i] = right
                            right
                        }
                        else -> throw RuntimeException("Cannot index ${obj.typeName()} with ${index.typeName()}")
                    }
                }
                else -> throw RuntimeException("Invalid assignment target")
            }
        }
        
        val left = evaluate(expr.left)
        val right = evaluate(expr.right)
        
        return when (expr.operator) {
            BinaryOp.ADD -> when {
                left is IntValue && right is IntValue -> IntValue(left.value + right.value)
                left is FloatValue && right is FloatValue -> FloatValue(left.value + right.value)
                left is IntValue && right is FloatValue -> FloatValue(left.value + right.value)
                left is FloatValue && right is IntValue -> FloatValue(left.value + right.value)
                left is StringValue || right is StringValue -> StringValue(left.toDisplayString() + right.toDisplayString())
                else -> throw RuntimeException("Cannot add ${left.typeName()} and ${right.typeName()}")
            }
            BinaryOp.MINUS -> numericOp(left, right, "subtract") { a, b -> a - b }
            BinaryOp.MULT -> numericOp(left, right, "multiply") { a, b -> a * b }
            BinaryOp.DIV -> when {
                left is IntValue && right is IntValue -> {
                    if (right.value == 0L) throw RuntimeException("Division by zero")
                    IntValue(left.value / right.value)
                }
                else -> numericOp(left, right, "divide") { a, b -> 
                    if (b == 0.0) throw RuntimeException("Division by zero")
                    a / b 
                }
            }
            BinaryOp.REM -> numericOp(left, right, "modulo") { a, b -> a % b }
            BinaryOp.ANDB -> IntValue(toInt(left) and toInt(right))
            BinaryOp.ORB -> IntValue(toInt(left) or toInt(right))
            BinaryOp.XOR -> IntValue(toInt(left) xor toInt(right))
            BinaryOp.SHIFTL -> IntValue(toInt(left) shl toInt(right).toInt())
            BinaryOp.SHIFTR -> IntValue(toInt(left) shr toInt(right).toInt())
            BinaryOp.GT -> BoolValue(compareValues(left, right) > 0)
            BinaryOp.GE -> BoolValue(compareValues(left, right) >= 0)
            BinaryOp.LT -> BoolValue(compareValues(left, right) < 0)
            BinaryOp.LE -> BoolValue(compareValues(left, right) <= 0)
            BinaryOp.EQ -> BoolValue(isEqual(left, right))
            BinaryOp.NE -> BoolValue(!isEqual(left, right))
            else -> throw RuntimeException("Unknown binary operator: ${expr.operator}")
        }
    }

    private fun numericOp(
        left: RosenfeldValue,
        right: RosenfeldValue,
        op: String,
        fn: (Double, Double) -> Double
    ): RosenfeldValue {
        val a = toDouble(left)
        val b = toDouble(right)
        val result = fn(a, b)
        return if (left is IntValue && right is IntValue && op != "divide") {
            IntValue(result.toLong())
        } else {
            FloatValue(result)
        }
    }

    private fun toInt(value: RosenfeldValue): Long {
        return when (value) {
            is IntValue -> value.value
            is FloatValue -> value.value.toLong()
            else -> throw RuntimeException("Expected number, got ${value.typeName()}")
        }
    }

    private fun toDouble(value: RosenfeldValue): Double {
        return when (value) {
            is IntValue -> value.value.toDouble()
            is FloatValue -> value.value
            else -> throw RuntimeException("Expected number, got ${value.typeName()}")
        }
    }

    private fun compareValues(left: RosenfeldValue, right: RosenfeldValue): Int {
        return when {
            left is IntValue && right is IntValue -> left.value.compareTo(right.value)
            left is FloatValue && right is FloatValue -> left.value.compareTo(right.value)
            left is IntValue && right is FloatValue -> left.value.toDouble().compareTo(right.value)
            left is FloatValue && right is IntValue -> left.value.compareTo(right.value.toDouble())
            left is StringValue && right is StringValue -> left.value.compareTo(right.value)
            else -> throw RuntimeException("Cannot compare ${left.typeName()} and ${right.typeName()}")
        }
    }

    private fun isEqual(left: RosenfeldValue, right: RosenfeldValue): Boolean {
        return when {
            left is NullValue && right is NullValue -> true
            left is NullValue || right is NullValue -> false
            left is IntValue && right is IntValue -> left.value == right.value
            left is FloatValue && right is FloatValue -> left.value == right.value
            left is IntValue && right is FloatValue -> left.value.toDouble() == right.value
            left is FloatValue && right is IntValue -> left.value == right.value.toDouble()
            left is StringValue && right is StringValue -> left.value == right.value
            left is BoolValue && right is BoolValue -> left.value == right.value
            else -> left == right
        }
    }

    private fun evaluateUnary(expr: UnaryExpr): RosenfeldValue {
        val operand = evaluate(expr.operand)
        return when (expr.operator) {
            UnaryOp.MINUS -> when (operand) {
                is IntValue -> IntValue(-operand.value)
                is FloatValue -> FloatValue(-operand.value)
                else -> throw RuntimeException("Cannot negate ${operand.typeName()}")
            }
            UnaryOp.NOTL -> BoolValue(!operand.isTruthy())
            UnaryOp.NOTB -> IntValue(toInt(operand).inv())
        }
    }

    private fun evaluateCall(expr: CallExpr): RosenfeldValue {
        val callee = evaluate(expr.callee)
        val arguments = expr.arguments.map { evaluate(it) }

        return when (callee) {
            is FunctionValue -> callFunction(callee, arguments)
            is ClassValue -> callee.call(this, arguments)
            is NativeFunction -> callee.call(this, arguments)
            else -> throw RuntimeException("Cannot call ${callee.typeName()}")
        }
    }

    fun callFunction(function: FunctionValue, arguments: List<RosenfeldValue>): RosenfeldValue {
        val env = Environment(function.closure)

        for (i in function.params.indices) {
            val param = function.params[i]
            val value = if (i < arguments.size) {
                arguments[i]
            } else {
                param.defaultValue?.let { evaluate(it) }
                    ?: throw RuntimeException("Missing argument for parameter '${param.name}'")
            }
            env.define(param.name, value)
        }

        val previous = environment
        environment = env
        try {
            execute(function.body)
            return if (function.isInit) {
                function.closure.get("this")
            } else {
                NullValue
            }
        } catch (e: ReturnException) {
            return if (function.isInit) {
                function.closure.get("this")
            } else {
                e.value
            }
        } finally {
            environment = previous
        }
    }

    private fun evaluateMember(expr: MemberExpr): RosenfeldValue {
        val obj = evaluate(expr.obj)

        return when (obj) {
            is InstanceValue -> obj.get(expr.property, this)
            is StringValue -> when (expr.property) {
                "size" -> IntValue(obj.value.length.toLong())
                "isEmpty" -> BoolValue(obj.value.isEmpty())
                else -> {
                    obj.getMethod(expr.property)?.let { method ->
                        NativeFunction(method.name, method.arity) { interpreter, args ->
                            method.impl(interpreter, obj, args)
                        }
                    } ?: throw RuntimeException("String has no property or method '${expr.property}'")
                }
            }
            is ListValue -> when (expr.property) {
                "size" -> IntValue(obj.elements.size.toLong())
                "isEmpty" -> BoolValue(obj.elements.isEmpty())
                "add" -> NativeFunction("add", 1) { _, args ->
                    obj.elements.add(args[0])
                    NullValue
                }
                else -> {
                    obj.getMethod(expr.property)?.let { method ->
                        NativeFunction(method.name, method.arity) { interpreter, args ->
                            method.impl(interpreter, obj, args)
                        }
                    } ?: throw RuntimeException("List has no property or method '${expr.property}'")
                }
            }
            is ResultValue -> when (expr.property) {
                "mustOk" -> NativeFunction("mustOk") { _, args ->
                    val errorMsg = args.getOrNull(0) as? StringValue
                    when (obj) {
                        is ResultValue.Ok -> obj.value
                        is ResultValue.Err -> throw RuntimeException(
                            errorMsg?.value ?: "Called mustOk on Err value: ${obj.error}"
                        )
                    }
                }
                else -> throw RuntimeException("Result has no property '${expr.property}'")
            }
            else -> throw RuntimeException("Cannot access member of ${obj.typeName()}")
        }
    }

    private fun evaluateIndex(expr: IndexExpr): RosenfeldValue {
        val obj = evaluate(expr.obj)
        val index = evaluate(expr.index)

        return when {
            obj is ListValue && index is IntValue -> {
                val i = index.value.toInt()
                if (i < 0 || i >= obj.elements.size) {
                    throw RuntimeException("Index out of bounds: $i")
                }
                obj.elements[i]
            }
            obj is StringValue && index is IntValue -> {
                val i = index.value.toInt()
                if (i < 0 || i >= obj.value.length) {
                    throw RuntimeException("Index out of bounds: $i")
                }
                StringValue(obj.value[i].toString())
            }
            else -> throw RuntimeException("Cannot index ${obj.typeName()} with ${index.typeName()}")
        }
    }

    private fun evaluateArrowMatch(expr: ArrowMatchExpr): RosenfeldValue {
        val value = evaluate(expr.value)

        for (branch in expr.branches) {
            val matches = when (value) {
                is ResultValue.Ok -> branch.pattern == "Ok"
                is ResultValue.Err -> branch.pattern == "Err"
                else -> false
            }

            if (matches) {
                val env = Environment(environment)
                when (value) {
                    is ResultValue.Ok -> env.define("it", value.value)
                    is ResultValue.Err -> env.define("it", value.error)
                    else -> {}
                }

                val previous = environment
                environment = env
                return try {
                    if (branch.isBlock && branch.body is io.github.sumaroder.rosenfeld.ast.BlockExpr) {
                        var result: RosenfeldValue = NullValue
                        for (stmt in branch.body.block.statements) {
                            result = when (stmt) {
                                is ExprStmt -> evaluate(stmt.expr)
                                else -> {
                                    execute(stmt)
                                    NullValue
                                }
                            }
                        }
                        result
                    } else {
                        evaluate(branch.body)
                    }
                } finally {
                    environment = previous
                }
            }
        }

        throw RuntimeException("No matching branch for $value")
    }

    fun evaluateGetter(instance: InstanceValue, prop: PropertyDecl, getter: GetterDecl): RosenfeldValue {
        return if (getter.isExpression) {
            val env = Environment(environment)
            env.define("this", instance)
            val previous = environment
            environment = env
            try {
                evaluate(getter.body)
            } finally {
                environment = previous
            }
        } else {
            val env = Environment(environment)
            env.define("this", instance)
            val previous = environment
            environment = env
            try {
                if (getter.body is BlockExpr) {
                    for (stmt in getter.body.block.statements) {
                        execute(stmt)
                    }
                }
                NullValue
            } catch (e: ReturnException) {
                e.value
            } finally {
                environment = previous
            }
        }
    }

    fun executeSetter(instance: InstanceValue, prop: PropertyDecl, value: RosenfeldValue) {
        val setter = prop.setter ?: return

        if (setter.body != null) {
            val env = Environment(environment)
            env.define("this", instance)
            env.define("value", value)
            val previous = environment
            environment = env
            try {
                for (stmt in setter.body.statements) {
                    execute(stmt)
                }
            } finally {
                environment = previous
            }
        } else {
            instance.fields[prop.name] = value
        }
    }

    private fun defineNativeFunctions() {
        globals.define("print", NativeFunction("print") { interpreter, args ->
            val output = args.joinToString(" ") { it.toDisplayString() }
            println(output)
            NullValue
        })

        globals.define("Ok", NativeFunction("Ok") { _, args ->
            if (args.isEmpty()) throw RuntimeException("Ok requires a value")
            ResultValue.Ok(args[0])
        })

        globals.define("Err", NativeFunction("Err") { _, args ->
            if (args.isEmpty()) throw RuntimeException("Err requires an error")
            ResultValue.Err(args[0])
        })

        globals.define("mustOk", NativeFunction("mustOk") { _, args ->
            val result = args.getOrNull(0)
                ?: throw RuntimeException("mustOk requires a Result argument")
            val errorMsg = args.getOrNull(1) as? StringValue

            when (result) {
                is ResultValue.Ok -> result.value
                is ResultValue.Err -> throw RuntimeException(
                    errorMsg?.value ?: "Called mustOk on Err value: ${result.error}"
                )
                else -> throw RuntimeException("mustOk requires a Result argument")
            }
        })

        globals.define("List", NativeFunction("List") { _, args ->
            ListValue(args.toMutableList())
        })

        globals.define("Str", NativeFunction("Str") { _, args ->
            if (args.isEmpty()) StringValue("")
            else StringValue(args[0].toDisplayString())
        })

        globals.define("Int", NativeFunction("Int") { _, args ->
            if (args.isEmpty()) IntValue(0)
            else when (val arg = args[0]) {
                is IntValue -> arg
                is FloatValue -> IntValue(arg.value.toLong())
                is StringValue -> IntValue(arg.value.toLongOrNull() ?: 0)
                else -> throw RuntimeException("Cannot convert ${arg.typeName()} to Int")
            }
        })

        globals.define("Float", NativeFunction("Float") { _, args ->
            if (args.isEmpty()) FloatValue(0.0)
            else when (val arg = args[0]) {
                is IntValue -> FloatValue(arg.value.toDouble())
                is FloatValue -> arg
                is StringValue -> FloatValue(arg.value.toDoubleOrNull() ?: 0.0)
                else -> throw RuntimeException("Cannot convert ${arg.typeName()} to Float")
            }
        })
    }

    fun getGlobal(name: String): RosenfeldValue {
        return globals.get(name)
    }

    fun callMainIfExists() {
        val mainFunc = try {
            globals.get("main")
        } catch (_: RuntimeException) {
            return
        }
        
        if (mainFunc is FunctionValue) {
            val env = Environment(globals)
            val previous = environment
            environment = env
            try {
                execute(mainFunc.body)
            } catch (e: ReturnException) {
            } finally {
                environment = previous
            }
        }
    }

    private inner class BlockExpr(val block: BlockStmt, override val info: TokenInfo = block.info) : Expr
}

typealias NativeFunctionImpl = (Interpreter, List<RosenfeldValue>) -> RosenfeldValue

data class NativeFunction(
    val name: String,
    val arity: Int = -1,
    val impl: NativeFunctionImpl
) : RosenfeldValue() {
    override fun typeName() = "NativeFunction"
    override fun toString() = "<native fn $name>"

    fun call(interpreter: Interpreter, arguments: List<RosenfeldValue>): RosenfeldValue {
        if (arity >= 0 && arguments.size != arity) {
            throw RuntimeException("$name expects $arity arguments, got ${arguments.size}")
        }
        return impl(interpreter, arguments)
    }
}
