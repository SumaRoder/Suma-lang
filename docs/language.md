# Suma-lang Language Reference

## Getting Started

Suma-lang is a statically-typed language with explicit error handling via Result types. No exceptions — you handle errors as values.

```suma
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

That's your entry point. The function must return an `Int`, and `0` means success.

## Lexical Stuff

Identifiers start with a letter or underscore, then can use letters, numbers, and underscores. Case matters.

Keywords you can't use as names: `pub`, `pri`, `const`, `init`, `this`, `it`, `if`, `elif`, `else`, `loop`, `break`, `continue`, `return`, `import`, `getter`, `setter`, `static`, `is`, `fn`, `class`, `throw`, `try`, `catch`, `finally`.

Comments work like this:

```suma
// single line

/*
    multi-line
    /* they can nest */
*/
```

Strings use double or single quotes, support escapes: `\n`, `\t`, `\\`, `\"`, `\'`.

## Types

**Primitives:**
- `Int` — integers, hex works too: `0xFF`
- `Float` — floating point: `3.14`
- `Str` — strings
- `Bool` — `true` or `false`
- `Null` — the nothing value
- `Any` — dynamic type when you need it

**Special types:**
- `List` — growable list: `List(1, 2, 3)`
- `R<T, E>` — Result type, generic: `R<Int, Str>`
- `Function` — function values

Type annotations go after the name:

```suma
age: Int = 25
name: Str = "Alice"
items: List = List(1, 2, 3)
```

## Variables

Declare with `pub` for global scope, `pri` for local-only:

```suma
pub MAX_SIZE: Int = 100
pri temp: Int = 0
```

`pub` at the top level makes it visible everywhere. `pri` keeps it in the current scope.

## Operators

Pretty much what you'd expect:

**Arithmetic:** `+`, `-`, `*`, `/`, `%`

**Comparison:** `==`, `!=`, `>`, `<`, `>=`, `<=`

**Logical:** `&&`, `||`, `!`

**Bitwise:** `&`, `|`, `^`, `<<`, `>>`, `~`

**Assignment:** `=`, `+=`, `-=`, `*=`, `/=`, `%=`

**Special stuff:**
- `->` — pattern match on Result
- `?.` — safe call (returns null if error)
- `?=` — Elvis operator (use default if error)
- `[]` — index access
- `.` — member access
- `is` — type check

Operator precedence, lowest to highest:
```
=  →  ?=  →  ||  →  &&  →  |  →  ^  →  &  →  == !=  →  < > <= >= is  →  << >>  →  + -  →  * / %  →  ! - ~  →  postfix (call, member, index)
```

## Control Flow

### if/elif/else

```suma
if (x > 0) {
    print("positive")
} elif (x < 0) {
    print("negative")
} else {
    print("zero")
}
```

### loop

It's an infinite loop by default, you break out manually:

```suma
i: Int = 0
loop {
    if (i >= 10) break
    print(to_str(i))
    i += 1
}
```

`break` exits the loop, `continue` skips to the next iteration.

## Functions

```suma
pub add(a: Int, b: Int): Int {
    return a + b
}
```

Return type goes after the parameters. Omit it for `Null` return.

Default parameters work:

```suma
pub greet(name: Str, greeting: Str = "Hello"): Str {
    return greeting + ", " + name
}
```

Recursion is fine:

```suma
pub factorial(n: Int): Int {
    if (n <= 1) return 1
    return n * factorial(n - 1)
}
```

### Lambdas

Functions are first-class values:

```suma
double: Function = fn(x: Int): Int {
    return x * 2
}

result: Int = double(21)  // 42
```

You can pass them around:

```suma
pub apply(n: Int, fn: Function): Int {
    return fn(n)
}

result: Int = apply(5, fn(x: Int): Int { return x * x })
```

## Classes

```suma
pub Person {
    pri name: Str
    pri age: Int
    pub id: Int

    pub init(name: Str, age: Int) {
        this.name = name
        this.age = age
        this.id = 0
    }

    pub greet(): Str {
        return "Hello, I'm " + this.name
    }
}
```

