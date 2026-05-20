"""Public Python API for embedding Suma-lang."""

from src import (
    VM,
    CompileOptions,
    CompileSourceError,
    VMError,
    compile_source,
    create_vm,
    inject_environment,
    make_environment,
    run_program,
    run_source,
)

__all__ = [
    "CompileOptions",
    "CompileSourceError",
    "VM",
    "VMError",
    "compile_source",
    "create_vm",
    "inject_environment",
    "make_environment",
    "run_source",
    "run_program",
]
