# Suma-lang Language Reference

## Getting Started

Suma-lang is a statically-typed language with explicit error handling via Result types. Recoverable errors are handled as values, while `throw` / `try` / `catch` exist for exceptional control flow.

It is also a deliberately aggressive language. The syntax is allowed to omit
keywords and boilerplate that SumaRoder considers low-value, so Suma programs may
look more compact and opinionated than code in languages that preserve every
traditional marker.

```suma
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

That's your entry point. The function must return an `Int`, and `0` means success.

## Lexical Stuff

Identifiers start with a letter or underscore, then can use letters, numbers, and underscores. Case matters. Names cannot start with a digit, so `123abc` is rejected as an invalid numeric literal suffix.

Keywords and special names you can't use as ordinary expression names: `pub`, `pri`, `const`, `init`, `this`, `it`, `if`, `elif`, `else`, `while`, `for`, `in`, `loop`, `break`, `continue`, `return`, `import`, `static`, `is`, `enum`, `match`, `throw`, `try`, `catch`, `finally`, `true`, `false`, `null`.

Comments work like this:

```suma
// single line

/*
    multi-line
    /* they can nest */
*/
```

Strings use double or single quotes, support escapes: `\n`, `\t`, `\\`, `\"`, `\'`.

Strings interpolate expressions written between `{` and `}`:

```suma
name = "Alice"
age = 30
print("Hello, {name}!")               // Hello, Alice!
print("name={name}, doubled={age * 2}")  // name=Alice, doubled=60
```

The expression inside `{...}` is parsed as a full Suma expression and
stringified with `to_str` at runtime. To include a literal `{`, escape with
`\{`. Prefix with `r"..."` to disable both escapes and interpolation.

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
- `Result<T, E>` — generic result type. `R<T, E>` is the short alias.
- `T?` — nullable shorthand for `Nullable<T>`, assignable from `T` or `null`.
- `(A, B)` — fixed-length tuple type. Tuple values use `(a, b)` literals.
- User-defined enums — sum types declared with `enum`.
- `Function` — function values; `Function<Int, Str>` means one `Int` parameter returning `Str`

Type annotations go after the name. Generic types use angle brackets and are invariant:

```suma
age: Int = 25
name: Str = "Alice"
items: List<Int> = List(1, 2, 3)
result: Result<Int, Str> = Ok(42)
pair: (Int, Str) = (1, "two")
```

## Variables

At the top level, `pub` explicitly exports a declaration from the module. `pri`
marks it module-private. Leaving visibility off also makes it private:

```suma
pub MAX_SIZE: Int = 100
helper(): Int { return 1 }      // private by default
pri temp: Int = 0               // explicitly private
```

Inside a class, `pub` exposes a field or method and `pri` keeps it private to the
class. Import declarations cannot be marked `pub` or `pri`.

Inside functions, introduce locals with assignment or with a typed local
declaration. Typed local declarations must include an initializer:

```suma
count = 1          // inferred as Int
name = "Suma"      // inferred as Str
typed: Int = 42    // explicit annotation
```

Bare assignment is scoped to the current block. If the name exists in the
current block, it updates that local. If it does not, it creates a new local in
the current block. To modify an outer local or a global, prefix the target with
`@`:

```suma
count = 0
loop {
    @count += 1      // modifies the outer count
    scratch = count  // creates/updates a loop-block local
    if count >= 10 { break }
}
```

Compound assignment and `++`/`--` follow the same rule: use `@name += value` or
`@name++` when the target lives in an outer scope. Destructuring assignment also
uses the current block, creating missing current-block locals instead of
rewriting an outer binding:

```suma
(left, right) = (1, 2)
a = 0;
b = 0;
(a, b) = (1, 2)
```

## Operators

Pretty much what you'd expect:

**Arithmetic:** `+`, `-`, `*`, `/`, `%`

**Comparison:** `==`, `!=`, `>`, `<`, `>=`, `<=`

**Logical:** `&&`, `||`, `!`

**Bitwise:** `&`, `|`, `^`, `<<`, `>>`, `~`

**Assignment:** `=`, `+=`, `-=`, `*=`, `/=`, `%=`

**Special stuff:**
- `->` — lambda body marker
- `=>` — pattern match arm separator in `match { ... }`
- `?.` — safe member access or call (returns null for error/null receivers)
- `else` — Result Elvis operator (unwrap `Ok`, use default for `Err`)
- `??` — null coalescing operator
- `?` — Result propagation operator
- `[]` — index access
- `.` — member access
- `is` — type check

Operator precedence, lowest to highest:
```
=  →  .. ..=  →  else ??  →  ||  →  &&  →  |  →  ^  →  &  →  == !=  →  < > <= >= is  →  << >>  →  + -  →  * / %  →  ! - ~  →  postfix (call, member, index, `?`, `?.`)
```

## Control Flow

### if/elif/else

```suma
if x > 0 {
    print("positive")
} elif x < 0 {
    print("negative")
} else {
    print("zero")
}
```

Parentheses around the condition are optional. The classic `if (cond) { ... }`
form is still accepted for compatibility with older code.

### for/in

`for` iterates over a range or a list:

```suma
for i in 0..10 {           // half-open: 0, 1, …, 9
    print(i)
}

for i in 0..=10 {          // inclusive: 0, 1, …, 10
    print(i)
}

for item in items {        // any List
    print(item)
}
```