`pub` fields are accessible outside, `pri` are private. The `init` method is your constructor, called with `ClassName(args)`.

### Getters and Setters

```suma
pub Rectangle {
    pri width: Int
    pri height: Int

    pub area: Int
        .getter {
            return this.width * this.height
        }

    pub width: Int
        .setter (value: Int) {
            if (value >= 0) {
                this.width = value
            }
        }
}
```

## Pattern Matching

The `->` operator matches Results, runtime types, literal values, and `_` as a fallback:

```suma
result -> {
    Ok = handle_success(it)
    Err = handle_error(it)
}

value -> {
    is Box = it.value
    "ready" = 1
    _ = 0
}
```

For `Ok` and `Err`, `it` refers to the wrapped value. For type, literal, and `_` matches,
`it` refers to the matched value itself.

You can nest them:

```suma
nested -> {
    Ok = {
        value -> {
            Ok = print("Got: " + to_str(it))
            Err = print("Inner error: " + it)
        }
    }
    Err = print("Outer error: " + it)
}
```

## Error Handling

No exceptions. You return `Ok(value)` for success and `Err(error)` for failure:

```suma
pub parse_number(s: Str): R<Int, Str> {
    if (s.size == 0) {
        return Err("Empty string")
    }
    return Ok(123)
}
```

Helper functions:
- `is_ok(result)` — returns `true` if Ok
- `is_err(result)` — returns `true` if Err
- `unwrap(result)` — gets the value, panics if Err
- `unwrap_or(result, default)` — gets value or returns default

`throw` is available for exceptional situations that you can't recover from.

## Imports

```suma
import "core"                    // from stdlib
import "./utils.suma"             // relative to current file
import "/absolute/path/module"    // absolute path
import "my_module"                // search path
import "py:math"                  // Python module
import "py:numpy as np"           // import with alias
```

Search order:
1. Relative to current file
2. `SUMA_PATH` environment variable
3. `-I` / `--import-path` flags
4. Current directory
5. Project root
6. `stdlib/`

The compiler catches circular imports and reports them.

## Special Syntax

### Elvis Operator (?=)

```suma
result: R = left ?= right
// equivalent to:
if (is_err(left)) {
    result = right
} else {
    result = left
}
```

### Safe Call (?.)

```suma
result = obj?.method(args)
// equivalent to:
if (is_err(obj)) {
    result = null
} else {
    result = obj.method(args)
}
```

### Slicing

```suma
list: List = List(1, 2, 3, 4, 5)
first_three: List = list[0:3]   // List(1, 2, 3)
last_two: List = list[3:]       // List(4, 5)
copy: List = list[:]            // full copy
```

### it Keyword

In pattern matching, `it` binds to the inner Result value for `Ok` and `Err`,
or to the matched value for type, literal, and `_` arms:

```suma
result -> {
    Ok = print("Got: " + to_str(it))
    Err = print("Failed: " + it)
}
```

## Under the Hood

The compiler pipeline:

1. **Lexing** — source to tokens
2. **Parsing** — tokens to AST
3. **Semantic analysis** — type checking, scope resolution
4. **Import resolution** — expand all imports
5. **IR lowering** — AST to three-address code
6. **IR optimization** — constant folding, propagation, dead code
7. **Codegen** — IR to bytecode
8. **Bytecode optimization** — peephole, superinstruction fusion
9. **Serialization** — write .sumac file
10. **VM execution** — stack-based interpreter

The IR uses virtual registers in `%name.version` format. Basic blocks form the control flow graph. Optimizations run iteratively up to 10 passes.

Bytecode uses a custom binary format with sections for constants, classes, functions. The VM maintains a call stack of frames, each with local slots and an operand stack.

If you're hacking on the compiler, the key files:
- `src/frontend/lexer/tokenizer.py` — the lexer
- `src/frontend/parser/parser.py` — recursive descent parser
- `src/frontend/semantic/analyzer.py` — type checker
- `src/mid/ir/lower.py` — AST to IR conversion
- `src/mid/ir/optimizer.py` — IR optimizations
- `src/backend/codegen/compiler.py` — bytecode generation
- `src/runtime/vm/vm.py` — the virtual machine
