# Suma-lang

A statically-typed language that compiles to bytecode, runs on a stack-based VM.

Suma-lang is an intentionally aggressive language with an aggressive syntax
design. It cuts keywords and ceremony that SumaRoder considers low-value, so the
language favors compact, opinionated syntax over copying the shape of older
mainstream languages.

📖 **Full documentation:** <https://SumaRoder.github.io/suma-lang/>

## What It Gives You

- **Static typing** with compile-time checks
- **Result types** for explicit error handling (`Ok` / `Err`)
- **Pattern matching** for Results, enums, types, and literal values: `match value { ... }`
- **Enums** with payload variants for closed sum types
- **First-class functions** with closures
- **Classes** with access control (`pub`/`pri`), getters and setters
- **Bytecode compiler** with multi-pass optimization
- **Stack VM** for efficient execution

## Quick Start

```bash
# Install
pip install -e .

# Run directly from source
suma run examples/hello.suma

# Compile to bytecode
suma compile examples/hello.suma

# Run the compiled bytecode
suma execute examples/hello.sumac

# Skip optimizations if you want faster compile (slower run)
suma --no-opt run examples/hello.suma
```

Here's the classic:

```suma
pub main(): Int {
    print("Hello, World!")
    return 0
}
```

## Error Handling

The language uses Result types for recoverable errors:

```suma
pub divide(a: Int, b: Int) {
    if b == 0 {
        return Err("Division by zero")
    }
    return Ok(a / b)
}

pub main(): Int {
    result = divide(10, 2)
    match result {
        Ok => print("Result: {it}")
        Err => print("Error: {it}")
    }
    return 0
}
```

Classes work like this:

```suma
pub Person {
    name: Str
    age: Int

    init(name: Str, age: Int) {
        this.name = name
        this.age = age
    }

    pub greet(): Str {
        return "Hello, I'm {this.name}"
    }
}

pub main(): Int {
    p: Person = Person("Alice", 25)
    print(p.greet())
    return 0
}
```

## How It Works

The compiler has four main stages:

**Frontend** — Tokenizes and parses your code, builds an AST, runs type checking and import resolution.

**Midend** — Converts the AST to three-address code (TAC), runs constant folding, propagation, dead code elimination.

**Backend** — Generates bytecode, applies peephole optimizations, serializes to `.sumac` files. The wire format is specified in [docs/bytecode.md](docs/bytecode.md).

**Runtime** — Stack-based VM executes the bytecode.

```
.suma source → Frontend → AST → Midend → IR → Backend → .sumac bytecode → VM
```

## Project Layout

```
src/
└── suma_lang/
    ├── frontend/      # Lexer, parser, semantic analysis, imports
    ├── mid/           # IR generation and optimization
    ├── backend/       # Bytecode generation and serialization
    └── runtime/       # The VM implementation

stdlib/                # Standard library in Suma
examples/              # Example programs
tests/                 # Test suite
```

## Running Tests

```bash
uv run pytest -q
uv run ruff check .
uv run pyright
```

## Building the Docs

The site at <https://SumaRoder.github.io/suma-lang/> is built with MkDocs Material
and deployed from `.github/workflows/docs.yml`. To preview locally:

```bash
pip install -e ".[docs]"
mkdocs serve            # http://127.0.0.1:8000
mkdocs build --strict   # one-off build into ./site
```

## Command Line Options

```bash
suma run <file>        # Compile and run
suma compile <file>    # Just compile to .sumac
suma execute <file>    # Run existing .sumac file
suma -I <path>         # Add import search path
suma --no-opt          # Disable optimizations
```

`main(): Int` is treated as a process-style exit value. `0` is success and is
not printed by the CLI; non-zero return values are printed for interactive use.

## Python Host API

Suma can be embedded from Python through the `suma_lang` package:

```python
import suma_lang

source = """
seed: Int
result: Int

pub main(): Int {
    @result = seed + 2
    return result
}
"""

program = suma_lang.compile_source(source)
vm = suma_lang.create_vm(program)
suma_lang.inject_environment(vm, {"seed": 40})

assert vm.run() == 42
assert vm.get_global("result") == 42
```

Useful API entry points:
- `compile_source(source, filename="<stdin>", options=None)` compiles source to bytecode.
- `create_vm(source_or_program, ...)` creates a VM from source text or bytecode.
- `run_source(source, inject={...})` compiles and runs source in one call.
- `run_program(program, inject={...})` runs already compiled bytecode.
- `inject_environment(vm, values)` injects host Python values into Suma globals.
- `make_environment(vm)` returns a host-side snapshot of VM globals.

## Adding Custom Imports

Import paths are searched in this order:
1. Relative to current file
2. `SUMA_PATH` environment variable
3. Paths from `-I` flag
4. Current working directory
5. Project root
6. `SUMA_STDLIB_PATHS` entries, searched left to right
7. Built-in `stdlib/` directory fallback

You can also import Python modules directly:

```suma
import "py:math"
import "py:json"
```

Python imports are disabled by default. Allow trusted modules explicitly with
`SUMA_PY_IMPORTS`, for example `SUMA_PY_IMPORTS=math,json`.

`SUMA_PATH` and `SUMA_STDLIB_PATHS` both use the platform path separator:
`:` on Unix-like systems, `;` on Windows.
