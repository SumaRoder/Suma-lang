# Embedding from Python

Use the `suma_lang` package as a library: compile Suma sources at runtime,
inject host Python values into Suma globals, and read results back. This is the
path tools should take to host scripted logic without spawning a subprocess.

## Install the package

```bash
pip install -e .
```

The package exposes a small, stable surface from `suma_lang/__init__.py`:

```python
from suma_lang import (
    BytecodeFormatError,
    CompileOptions,
    CompileSourceError,
    Diagnostic,
    VM,
    VMError,
    compile_source,
    create_vm,
    inject_environment,
    make_environment,
    run_program,
    run_source,
)
```

## The 60-second tour

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

## API reference

### `compile_source(source, filename="<stdin>", *, import_paths=None, options=None) -> ProgramBytecode`

Compile source text into a `ProgramBytecode` object suitable for execution or
serialization. Raises [`CompileSourceError`](#compilesourceerror) on syntax,
import-resolution, or semantic-analysis failures.

```python
program = suma_lang.compile_source(
    source_text,
    filename="user_script.suma",
    options=suma_lang.CompileOptions(use_ir=True, optimize=True),
)
```

### `create_vm(source_or_program=None, *, filename, import_paths, options, environment, inject) -> VM`

Build a [`VM`](#vm) ready to execute. Accepts source text *or* a pre-compiled
program. Use `environment=` or `inject=` to seed host values.

```python
vm = suma_lang.create_vm(
    source_text,
    inject={"api_token": "abc123", "max_retries": 5},
)
vm.run()
```

### `run_source(source, *, inject=None, options=None, ...) -> Any`

Compile and execute in one call. Returns whatever `main()` returns.

```python
exit_code = suma_lang.run_source(source_text, inject={"seed": 40})
```

### `run_program(program, *, inject=None, ...) -> Any`

Execute an already-compiled `ProgramBytecode`. Useful when you load `.sumac`
files via the serializer.

```python
from suma_lang.backend.codegen.serializer import deserialize

with open("script.sumac", "rb") as f:
    program = deserialize(f.read())
result = suma_lang.run_program(program)
```

### `inject_environment(vm, values) -> VM`

Bulk-set Suma globals on an existing VM. Returns the VM for chaining.

```python
vm = suma_lang.create_vm(source)
suma_lang.inject_environment(vm, {"x": 1, "y": 2, "name": "alice"})
```

### `make_environment(program_or_vm) -> dict[str, object]`

Read the current values of all globals as a plain Python dict.

```python
state = suma_lang.make_environment(vm)
print(state["result"])  # whatever Suma assigned to it
```

## Types

### `CompileOptions`

A frozen dataclass that controls compilation. All fields have safe defaults.

| Field           | Type                | Default | Meaning                                       |
|-----------------|---------------------|---------|-----------------------------------------------|
| `optimize`      | `bool`              | `True`  | Run bytecode-level peephole optimizer.        |
| `use_ir`        | `bool`              | `False` | Use the IR pipeline (AST → IR → bytecode).    |
| `dump_opt`      | `bool`              | `False` | Dump the optimized pseudo-code to stderr.     |
| `import_paths`  | `tuple[str, ...]`   | `()`    | Extra search paths for `import "..."`.        |

```python
options = suma_lang.CompileOptions(
    use_ir=True,
    import_paths=("/usr/share/suma/modules",),
)
```

### `Diagnostic`

A frozen dataclass describing a single compilation error. Carried inside
`CompileSourceError.diagnostics`.

```python
@dataclass(frozen=True)
class Diagnostic:
    message: str
    source: str | None = None     # "Parser", "Import", "Analyzer"
    level: Literal["error", "warning"] = "error"
    location: tuple[int, int] | None = None
```

`str(diagnostic)` renders the legacy `"[Source] message"` form, so code that
just prints diagnostics needs no changes.

### `CompileSourceError`

Raised when compilation produces user-facing diagnostics.

```python
try:
    suma_lang.compile_source(source)
except suma_lang.CompileSourceError as err:
    for d in err.diagnostics:
        print(d.source, d.message)
    # Legacy view, if you only need strings:
    print(err.messages)
```

### `BytecodeFormatError`

Subclass of `ValueError`, raised by `deserialize()` when reading a malformed
`.sumac` file (bad magic, unsupported version, truncated section).

### `VMError`

Raised by [`VM.run()`](#vm) for runtime errors the VM can't recover from
(division by zero, unwrap on `Err`, type mismatches the analyzer couldn't catch).

### `VM`

The execution engine. Created via `create_vm()` or `VM(program)` directly.

Useful methods:

| Method                                              | Purpose                                                    |
|-----------------------------------------------------|------------------------------------------------------------|
| `run() -> Any`                                      | Execute `main()`, return its result.                       |
| `inject(name, value)`                               | Set a single Suma global.                                  |
| `inject_many(values)`                               | Set globals from a dict.                                   |
| `get_global(name, default=...) -> Any`              | Read a Suma global.                                        |
| `environment() -> dict[str, Any]`                   | Snapshot all globals.                                      |
| `load_program(program, *, reset_globals=False)`     | Swap in a new program. Optionally clear globals.           |

## Calling Suma functions from Python

`SumaCallable` wraps a Suma function and exposes it as a Python callable:

```python
program = suma_lang.compile_source("""
pub greet(name: Str): Str {
    return "Hello, " + name + "!"
}

pub main(): Int { return 0 }
""")

vm = suma_lang.create_vm(program)
greet = vm.get_global("greet")    # returns a SumaCallable
print(greet("Alice"))              # "Hello, Alice!"
```

## Calling Python from Suma

Suma can import Python modules and call them via the `py:` prefix.
Host applications must allow-list the modules they expose via the
`SUMA_PY_IMPORTS` environment variable (a comma-separated list of importable
names).

```python
import os
os.environ["SUMA_PY_IMPORTS"] = "math,statistics"
```

```suma
import "py:math"
import "py:json"

pub main(): Int {
    payload: Str = json.dumps(List(40, 2))
    print(payload)
    return math.floor(42.7)
}
```

## Catch compile and runtime errors separately

Wrap compilation and execution in their own `try` blocks. That way an IDE
or CI integration can tell a bad source file apart from a runtime crash:

```python
try:
    program = suma_lang.compile_source(source)
except suma_lang.CompileSourceError as err:
    # Surface diagnostics to the user with structured info.
    for d in err.diagnostics:
        report(level=d.level, source=d.source, message=d.message)
    raise

try:
    result = suma_lang.run_program(program, inject=context)
except suma_lang.VMError as err:
    log.error("Suma runtime error: %s", err)
    raise

return result
```
