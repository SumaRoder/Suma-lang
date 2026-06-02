# Suma-lang Language Reference

## Getting Started

Suma-lang is a statically-typed language with explicit error handling via Result types. Recoverable errors are handled as values, while `throw` / `try` / `catch` exist for exceptional control flow.

```suma
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

That's your entry point. The function must return an `Int`, and `0` means success.

## Lexical Stuff

Identifiers can start with a letter, underscore, or digit, then can use letters, numbers, and underscores. Case matters. A digit-only word is still a number, while a mixed word like `123abc` is an identifier.

Keywords you can't use as names: `pub`, `pri`, `const`, `init`, `this`, `it`, `if`, `elif`, `else`, `while`, `for`, `in`, `loop`, `break`, `continue`, `return`, `import`, `static`, `is`, `class`, `throw`, `try`, `catch`, `finally`, `true`, `false`, `null`.

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
- `Any` — accepts any value at API boundaries, then narrows when a concrete value is assigned

**Special types:**
- `List` — growable list: `List(1, 2, 3)`
- `R<T, E>` — Result type, generic: `R<Int, Str>`
- `Function` — function values; `Function<Int, Str>` means one `Int` parameter returning `Str`

Type annotations go after the name. Generic types use angle brackets and are invariant:

```suma
age: Int = 25
name: Str = "Alice"
items: List<Int> = List(1, 2, 3)
result: R<Int, Str> = Ok(42)
```

## Variables

Declare with `pub` for global scope, `pri` for local-only:

```suma
pub MAX_SIZE: Int = 100
pri temp: Int = 0
```

`pub` at the top level makes it visible everywhere. `pri` keeps it in the current scope.

Inside functions, assigning to a missing name creates a local and infers its type:

```suma
count = 1        // inferred as Int
name = "Suma"    // inferred as Str
```

## Operators

Pretty much what you'd expect:

**Arithmetic:** `+`, `-`, `*`, `/`, `%`

**Comparison:** `==`, `!=`, `>`, `<`, `>=`, `<=`

**Logical:** `&&`, `||`, `!`

**Bitwise:** `&`, `|`, `^`, `<<`, `>>`, `~`

**Assignment:** `=`, `+=`, `-=`, `*=`, `/=`, `%=`

**Special stuff:**
- `->` — lambda body marker and pattern match on Result
- `?.` — safe call (returns null if error)
- `?:` — Result Elvis operator (unwrap `Ok`, use default for `Err`)
- `??` — null coalescing operator
- `?` — Result propagation operator
- `[]` — index access
- `.` — member access
- `is` — type check

Operator precedence, lowest to highest:
```
=  →  .. ..=  →  ?: ??  →  ||  →  &&  →  |  →  ^  →  &  →  == !=  →  < > <= >= is  →  << >>  →  + -  →  * / %  →  ! - ~  →  postfix (call, member, index, `?`, `?.`, `->`)
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
double: Function = (x: Int): Int -> {
    return x * 2
}

plus_one: Function = (x: Int) -> x + 1
result: Int = double(21)  // 42
```

You can leave a callback as plain `Function` for dynamic call checking, or use
`Function<Arg1, Arg2, Return>` to let the analyzer check calls statically:

```suma
inc: Function<Int, Int> = (x: Int): Int -> x + 1
answer: Int = inc(41)
```

You can pass them around:

```suma
pub apply(n: Int, callback: Function): Int {
    return callback(n)
}

result: Int = apply(5, (x: Int): Int -> { return x * x })
```

You can write generic functions. Suma infers type parameters from the call site and erases them at runtime:

```suma
pub id<T>(value: T): T {
    return value
}

answer: Int = id(42)
word: Str = id("suma")
```

Function overloads are selected by parameter types, similar to Java overload resolution. Overload sets cannot use default/optional parameters, and overloads with the same erased generic signature are rejected:

```suma
pub size(value: Int): Int {
    return value
}

pub size(value: Str): Int {
    return value.size
}
```

### Decorators

Decorators are Suma or Python callables that receive a function-like value and return a replacement. They can decorate top-level functions, classes, and class methods:

```suma
pub plus_ten(func: Function): Function {
    return () -> {
        return func() + 10
    }
}

@plus_ten
pub answer(): Int {
    return 32
}

pub wrap_box(ctor: Function): Function {
    return (value: Int) -> {
        box: Box = ctor(value)
        box.value += 1
        return box
    }
}

@wrap_box
Box {
    value: Int

    init(value: Int) {
        this.value = value
    }

    @plus_ten
    pub get(): Int {
        return this.value
    }
}
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

Classes can be generic and methods can be overloaded by parameter type:

```suma
Box<T> {
    pub value: T

    init(value: T) {
        this.value = value
    }

    pub get(): T {
        return this.value
    }
}

Scorer {
    pub score(value: Int): Int { return value + 1 }
    pub score(value: Str): Int { return value.size }
}
```

Operator overloading is implemented through special instance methods on the left operand. For example, `a + b` calls `a.op_add(b)` when that method exists. Supported names are `op_add`, `op_sub`, `op_mul`, `op_div`, `op_mod`, `op_eq`, `op_ne`, `op_gt`, `op_lt`, `op_ge`, `op_le`, `op_bit_and`, `op_bit_or`, `op_bit_xor`, `op_shl`, `op_shr`, `op_neg`, `op_not`, and `op_bit_not`.

### Getters and Setters

```suma
pub Rectangle {
    pri _width: Int
    pri height: Int

    pub get area(): Int {
        return this._width * this.height
    }

    pub get width(): Int {
        return this._width
    }

    pub set width(value: Int) {
        if (value >= 0) {
            this._width = value
        }
    }
}
```

`get` and `set` are contextual in class bodies, so ordinary methods like `pub get(): Int` remain valid.
Use a separate backing field such as `_width`; assigning to `this.width` calls the setter.

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

Prefer Results for recoverable errors. Return `Ok(value)` for success and `Err(error)` for failure:

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

Use `?` to propagate an `Err` from a function returning `R<T, E>`:

```suma
pub add(a: Str, b: Str): R<Int, Str> {
    left: Int = parse_int(a)?
    right: Int = parse_int(b)?
    return Ok(left + right)
}
```

`throw` / `try` / `catch` / `finally` are available for exceptional control flow that does not fit Result-based recovery.

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
6. `SUMA_STDLIB_PATHS` entries, left to right
7. Built-in `stdlib/`

`SUMA_PATH` and `SUMA_STDLIB_PATHS` are path lists split with the platform
separator: `:` on Unix-like systems, `;` on Windows.

The compiler catches circular imports and reports them.

## Special Syntax

### Result Elvis Operator (?:)

```suma
result = left ?: right
// equivalent to:
if (is_ok(left)) {
    result = left.value
} else {
    result = right
}
```

### Null Coalescing (??)

```suma
result = nullable ?? fallback
```

The right side is evaluated only when the left side is `null`.

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
