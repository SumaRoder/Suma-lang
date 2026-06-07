"""Public Python API for embedding the Suma-lang compiler and VM.

This module is the canonical home for `compile_source`, `create_vm`,
`run_source`, `run_program`, and the supporting types. The CLI entry point
(`suma_lang.cli`) is built on top of these functions.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from typing import Any, Literal

from suma_lang.backend.codegen.compiler import CompileError, Compiler
from suma_lang.backend.codegen.opcodes import ProgramBytecode
from suma_lang.backend.codegen.optimizer import format_program, optimize
from suma_lang.backend.codegen.serializer import BytecodeFormatError
from suma_lang.frontend.imports import ImportResolveError, ImportResolver
from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser.parser import Parser
from suma_lang.frontend.semantic.analyzer import Analyzer
from suma_lang.mid.ir.codegen import CodegenError, ir_to_bytecode
from suma_lang.mid.ir.lower import LowerError, lower_to_ir
from suma_lang.mid.ir.optimizer import optimize_ir
from suma_lang.runtime.vm.vm import VM

DiagnosticLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class Diagnostic:
    """Structured compiler diagnostic.

    Stable surface for IDE / LSP integration: groups the human-readable message
    with its category (`source`), severity, and an optional ``(line, column)``
    location. ``str(diagnostic)`` renders the legacy ``"[Source] message"``
    form, so existing CLI / test code that printed strings keeps working.
    """

    message: str
    source: str | None = None
    level: DiagnosticLevel = "error"
    location: tuple[int, int] | None = None

    def __str__(self) -> str:
        prefix = f"[{self.source}] " if self.source else ""
        return f"{prefix}{self.message}"


@dataclass(frozen=True)
class CompileOptions:
    optimize: bool = True
    use_ir: bool = False
    dump_opt: bool = False
    import_paths: tuple[str, ...] = ()


class CompileSourceError(Exception):
    """Raised when source compilation produces user-facing diagnostics."""

    def __init__(self, diagnostics: list[Diagnostic | str]) -> None:
        # Accept legacy ``list[str]`` callers as well as structured diagnostics
        # so external embedders that pre-date `Diagnostic` keep working.
        normalized: list[Diagnostic] = [
            d if isinstance(d, Diagnostic) else Diagnostic(d) for d in diagnostics
        ]
        self.diagnostics: list[Diagnostic] = normalized
        super().__init__("\n".join(str(d) for d in normalized))

    @property
    def messages(self) -> list[str]:
        """Legacy view returning the rendered diagnostic strings."""
        return [str(d) for d in self.diagnostics]


def _default_compile_options() -> CompileOptions:
    return CompileOptions()


_ANALYZER_LOCATION_RE = re.compile(r"^.*:(\d+):(\d+): ")


def _analyzer_diagnostic(message: str, *, level: DiagnosticLevel = "error") -> Diagnostic:
    location: tuple[int, int] | None = None
    match = _ANALYZER_LOCATION_RE.match(message)
    if match:
        line_text, column_text = match.groups()
        if line_text.isdigit() and column_text.isdigit():
            line = int(line_text)
            column = int(column_text)
            if line > 0 and column > 0:
                location = (line, column)
    return Diagnostic(message=message, source="Analyzer", level=level, location=location)


@dataclass(frozen=True)
class CompileResult:
    """Result bundle: bytecode plus any non-fatal compiler diagnostics."""

    program: ProgramBytecode
    warnings: tuple[Diagnostic, ...] = ()


def compile_source(
    source: str,
    filename: str = "<stdin>",
    import_paths: list[str] | None = None,
    options: CompileOptions | None = None,
) -> ProgramBytecode:
    """Compile source code to bytecode program.

    For access to non-fatal warnings (e.g. implicit shadowing), call
    :func:`compile_source_with_diagnostics` instead.
    """
    return compile_source_with_diagnostics(
        source, filename, import_paths=import_paths, options=options
    ).program


def compile_source_with_diagnostics(
    source: str,
    filename: str = "<stdin>",
    *,
    import_paths: list[str] | None = None,
    options: CompileOptions | None = None,
) -> CompileResult:
    """Compile source and return both bytecode and non-fatal warnings.

    Errors still raise :class:`CompileSourceError`; warnings are returned in
    ``CompileResult.warnings`` so callers (CLI, LSP, embedders) can render them.
    """
    active_options = options or _default_compile_options()
    if import_paths is not None:
        active_options = replace(active_options, import_paths=tuple(import_paths))

    try:
        tokens = Tokenizer.tokenize(source, file_name=filename)
        ast = Parser.parse(tokens)
    except SyntaxError as err:
        raise CompileSourceError([Diagnostic(str(err), source="Parser")]) from err
    try:
        ast = ImportResolver.with_defaults(active_options.import_paths).resolve_program(
            ast, filename
        )
    except ImportResolveError as err:
        raise CompileSourceError([Diagnostic(str(err), source="Import")]) from err

    analyzer = Analyzer()
    errors = analyzer.analyze(ast)
    if errors:
        raise CompileSourceError([_analyzer_diagnostic(str(err)) for err in errors])
    warnings = tuple(_analyzer_diagnostic(msg, level="warning") for msg in analyzer.warnings)

    try:
        if active_options.use_ir:
            # IR pipeline: AST → IR → optimize IR → bytecode
            ir_prog = lower_to_ir(ast)
            if active_options.optimize:
                ir_prog = optimize_ir(ir_prog)
            prog = ir_to_bytecode(ir_prog)
            if active_options.optimize:
                prog = optimize(prog)
        else:
            # Direct pipeline: AST → bytecode → optimize bytecode
            compiler = Compiler()
            prog = compiler.compile(ast)
            if active_options.optimize:
                prog = optimize(prog)
    except LowerError as err:
        raise CompileSourceError([Diagnostic(str(err), source="IR")]) from err
    except CodegenError as err:
        raise CompileSourceError([Diagnostic(str(err), source="Codegen")]) from err
    except CompileError as err:
        raise CompileSourceError([Diagnostic(str(err), source="Compiler")]) from err
    except BytecodeFormatError as err:
        raise CompileSourceError([Diagnostic(str(err), source="Bytecode")]) from err

    if active_options.dump_opt:
        print(format_program(prog), file=sys.stderr)

    return CompileResult(program=prog, warnings=warnings)


def create_vm(
    source_or_program: str | ProgramBytecode | None = None,
    *,
    filename: str = "<stdin>",
    import_paths: list[str] | None = None,
    options: CompileOptions | None = None,
    environment: dict[str, object] | None = None,
    inject: dict[str, object] | None = None,
) -> VM:
    """Build a VM from source text or an already compiled program."""
    if source_or_program is None:  # noqa: SIM108
        program = ProgramBytecode()
    elif isinstance(source_or_program, str):
        program = compile_source(
            source_or_program,
            filename,
            import_paths=import_paths,
            options=options,
        )
    else:
        program = source_or_program
    vm = VM(program)
    _inject_values(vm, environment=environment, inject=inject)
    return vm


def _inject_values(
    vm: VM,
    *,
    environment: dict[str, object] | None = None,
    inject: dict[str, object] | None = None,
) -> None:
    if environment:
        vm.inject_many(environment)
    if inject:
        vm.inject_many(inject)


def run_source(
    source: str,
    *,
    filename: str = "<stdin>",
    import_paths: list[str] | None = None,
    options: CompileOptions | None = None,
    vm: VM | None = None,
    environment: dict[str, object] | None = None,
    inject: dict[str, object] | None = None,
) -> Any:
    """Compile and execute source text."""
    program = compile_source(source, filename, import_paths=import_paths, options=options)
    active_vm = vm or VM(program)
    if vm is not None:
        vm.load_program(program)
    _inject_values(active_vm, environment=environment, inject=inject)
    return active_vm.run()


def run_program(
    program: ProgramBytecode,
    *,
    vm: VM | None = None,
    environment: dict[str, object] | None = None,
    inject: dict[str, object] | None = None,
) -> Any:
    """Execute an already compiled program."""
    active_vm = vm or VM(program)
    if vm is not None:
        vm.load_program(program)
    _inject_values(active_vm, environment=environment, inject=inject)
    return active_vm.run()


def make_environment(
    program_or_vm: ProgramBytecode | VM | None = None,
) -> dict[str, object]:
    """Return a host-side snapshot of the current execution environment."""
    if isinstance(program_or_vm, VM):
        return program_or_vm.environment()
    if program_or_vm is None:
        return {}
    return VM(program_or_vm).environment()


def inject_environment(vm: VM, values: dict[str, object]) -> VM:
    """Inject host values into an existing VM."""
    vm.inject_many(values)
    return vm
