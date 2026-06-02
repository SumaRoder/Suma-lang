# Suma-lang

A statically-typed language that compiles to bytecode and runs on a stack-based VM,
implemented in pure Python.

## What you get

- **Static typing** with compile-time checks
- **Result types** for explicit error handling (`Ok` / `Err`)
- **Pattern matching** for results, types, and literal values
- **First-class functions** with closures and lambdas
- **Classes** with access control (`pub` / `pri`), getters and setters
- **Bytecode compiler** with multi-pass optimization
- **Stack VM** for efficient execution
- **Python interop** — import host modules with `import "py:..."`
- **Embeddable** from any Python program via [`suma_lang`](embedding.md)

## Hello, world

```suma
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

## Quick start

```bash
pip install -e .

# Compile and run a source file
suma run examples/hello.suma

# Compile to .sumac bytecode
suma compile examples/hello.suma

# Run a compiled bytecode file
suma execute examples/hello.sumac
```

The `main(): Int` function is treated as a process-style exit value.
`0` means success (and is not printed); non-zero returns are echoed to stdout
for interactive use.

## How it's built

The compiler has four stages:

1. **Frontend** — Lexer, parser, semantic analysis, import resolution
2. **Midend** — Three-address IR with constant folding, propagation, dead-code elimination
3. **Backend** — Bytecode generation, peephole optimization, `.sumac` serialization
4. **Runtime** — Stack VM that executes the bytecode

```
.suma source → Frontend → AST → Midend → IR → Backend → .sumac → VM
```

## Where to go next

<div class="grid cards" markdown>

-   :material-book-open-page-variant: **[Language Reference](language.md)**

    Syntax, types, pattern matching, classes, decorators, generics.

-   :material-package-variant: **[Standard Library](stdlib.md)**

    Builtin functions, list/string/math/JSON modules.

-   :material-language-python: **[Embedding from Python](embedding.md)**

    Compile and run Suma code from inside Python, inject host values.

-   :material-file-code: **[Bytecode Format](bytecode.md)**

    The `.sumac` wire format and opcode reference — for tooling.

</div>

## Project status

Alpha. The language and VM are functional; CLI, embedding API, and bytecode format
are usable but may shift between minor versions. See the
[GitHub repository](https://github.com/suma-lang/suma-lang) for source, issues,
and contributions.
