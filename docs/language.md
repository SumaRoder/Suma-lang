# Rosenfield 语言文档

## 目录

1. [概述](#概述)
2. [快速开始](#快速开始)
3. [基础语法](#基础语法)
4. [类型系统](#类型系统)
5. [变量和常量](#变量和常量)
6. [表达式和运算符](#表达式和运算符)
7. [控制流](#控制流)
8. [函数](#函数)
9. [类](#类)
10. [模式匹配](#模式匹配)
11. [错误处理](#错误处理)
12. [模块系统](#模块系统)
13. [标准库](#标准库)

---

## 概述

Rosenfield 是一种静态类型的编程语言，设计简洁而强大。它结合了面向对象和函数式编程的特性，提供：

- **静态类型系统**：编译时类型检查，提高代码可靠性
- **类**：支持面向对象编程
- **函数式特性**：一等函数、模式匹配
- **Result 类型**：显式错误处理
- **模块化**：支持代码组织和复用

### Hello World

```nk
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

---

## 快速开始

### 编译和运行

```bash
# 编译项目
mvn compile

# 运行程序
mvn exec:java -Dexec.mainClass="io.github.sumaroder.rosenfeld.RosenfeldKt" \
    -Dexec.args="your_program.nk"
```

### 基本程序结构

```nk
// 导入模块
import "stdlib/core.nk"
import "stdlib/math.nk"

// 定义函数
pub add(a: Int, b: Int): Int {
    return a + b
}

// 主函数
pub main(): Int {
    result: Int = add(5, 3)
    print("Result: " + Str(result))
    return 0
}
```

---

## 基础语法

### 注释

```nk
// 单行注释

/*
 * 多行注释
 */
```

### 标识符

- 以字母或下划线开头
- 可包含字母、数字、下划线
- 区分大小写

### 关键字

```
pub, pri, const, init, this, it
if, elif, else, loop, break, continue
return, import, getter, setter
```

---

## 类型系统

### 基本类型

| 类型 | 描述 | 示例 |
|------|------|------|
| `Int` | 整数 | `42`, `-10` |
| `Float` | 浮点数 | `3.14`, `-0.5` |
| `Str` | 字符串 | `"hello"` |
| `Bool` | 布尔值 | `true`, `false` |
| `Null` | 空值 | `null` |

### 复合类型

| 类型 | 描述 | 示例 |
|------|------|------|
| `List` | 列表 | `List(1, 2, 3)` |
| `R<T, E>` | Result 类型 | `Ok(42)`, `Err("error")` |
| `Function` | 函数类型 | `fn: Function` |

### 类型注解

```nk
// 变量类型注解
age: Int = 25
name: Str = "Alice"
numbers: List = List(1, 2, 3)

// 函数参数和返回类型
pub greet(name: Str): Str {
    return "Hello, " + name
}

// Result 类型
pub divide(a: Int, b: Int): R<Int, Str> {
    if (b == 0) {
        return Err("Division by zero")
    }
    return Ok(a / b)
}
```

### 类型转换

```nk
// 数值转字符串
s: Str = Str(42)        // "42"
f: Str = Str(3.14)      // "3.14"

// 字符串转数值（返回 Result）
n: Any = parseInt("42")     // Ok(42)
```

---

## 变量和常量

### 变量声明

```nk
// 显式类型
x: Int = 10
y: Str = "hello"

// 类型推断（如果支持）
z = 10  // 推断为 Int
```

### 常量

```nk
pub PI: Int = 314159
pub MAX_SIZE: Int = 100
```

### 可变性与作用域

```nk
pub global: Int = 0  // 全局变量

pub test() {
    local: Int = 10  // 局部变量
    global = 5       // 可以修改全局变量
}
```

---

## 表达式和运算符

### 算术运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `+` | 加法 | `a + b` |
| `-` | 减法 | `a - b` |
| `*` | 乘法 | `a * b` |
| `/` | 除法 | `a / b` |
| `%` | 取模 | `a % b` |

### 比较运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `==` | 等于 | `a == b` |
| `!=` | 不等于 | `a != b` |
| `>` | 大于 | `a > b` |
| `<` | 小于 | `a < b` |
| `>=` | 大于等于 | `a >= b` |
| `<=` | 小于等于 | `a <= b` |

### 逻辑运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `&&` | 逻辑与 | `a && b` |
| `\|\|` | 逻辑或 | `a \|\| b` |
| `!` | 逻辑非 | `!a` |

### 位运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `&` | 按位与 | `a & b` |
| `\|` | 按位或 | `a \| b` |
| `^` | 按位异或 | `a ^ b` |
| `<<` | 左移 | `a << 2` |
| `>>` | 右移 | `a >> 2` |
| `~` | 按位取反 | `~a` |

### 赋值运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `=` | 赋值 | `a = 10` |
| `+=` | 加赋值 | `a += 5` |
| `-=` | 减赋值 | `a -= 5` |
| `*=` | 乘赋值 | `a *= 2` |
| `/=` | 除赋值 | `a /= 2` |
| `%=` | 模赋值 | `a %= 3` |

### 其他运算符

| 运算符 | 描述 | 示例 |
|--------|------|------|
| `?:` | Elvis 运算符 | `value ?: default` |
| `?.` | 安全调用 | `obj?.method()` |
| `[]` | 索引访问 | `list[0]`, `str[0]` |
| `.` | 成员访问 | `obj.property` |

### 条件表达式

```nk
// 三元条件（如果支持）
result: Int = if (a > b) { a } else { b }
```

---

## 控制流

### if 表达式

```nk
if (condition) {
    // 代码块
}

if (condition) {
    // 代码块
} else {
    // 代码块
}

if (condition) {
    // 代码块
} elif (otherCondition) {
    // 代码块
} else {
    // 代码块
}
```

### loop 循环

```nk
// 无限循环
loop {
    // 循环体
    if (condition) {
        break  // 跳出循环
    }
}

// 带条件的循环（类似 while）
loop {
    if (!condition) break
    // 循环体
}
```

### break 和 continue

```nk
loop {
    if (shouldSkip) {
        continue  // 跳过当前迭代
    }
    if (shouldStop) {
        break     // 完全退出循环
    }
}
```

### 列表遍历示例

```nk
numbers: List = List(1, 2, 3, 4, 5)
i: Int = 0
loop {
    if (i >= numbers.size) break
    print(Str(numbers[i]))
    i += 1
}
```

---

## 函数

### 函数定义

```nk
// 基本函数
pub add(a: Int, b: Int): Int {
    return a + b
}

// 无返回值函数
pub printMessage(msg: Str) {
    print(msg)
}

// 默认参数值
pub greet(name: Str, greeting?: Str = "Hello"): Str {
    return greeting + ", " + name
}
```

### 函数调用

```nk
result: Int = add(5, 3)           // 位置参数
message: Str = greet("Alice")      // 使用默认值
message: Str = greet("Bob", "Hi")  // 覆盖默认值
```

### 递归函数

```nk
pub factorial(n: Int): Int {
    if (n <= 1) return 1
    return n * factorial(n - 1)
}
```

### 高阶函数

```nk
// 接受函数作为参数
pub applyTwice(n: Int, fn: Function): Int {
    return fn(fn(n))
}

// 使用
result: Int = applyTwice(5, double)  // 20
```

### 嵌套函数

```nk
pub outer() {
    pri localVar: Int = 10
    
    pub inner(): Int {
        return localVar + 5  // 可以访问外部变量
    }
    
    return inner()
}
```

---

## 类

### 类定义

```nk
pub Person {
    // 私有属性
    pri name: Str
    pri age: Int = 0
    
    // 公共属性
    pub id: Int
    
    // 带 getter 的私有属性
    pri email: Str
        .getter
    
    // 初始化方法
    pub init(name: Str, age: Int) {
        this.name = name
        this.age = age
    }
    
    // 普通方法
    pub greet(): Str {
        return "Hello, I'm " + this.name
    }
    
    // 修改状态的方法
    pub haveBirthday() {
        this.age += 1
    }
    
    // getter 方法（显式）
    pub getAge(): Int {
        return this.age
    }
}
```

### 创建实例

```nk
// 创建对象
p: Person = Person("Alice", 25)

// 访问属性
print(p.id)      // 访问公共属性
print(p.email)   // 通过 getter 访问私有属性

// 调用方法
greeting: Str = p.greet()
p.haveBirthday()
```

### 访问修饰符

```nk
pub ClassName {
    pub publicField: Int      // 公共访问
    pri privateField: Int     // 私有访问（仅类内部）
    
    pub publicMethod() { }     // 公共方法
    pri privateMethod() { }    // 私有方法
}
```

### Getter 和 Setter

```nk
pub Rectangle {
    pri width: Int
    pri height: Int
    
    // 只读属性（getter）
    pub area: Int
        .getter { return width * height }
    
    // 计算属性
    pub perimeter: Int
        .getter { return 2 * (width + height) }
}
```

---

## 模式匹配

### Arrow Match

Rosenfield 提供箭头匹配表达式，用于解构和匹配值：

```nk
// 基本匹配
result -> {
    Ok = handleSuccess(it)
    Err = handleError(it)
}

// 带默认值
value -> {
    Some = it
    None = defaultValue
}
```

### Result 类型匹配

```nk
pub divide(a: Int, b: Int): R<Int, Str> {
    if (b == 0) {
        return Err("Cannot divide by zero")
    }
    return Ok(a / b)
}

// 使用匹配
result: R<Int, Str> = divide(10, 2)
result -> {
    Ok {
        print("Result: " + it)
    }
    Err = print("Error: " + it)
}
```

### 匹配中的 `it`

在匹配分支中，`it` 代表匹配到的值：

```nk
result -> {
    Ok = process(it)    // it 是 Ok 中的值
    Err = log(it)       // it 是 Err 中的错误信息
}
```

---

## 错误处理

### Result 类型

Rosenfield 使用 `R<T, E>` 类型进行错误处理：

```nk
// 成功值
success: R<Int, Str> = Ok(42)

// 错误值
failure: R<Int, Str> = Err("Something went wrong")
```

### 创建 Result

```nk
pub parseNumber(s: Str): R<Int, Str> {
    if (s.size == 0) {
        return Err("Empty string")
    }
    // 解析逻辑...
    return Ok(result)
}
```

### 处理 Result

```nk
// 使用匹配（推荐）
result -> {
    Ok = {
        // 使用 it
    }
    Err = {
        // 处理错误
    }
}

// 辅助函数（来自 stdlib/core.nk）
if (isOk(result)) { }
if (isErr(result)) { }

value: Any = unwrapOr(result, defaultValue)
value: Any = unwrap(result)  // 如果是 Err 会 panic
```

### 传播错误

```nk
pub processFile(path: Str): R<Data, Str> {
    content: R<Str, Str> = readFile(path)
    content -> {
        Ok = parseData(it)
        Err = Err(it)  // 传播错误
    }
}
```

---

## 模块系统

### 导入模块

```nk
// 导入标准库
import "stdlib/core.nk"
import "stdlib/math.nk"
import "stdlib/list.nk"

// 导入相对路径
import "./utils.nk"
import "../common/helpers.nk"
```

### 导出声明

```nk
// 使用 pub 关键字导出
pub helperFunction() { }

pub HelperClass { }

// 私有（仅在当前模块可见）
pri internalFunction() { }
```

### 模块结构

```
project/
├── main.nk
├── utils.nk
└── stdlib/
    ├── core.nk
    ├── math.nk
    └── list.nk
```

```nk
// main.nk
import "utils.nk"
import "stdlib/core.nk"

pub main(): Int {
    helper()  // 来自 utils.nk
    return 0
}
```

### 避免循环导入

模块系统会检测循环依赖并报错。

---

## 标准库

### core.nk - 核心工具

```nk
// Result 处理
isOk(result): Bool
isErr(result): Bool
unwrapOr(result, default): Any
unwrap(result): Any
map(result, fn): Any

// 数据结构
Pair { first(), second(), swap() }
Range { contains(), toList(), size() }
Optional { some(), none(), isSome(), isNone() }

// 错误处理
panic(msg): Any
assert(cond, msg)
```

### math.nk - 数学函数

```nk
// 基础
abs(n), max(a, b), min(a, b), clamp(n, low, high)
sign(n), isEven(n), isOdd(n)

// 幂运算
pow(base, exp), sqrt(n), cbrt(n)

// 数论
gcd(a, b), lcm(a, b), isPrime(n)
factorial(n), fibonacci(n)

// 列表统计
sum(list), product(list), average(list)
maxInList(list), minInList(list)

// 常量
PI(), E(), PHI()
```

### list.nk - 列表操作

```nk
// 切片
take(list, n), drop(list, n), slice(list, start, end)

// 变换
reverse(list), distinct(list), flatten(list)
map(list, fn), filter(list, pred)
reduce(list, fn, initial)

// 查找
contains(list, value), indexOf(list, value)
find(list, pred), any(list, pred), all(list, pred)

// 排序
sort(list), sortBy(list, fn)

// 组合
zip(list1, list2), concat(list1, list2)
```

### collections.nk - 数据结构

```nk
// 栈 (LIFO)
Stack { push(), pop(), peek(), isEmpty(), size() }

// 队列 (FIFO)
Queue { enqueue(), dequeue(), peek(), isEmpty(), size() }

// 双端队列
Deque { pushFront(), pushBack(), popFront(), popBack() }

// 哈希表
HashMap { put(), get(), contains(), remove(), keys(), values() }

// 集合
Set { add(), contains(), remove(), union(), intersect(), difference() }
```

### format.nk - 字符串格式化

```nk
padLeft(s, width, pad), padRight(s, width, pad), padCenter(s, width, pad)
intToStr(n, width), hex(n), binary(n), octal(n)
format(template, args), join(list, sep)
truncate(s, maxLen), lines(s), words(s)
```

### time.nk - 时间和随机数

```nk
// 随机数
Random { next(), nextInt(max), nextRange(min, max), shuffle(list) }

// 计时器
Timer { start(), stop(), elapsed(), lap() }

// 时间转换
msToSeconds(ms), msToMinutes(ms), formatDuration(ms)
```

### assert.nk - 测试断言

```nk
assertTrue(value, msg), assertFalse(value, msg)
assertEq(actual, expected, msg), assertNe(actual, expected, msg)
assertGt(a, b, msg), assertLt(a, b, msg)
assertOk(result, msg), assertErr(result, msg)
assertContains(list, item, msg), assertEmpty(list, msg)
fail(msg), panic(msg)
```

---

## 完整示例

### 示例 1：计算阶乘

```nk
pub factorial(n: Int): Int {
    if (n < 0) return 0
    if (n == 0 || n == 1) return 1
    return n * factorial(n - 1)
}

pub main(): Int {
    i: Int = 1
    loop {
        if (i > 10) break
        print(Str(i) + "! = " + Str(factorial(i)))
        i += 1
    }
    return 0
}
```

### 示例 2：学生成绩管理

```nk
import "stdlib/list.nk"
import "stdlib/math.nk"

pub Student {
    pri name: Str
    pri scores: List
    
    pub init(name: Str) {
        this.name = name
        this.scores = List()
    }
    
    pub addScore(score: Int) {
        this.scores.add(score)
    }
    
    pub average(): R<Int, Str> {
        if (this.scores.size == 0) {
            return Err("No scores available")
        }
        return Ok(sum(this.scores) / this.scores.size)
    }
    
    pub getName(): Str {
        return this.name
    }
}

pub main(): Int {
    s: Student = Student("Alice")
    s.addScore(85)
    s.addScore(90)
    s.addScore(78)
    
    avg: Any = s.average()
    avg -> {
        Ok = print(s.getName() + "'s average: " + Str(it))
        Err = print("Error: " + it)
    }
    
    return 0
}
```

### 示例 3：文件处理（概念示例）

```nk
pub processData(path: Str): R<Str, Str> {
    // 读取文件
    content: R<Str, Str> = readFile(path)
    
    result: Any = content -> {
        Ok = {
            // 处理内容
            if (it.size == 0) {
                Err("Empty file")
            } else {
                Ok(processContent(it))
            }
        }
        Err = Err(it)
    }
    
    return result
}
```

---

## 最佳实践

1. **使用 Result 类型处理错误**，避免异常滥用
2. **优先使用不可变数据**，减少副作用
3. **使用类型注解** 提高代码可读性
4. **模块化设计**，合理组织代码
5. **利用模式匹配** 简化条件逻辑

---

## 常见问题

### Q: 如何创建数组/列表？
```nk
list: List = List(1, 2, 3)
list.add(4)
```

### Q: 如何处理空值？
使用 Optional 类型或显式检查：
```nk
if (value != null) {
    // 安全使用
}
```

### Q: 字符串如何拼接？
```nk
s: Str = "Hello, " + name
```

### Q: 如何遍历列表？
```nk
i: Int = 0
loop {
    if (i >= list.size) break
    item = list[i]
    // 处理 item
    i += 1
}
```

---

*文档版本: 1.0.0*
*最后更新: 2026-04-03*
