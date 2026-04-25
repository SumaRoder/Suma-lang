package io.github.sumaroder.rosenfeld.interpreter

import io.github.sumaroder.rosenfeld.ast.*

typealias NativeMethodImpl = (Interpreter, RosenfeldValue, List<RosenfeldValue>) -> RosenfeldValue

data class NativeMethod(
    val name: String,
    val arity: Int = -1,
    val impl: NativeMethodImpl
)

sealed class RosenfeldValue {
    abstract fun typeName(): String
    open fun isTruthy(): Boolean = true
    open fun toDisplayString(): String = toString()
    
    open fun getMethod(name: String): NativeMethod? = null
}

object NullValue : RosenfeldValue() {
    override fun typeName() = "Null"
    override fun isTruthy() = false
    override fun toString() = "null"
}

data class IntValue(val value: Long) : RosenfeldValue() {
    override fun typeName() = "Int"
    override fun toString() = value.toString()
}

data class FloatValue(val value: Double) : RosenfeldValue() {
    override fun typeName() = "Float"
    override fun toString() = value.toString()
}

data class StringValue(val value: String) : RosenfeldValue() {
    override fun typeName() = "Str"
    override fun isTruthy() = value.isNotEmpty()
    override fun toString() = value
    override fun toDisplayString() = value
    
    override fun getMethod(name: String): NativeMethod? = when (name) {
        "split" -> NativeMethod("split", 1) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val sep = (args[0] as StringValue).value
            val parts = str.split(sep)
            ListValue(parts.map { StringValue(it) }.toMutableList())
        }
        "trim" -> NativeMethod("trim", 0) { _, receiver, _ ->
            StringValue((receiver as StringValue).value.trim())
        }
        "startswith" -> NativeMethod("startswith", 1) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val prefix = (args[0] as StringValue).value
            BoolValue(str.startsWith(prefix))
        }
        "endswith" -> NativeMethod("endswith", 1) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val suffix = (args[0] as StringValue).value
            BoolValue(str.endsWith(suffix))
        }
        "contains" -> NativeMethod("contains", 1) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val substr = (args[0] as StringValue).value
            BoolValue(str.contains(substr))
        }
        "repeat" -> NativeMethod("repeat", 1) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val count = (args[0] as IntValue).value.toInt()
            StringValue(str.repeat(count))
        }
        "replace" -> NativeMethod("replace", 2) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val oldStr = (args[0] as StringValue).value
            val newStr = (args[1] as StringValue).value
            StringValue(str.replace(oldStr, newStr))
        }
        "upper" -> NativeMethod("upper", 0) { _, receiver, _ ->
            StringValue((receiver as StringValue).value.uppercase())
        }
        "lower" -> NativeMethod("lower", 0) { _, receiver, _ ->
            StringValue((receiver as StringValue).value.lowercase())
        }
        "substr" -> NativeMethod("substr", 2) { _, receiver, args ->
            val str = (receiver as StringValue).value
            val start = (args[0] as IntValue).value.toInt()
            val end = (args[1] as IntValue).value.toInt()
            StringValue(str.substring(start, end))
        }
        else -> null
    }
}

data class BoolValue(val value: Boolean) : RosenfeldValue() {
    override fun typeName() = "Bool"
    override fun isTruthy() = value
    override fun toString() = value.toString()
}

data class FunctionValue(
    val name: String,
    val params: List<Parameter>,
    val body: Stmt,
    val closure: Environment,
    val isInit: Boolean = false
) : RosenfeldValue() {
    override fun typeName() = "Function"
    override fun toString() = "<fn $name>"
}

data class ClassValue(
    val name: String,
    val methods: Map<String, FunctionValue>,
    val properties: Map<String, PropertyDecl>,
    val init: FunctionValue?
) : RosenfeldValue() {
    override fun typeName() = "Class"
    override fun toString() = "<class $name>"

    fun call(interpreter: Interpreter, arguments: List<RosenfeldValue>): RosenfeldValue {
        val instance = InstanceValue(this)
        
        for ((name, propDecl) in properties) {
            propDecl.initializer?.let { initExpr ->
                val value = interpreter.evaluate(initExpr)
                instance.fields[name] = value
            }
        }
        
        init?.let {
            val boundInit = it.bind(instance)
            interpreter.callFunction(boundInit, arguments)
        }
        return instance
    }
}

