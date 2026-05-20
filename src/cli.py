"""Suma-lang compiler and VM runner."""

import argparse
import os
import sys
from dataclasses import dataclass, replace
from typing import Any

from src.backend.codegen.compiler import Compiler
from src.backend.codegen.opcodes import ProgramBytecode
from src.backend.codegen.optimizer import format_program, optimize
from src.backend.codegen.serializer import deserialize, serialize
from src.frontend.imports import ImportResolveError, ImportResolver
from src.frontend.lexer.tokenizer import Tokenizer
from src.frontend.parser.parser import Parser
from src.frontend.semantic.analyzer import Analyzer
from src.mid.ir.codegen import ir_to_bytecode

# IR pipeline
from src.mid.ir.lower import lower_to_ir
from src.mid.ir.optimizer import optimize_ir
from src.runtime.vm.vm import VM, VMError

# Global flags toggled by CLI
_optimize = True
_use_ir = False
_dump_opt = False
_import_paths: list[str] = []

LAST_VM: VM | None = None


@dataclass(frozen=True)
class CompileOptions:
    optimize: bool = True
    use_ir: bool = False
    dump_opt: bool = False
    import_paths: tuple[str, ...] = ()


class CompileSourceError(Exception):
    """Raised when source compilation produces user-facing diagnostics."""

    def __init__(self, diagnostics: list[str]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(diagnostics))


def _default_compile_options() -> CompileOptions:
    return CompileOptions(
        optimize=_optimize,
        use_ir=_use_ir,
        dump_opt=_dump_opt,
        import_paths=tuple(_import_paths),
    )


def compile_source(
    source: str,
    filename: str = "<stdin>",
    import_paths: list[str] | None = None,
    options: CompileOptions | None = None,
):
    """Compile source code to bytecode program."""
    active_options = options or _default_compile_options()
    if import_paths is not None:
        active_options = replace(active_options, import_paths=tuple(import_paths))

    try:
        tokens = Tokenizer.tokenize(source, file_name=filename)
        ast = Parser.parse(tokens)
    except SyntaxError as err:
        raise CompileSourceError([str(err)]) from err
    try:
        ast = ImportResolver.with_defaults(active_options.import_paths).resolve_program(
            ast, filename
        )
    except ImportResolveError as err:
        raise CompileSourceError([f"[Import] {err}"]) from err

    analyzer = Analyzer()
    errors = analyzer.analyze(ast)
    if errors:
        raise CompileSourceError([f"[Analyzer] {err}" for err in errors])

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

    if active_options.dump_opt:
        print(format_program(prog), file=sys.stderr)

    return prog


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
    if source_or_program is None:
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
    *,
    include_runtime: bool = False,
) -> dict[str, object]:
    """Return a host-side snapshot of the current execution environment."""
    if isinstance(program_or_vm, VM):
        env = program_or_vm.environment()
    elif program_or_vm is None:
        env = {}
    else:
        env = VM(program_or_vm).environment()
    if include_runtime:
        env = dict(env)
        env["_optimize"] = _optimize
        env["_use_ir"] = _use_ir
        env["_dump_opt"] = _dump_opt
        env["_import_paths"] = tuple(_import_paths)
    return env


def inject_environment(vm: VM, values: dict[str, object]) -> VM:
    """Inject host values into an existing VM."""
    vm.inject_many(values)
    return vm


def cmd_compile(
    input_path: str, output_path: str | None = None, options: CompileOptions | None = None
) -> None:
    """Compile a .suma file to .sumac bytecode."""
    with open(input_path, "r") as f:
        source = f.read()

    prog = compile_source(source, input_path, options=options)
    data = serialize(prog)

    if output_path is None:
        base = os.path.splitext(input_path)[0]
        output_path = base + ".sumac"

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"Compiled {input_path} -> {output_path} ({len(data)} bytes)")


def cmd_run(input_path: str) -> None:
    """Run a .sumac bytecode file."""
    global LAST_VM
    with open(input_path, "rb") as f:
        data = f.read()

    prog = deserialize(data)
    vm = VM(prog)
    LAST_VM = vm
    result = vm.run()
    if result is not None and result != 0:
        print(result)


def cmd_build_and_run(input_path: str, options: CompileOptions | None = None) -> None:
    """Compile and run a .suma source file."""
    global LAST_VM
    with open(input_path, "r") as f:
        source = f.read()

    prog = compile_source(source, input_path, options=options)
    vm = VM(prog)
    LAST_VM = vm
    result = vm.run()
    if result is not None and result != 0:
        print(result)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="suma",
        description="Compile and run Suma source files or bytecode.",
    )
    parser.add_argument(
        "--no-opt",
        action="store_true",
        help="disable bytecode optimization",
    )
    parser.add_argument(
        "--ir",
        action="store_true",
        help="use IR optimization pipeline",
    )
    parser.add_argument(
        "--dump-opt",
        action="store_true",
        help="print optimized bytecode pseudo-code to stderr",
    )
    parser.add_argument(
        "-I",
        "--import-path",
        dest="import_paths",
        action="append",
        default=[],
        metavar="PATH",
        help="add Suma import search path",
    )
    parser.add_argument(
        "command",
        choices=("run", "compile", "execute"),
        help="command to run",
    )
    parser.add_argument("file", help="input .suma or .sumac file")
    parser.add_argument(
        "output",
        nargs="?",
        help="output .sumac path for the compile command",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = _build_arg_parser()
    parsed = parser.parse_args(args)
    if parsed.output is not None and parsed.command != "compile":
        parser.error(f"{parsed.command} accepts only one file argument")

    options = CompileOptions(
        optimize=not parsed.no_opt,
        use_ir=parsed.ir,
        dump_opt=parsed.dump_opt,
        import_paths=tuple(parsed.import_paths),
    )

    try:
        if parsed.command == "run":
            cmd_build_and_run(parsed.file, options=options)
        elif parsed.command == "compile":
            cmd_compile(parsed.file, parsed.output, options=options)
        elif parsed.command == "execute":
            cmd_run(parsed.file)
    except CompileSourceError as err:
        for diagnostic in err.diagnostics:
            print(diagnostic, file=sys.stderr)
        sys.exit(1)
    except VMError as err:
        print(f"[Runtime] {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
