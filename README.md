# Suma-lang

A statically-typed language that compiles to bytecode, runs on a stack-based VM.

## What It Gives You

- **Static typing** with compile-time checks
- **Result types** for explicit error handling (`Ok` / `Err`)
- **Pattern matching** for Results, types, and literal values: `value -> { ... }`
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

The language uses Result types instead of exceptions:

```suma
pub divide(a: Int, b: Int) {
    if (b == 0) {
        return Err("Division by zero")
    }
    return Ok(a / b)
}

pub main(): Int {
    result: R = divide(10, 2)
    result -> {
        Ok = print("Result: " + to_str(it))
        Err = print("Error: " + it)
    }
    return 0
}
```

Classes work like this:

```suma
pub Person {
    pri name: Str
    pri age: Int

    pub init(name: Str, age: Int) {
        this.name = name
        this.age = age
    }

    pub greet(): Str {
        return "Hello, I'm " + this.name
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

**Backend** — Generates bytecode, applies peephole optimizations, serializes to `.sumac` files.

**Runtime** — Stack-based VM executes the bytecode.

```
.suma source → Frontend → AST → Midend → IR → Backend → .sumac bytecode → VM
```

## Project Layout

```
src/
├── frontend/          # Lexer, parser, semantic analysis, imports
├── mid/               # IR generation and optimization
├── backend/           # Bytecode generation and serialization
└── runtime/           # The VM implementation

stdlib/                # Standard library in Suma
examples/              # Example programs
tests/                 # Test suite
```

## Running Tests

```bash
PYTHONPATH=. python tests/test_optimizer.py
PYTHONPATH=. python tests/test_cli.py
PYTHONPATH=. python tests/test_imports.py
```

## Command Line Options

```bash
suma run <file>        # Compile and run
suma compile <file>    # Just compile to .sumac
suma execute <file>    # Run existing .sumac file
suma -I <path>         # Add import search path
suma --no-opt          # Disable optimizations
```

## Adding Custom Imports

Import paths are searched in this order:
1. Relative to current file
2. `SUMA_PATH` environment variable
3. Paths from `-I` flag
4. Current working directory
5. Project root
6. `stdlib/` directory

You can also import Python modules directly:

```suma
import "py:math"
import "py:numpy as np"
```