data class InstanceValue(
    val clazz: ClassValue,
    val fields: MutableMap<String, RosenfeldValue> = mutableMapOf(),
    val properties: MutableMap<String, RosenfeldValue> = mutableMapOf()
) : RosenfeldValue() {
    override fun typeName() = "Instance"
    override fun toString() = "<${clazz.name} instance>"

    fun get(name: String, interpreter: Interpreter): RosenfeldValue {
        fields[name]?.let { return it }

        clazz.properties[name]?.let { propDecl ->
            val getter = propDecl.getter
            if (getter != null && getter.body is Identifier && getter.body.name == "__field__") {
                return fields[name] ?: NullValue
            } else if (getter != null) {
                return interpreter.evaluateGetter(this, propDecl, getter)
            }
            return fields[name] ?: NullValue
        }

        clazz.methods[name]?.let { return it.bind(this) }

        throw RuntimeException("undefined property '$name' on ${clazz.name}")
    }

    fun set(name: String, value: RosenfeldValue, interpreter: Interpreter) {
        clazz.properties[name]?.let { propDecl ->
            if (propDecl.setter != null) {
                interpreter.executeSetter(this, propDecl, value)
                return
            }
        }

        fields[name] = value
    }
}

sealed class ResultValue : RosenfeldValue() {
    override fun typeName() = "R"

    data class Ok(val value: RosenfeldValue) : ResultValue() {
        override fun isTruthy() = true
        override fun toString() = "Ok($value)"
    }

    data class Err(val error: RosenfeldValue) : ResultValue() {
        override fun isTruthy() = false
        override fun toString() = "Err($error)"
    }
}

data class ListValue(
    val elements: MutableList<RosenfeldValue>
) : RosenfeldValue() {
    override fun typeName() = "List"
    override fun toString() = elements.joinToString(", ", "[", "]")
    
    override fun getMethod(name: String): NativeMethod? = when (name) {
        "add" -> NativeMethod("add", 1) { _, receiver, args ->
            (receiver as ListValue).elements.add(args[0])
            NullValue
        }
        "remove" -> NativeMethod("remove", 1) { _, receiver, args ->
            val list = (receiver as ListValue).elements
            val removed = list.remove(args[0])
            BoolValue(removed)
        }
        "erase" -> NativeMethod("erase") { _, receiver, args ->
            
            val list = (receiver as ListValue).elements
            when (args.size) {
                1 -> {
                    val pos = (args[0] as IntValue).value.toInt()
                    if (pos < 0 || pos >= list.size) {
                        throw RuntimeException("index out of bounds: $pos")
                    }
                    list.removeAt(pos)
                    if (pos < list.size) list[pos] else NullValue
                }
                2 -> {
                    val first = (args[0] as IntValue).value.toInt()
                    val last = (args[1] as IntValue).value.toInt()
                    
                    if (first < 0 || first > list.size) throw RuntimeException("index out of bounds: $first")
                    if (last < 0 || last > list.size) throw RuntimeException("index out of bounds: $last")
                    if (first > last) throw RuntimeException("erase first > last")
                    
                    val count = last - first
                    repeat(count) { list.removeAt(first) }
                    
                    if (first < list.size) list[first] else NullValue
                }
                else -> throw RuntimeException("no matching erase overload")
            }
        }
        "get" -> NativeMethod("get", 1) { _, receiver, args ->
            val list = (receiver as ListValue).elements
            val index = (args[0] as IntValue).value.toInt()
            if (index < 0 || index >= list.size) {
                throw RuntimeException("Index out of bounds: $index")
            }
            list[index]
        }
        "clear" -> NativeMethod("clear", 0) { _, receiver, _ ->
            (receiver as ListValue).elements.clear()
            NullValue
        }
        "has" -> NativeMethod("has", 1) { _, receiver, args ->
            BoolValue((receiver as ListValue).elements.contains(args[0]))
        }
        "find" -> NativeMethod("find", 1) { _, receiver, args ->
            val index = (receiver as ListValue).elements.indexOf(args[0])
            IntValue(index.toLong())
        }
        "join" -> NativeMethod("join", 1) { _, receiver, args ->
            val list = (receiver as ListValue).elements
            val sep = (args[0] as StringValue).value
            StringValue(list.joinToString(sep) { it.toDisplayString() })
        }
        "reverse" -> NativeMethod("reverse", 0) { _, receiver, _ ->
            val list = (receiver as ListValue).elements
            list.reverse()
            NullValue
        }
        "sort" -> NativeMethod("sort", 0) { _, receiver, _ ->
            val list = (receiver as ListValue).elements
            try {
                list.sortWith(compareBy { 
                    when (it) {
                        is IntValue -> it.value.toDouble()
                        is FloatValue -> it.value
                        is StringValue -> it.value
                        else -> it.toDisplayString()
                    } as Comparable<Any>
                })
            } catch (_: Exception) {
                // 如果排序失败，忽略错误
            }
            NullValue
        }
        else -> null
    }
}

fun FunctionValue.bind(instance: InstanceValue): FunctionValue {
    val newClosure = Environment(closure)
    newClosure.define("this", instance)
    return FunctionValue(name, params, body, newClosure, isInit)
}

class ReturnException(val value: RosenfeldValue) : Exception()
class BreakException : Exception()
class ContinueException : Exception()