### while

```suma
while i < n {
    @i += 1
}
```

### loop

`loop` is an unconditional loop — break out manually. Prefer `for/in` when
you're iterating a range; reach for `loop` only when neither `for` nor `while`
fits.

```suma
loop {
    line = read_line()
    if line == "" { break }
    print(line)
}
```

`break` exits the innermost loop; `continue` jumps to the next iteration.

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

Parameters are optional at the call site only when they have a default value.
`T?` means a nullable type; it does not make the parameter optional.

Recursion is fine:

```suma
pub factorial(n: Int): Int {
    if n <= 1 { return 1 }
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
`Function<Arg1, Arg2, Return>` to the analyzer check calls statically:

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

Function overloads are selected by parameter types, similar to Java overload resolution. Overload sets cannot use default parameters, and overloads with the same erased generic signature are rejected:

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
    pub value: Int

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

Class declarations use `[pub|pri] Name { ... }`. There is no `class` keyword in
class declarations, and `class` is available as an ordinary identifier where the
grammar permits one.

```suma
pub Person {
    name: Str            // private by default
    age: Int
    pub id: Int          // explicitly exposed

    init(name: Str, age: Int) {
        this.name = name
        this.age = age
        this.id = 0
    }

    pub greet(): Str {
        return "Hello, I'm {this.name}"
    }
}
```

Fields and methods default to private; mark with `pub` to expose them. The
`init` method is the constructor — `Person("Alice", 25)` calls it. `init` is
always callable from outside, so writing `pub init` is redundant.

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

## Enums

Enums define a closed set of variants. A variant can either be empty or carry
one payload value:

```suma
enum Maybe {
    Some(Int),
    None
}

pub main(): Int {
    value: Maybe = Maybe.Some(40)
    return match value {
        Maybe.Some => it + 2
        Maybe.None => 0
    }
}
```

Construct empty variants with `Enum.Variant`. Construct payload variants with
`Enum.Variant(value)`. In a `match` arm for a payload variant, `it` is the
payload value. For an empty variant, `it` is the enum value itself.
When the matched value has a known enum type, every variant must be covered
unless the match includes a `_` fallback arm.

## Pattern Matching

Use `match` to branch on Results, enum variants, runtime types, literal values,
and `_` as a fallback. This is the preferred form for new code:

```suma
match result {
    Ok => handle_success(it)
    Err => handle_error(it)
}

match value {
    Maybe.Some => it + 1
    Maybe.None => 0
    is Box => it.value
    "ready" => 1
    _ => 0
}
```

For `Ok`, `Err`, and payload enum variants, `it` refers to the wrapped value.
For type, literal, and `_` matches, `it` refers to the matched value itself.
Empty enum variants bind the enum value itself.

You can give an arm an explicit binding by putting the name in parentheses after
the pattern. If you omit the binding name, the default name is `it`:

```suma
match result {
    Ok(value) => value + 1
    Err(message) => {
        print(message)
        0
    }
}
```

The older postfix expression form `value -> { Ok = ..., Err = ... }` is not
part of the language. Use `match value { ... => ... }`; `->` is only for
lambdas.

You can nest them:

```suma
match nested {
    Ok => {
        match value {
            Ok => print("Got: " + to_str(it))
            Err => print("Inner error: " + it)
        }
    }
    Err => print("Outer error: " + it)
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

`throw` / `try` / `catch` / `finally` are retained for exceptional control flow
that does not fit Result-based recovery. Use `Result<T, E>` for ordinary
recoverable errors.

## Imports

```suma
import "core"                    // from stdlib
import "./utils.suma"             // relative to current file
import "/absolute/path/module"    // absolute path
import "my_module"                // search path
import "py:math"                  // Python module
import "py:json"                  // Python module
```

Search order:
1. Relative to current file
2. `SUMA_PATH` environment variable
3. `-I` / `--import-path` flags
4. Current directory
5. Project root
6. `SUMA_STDLIB_PATHS` entries, left to right
7. Built-in packaged stdlib

`SUMA_PATH` and `SUMA_STDLIB_PATHS` are path lists split with the platform
separator: `:` on Unix-like systems, `;` on Windows.

The compiler catches circular imports and reports them.

The default Python import allowlist includes `math`, `json`, and `statistics`.
Hosts can allow additional trusted modules through `SUMA_PY_IMPORTS`, for
example `SUMA_PY_IMPORTS=decimal,random`.

Only `pub` top-level declarations from imported Suma modules are visible to the
importer. Private declarations still compile as module internals, so exported
functions can call their private helpers without exposing those helper names.

## Special Syntax

### Result Elvis Operator (else)

```suma
result = left else right
// equivalent to:
if (is_ok(left)) {
    result = left.value
} else {
    result = right
}
```

The old `?:` spelling is not accepted.

### Null Coalescing (??)

```suma
result = nullable ?? fallback
```

The right side is evaluated only when the left side is `null`.

### Safe Call (?.)

```suma
result = obj?.method(args) ?? fallback
// equivalent to:
if (is_err(obj) || obj == null) {
    result = null
} else {
    result = obj.method(args)
}
```

When the receiver is a `Result` or nullable value, `?.` produces a nullable
result. Use `??` or a null check before assigning it to a non-nullable type.

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
match result {
    Ok => print("Got: " + to_str(it))
    Err => print("Failed: " + it)
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
