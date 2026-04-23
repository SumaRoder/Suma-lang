# Rosenfield 编程语言

Rosenfield 是一种静态类型的编程语言，结合了面向对象和函数式编程的特性。

## 特性

- **静态类型系统**：编译时类型检查，提高代码可靠性
- **面向对象**：支持类、继承、封装
- **函数式编程**：一等函数、模式匹配、不可变数据结构
- **显式错误处理**：使用 Result 类型处理错误，避免隐藏异常
- **模块化**：支持代码组织和复用
- **标准库丰富**：提供数学、集合、字符串处理等常用功能

## 快速开始

### 安装

```bash
git clone <repository-url>
cd Rosenfield
mvn compile
```

### Hello World

创建 `hello.nk`：

```nk
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

运行：

```bash
mvn exec:java -Dexec.mainClass="io.github.sumaroder.rosenfeld.RosenfeldKt" \
    -Dexec.args="hello.nk"
```

## 示例

### 基础语法

```nk
// 变量和类型
age: Int = 25
name: Str = "Alice"
numbers: List = List(1, 2, 3)

// 函数
pub add(a: Int, b: Int): Int {
    return a + b
}

// 控制流
if (age >= 18) {
    print("Adult")
} else {
    print("Minor")
}

// 循环
i: Int = 0
loop {
    if (i >= 5) break
    print(Str(i))
    i += 1
}
```

### 类定义

```nk
pub Person {
    pri name: Str
    pri age: Int = 0
        .getter
    
    pub init(name: Str, age: Int) {
        this.name = name
        this.age = age
    }
    
    pub greet(): Str {
        return "Hello, I'm " + this.name
    }
}

// 使用
p: Person = Person("Alice", 25)
print(p.greet())
```

### 错误处理

```nk
pub divide(a: Int, b: Int): R<Int, Str> {
    if (b == 0) {
        return Err("Division by zero")
    }
    return Ok(a / b)
}

// 使用模式匹配处理 Result
result: R<Int, Str> = divide(10, 2)
result -> {
    Ok = print("Result: " + Str(it))
    Err = print("Error: " + it)
}
```

### 使用标准库

```nk
import "stdlib/math.nk"
import "stdlib/list.nk"

// 数学函数
print("sqrt(16) = " + Str(sqrt(16)))
print("factorial(5) = " + Str(factorial(5)))

// 列表操作
numbers: List = List(3, 1, 4, 1, 5)
sorted: List = sort(numbers)
reversed: List = reverse(sorted)
mapped: List = map(numbers, fn(x) { return x * 2 })
```

## 项目结构

```
Rosenfield/
├── src/
│   ├── main/
│   │   ├── kotlin/io/github/sumaroder/rosenfeld/
│   │   │   ├── Rosenfeld.kt          # 主入口
│   │   │   ├── ast/AST.kt            # 抽象语法树
│   │   │   ├── parse/Parser.kt       # 语法解析器
│   │   │   ├── tokenize/Tokenizer.kt # 词法分析器
│   │   │   ├── interpreter/          # 解释器
│   │   │   └── error/                # 错误处理
│   │   └── resources/
│   │       ├── stdlib/               # 标准库
│   │       │   ├── core.nk
│   │       │   ├── math.nk
│   │       │   ├── list.nk
│   │       │   ├── collections.nk
│   │       │   ├── format.nk
│   │       │   ├── time.nk
│   │       │   └── assert.nk
│   │       └── *.nk                  # 示例程序
├── docs/
│   ├── language.md                   # 语言文档
│   └── stdlib.md                     # 标准库文档
├── pom.xml                           # Maven 配置
└── README.md                         # 本文件
```

## 文档

- [语言文档](docs/language.md) - 完整的语言参考
- [标准库文档](docs/stdlib.md) - 标准库 API 参考

## 标准库模块

### core.nk
核心工具：Result 类型处理、Pair、Range、Optional、错误处理

### math.nk
数学函数：基础运算、数论、统计、三角函数

### list.nk
列表操作：切片、变换、函数式操作、排序、组合

### collections.nk
数据结构：Stack、Queue、Deque、HashMap、Set、PriorityQueue

### format.nk
字符串格式化：填充、进制转换、模板、处理

### time.nk
时间和随机数：Random、Timer、时间转换

### assert.nk
测试断言：布尔、相等性、数值比较、集合断言

## 构建和运行

```bash
# 编译
mvn compile

# 运行程序
mvn exec:java -Dexec.mainClass="io.github.sumaroder.rosenfeld.RosenfeldKt" \
    -Dexec.args="your_program.nk"

# 打包
mvn package
```

## 许可证

本项目采用 Apcahe License 2.0 协议开源。详情请见 [LICENSE](LICENSE) 。
