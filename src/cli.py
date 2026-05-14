"""Suma-lang compiler and VM runner."""

import os
import sys

from src.backend.codegen.compiler import Compiler
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
from src.runtime.vm.vm import VM

# Global flags toggled by CLI
_optimize = True
_use_ir = False
_dump_opt = False
_import_paths: list[str] = []


def compile_source(source: str, filename: str = "<stdin>", import_paths: list[str] = None):
    """Compile source code to bytecode program."""
    tokens = Tokenizer.tokenize(source, file_name=filename)
    ast = Parser.parse(tokens)
    try:
        ast = ImportResolver.with_defaults(import_paths or _import_paths).resolve_program(
            ast, filename
        )
    except ImportResolveError as err:
        print(f"[Import] {err}", file=sys.stderr)
        sys.exit(1)

    analyzer = Analyzer()
    errors = analyzer.analyze(ast)
    if errors:
        for err in errors:
            print(f"[Analyzer] {err}", file=sys.stderr)
        sys.exit(1)

    if _use_ir:
        # IR pipeline: AST → IR → optimize IR → bytecode
        ir_prog = lower_to_ir(ast)
        if _optimize:
            ir_prog = optimize_ir(ir_prog)
        prog = ir_to_bytecode(ir_prog)
        if _optimize:
            prog = optimize(prog)
    else:
        # Direct pipeline: AST → bytecode → optimize bytecode
        compiler = Compiler()
        prog = compiler.compile(ast)
        if _optimize:
            prog = optimize(prog)

    if _dump_opt:
        print(format_program(prog), file=sys.stderr)

    return prog


def cmd_compile(input_path: str, output_path: str = None) -> None:
    """Compile a .suma file to .sumac bytecode."""
    with open(input_path, "r") as f:
        source = f.read()

    prog = compile_source(source, input_path)
    data = serialize(prog)

    if output_path is None:
        base = os.path.splitext(input_path)[0]
        output_path = base + ".sumac"

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"Compiled {input_path} -> {output_path} ({len(data)} bytes)")


def cmd_run(input_path: str) -> None:
    """Run a .sumac bytecode file."""
    with open(input_path, "rb") as f:
        data = f.read()

    prog = deserialize(data)
    vm = VM(prog)
    result = vm.run()
    if result is not None:
        print(result)


def cmd_build_and_run(input_path: str) -> None:
    """Compile and run a .suma source file."""
    with open(input_path, "r") as f:
        source = f.read()

    prog = compile_source(source, input_path)
    vm = VM(prog)
    result = vm.run()
    if result is not None:
        print(result)


def main() -> None:
    global _optimize, _use_ir, _dump_opt, _import_paths

    args = sys.argv[1:]
    # Extract flags
    if "--no-opt" in args:
        _optimize = False
        args.remove("--no-opt")
    if "--ir" in args:
        _use_ir = True
        args.remove("--ir")
    if "--dump-opt" in args:
        _dump_opt = True
        args.remove("--dump-opt")

    parsed_args = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-I", "--import-path"):
            if i + 1 >= len(args):
                print(f"Error: {arg} requires a path", file=sys.stderr)
                sys.exit(1)
            _import_paths.append(args[i + 1])
            i += 2
        elif arg.startswith("-I") and len(arg) > 2:
            _import_paths.append(arg[2:])
            i += 1
        elif arg.startswith("--import-path="):
            _import_paths.append(arg.split("=", 1)[1])
            i += 1
        else:
            parsed_args.append(arg)
            i += 1
    args = parsed_args

    if len(args) < 1 or args[0] in ("--help", "-h"):
        print("Usage: suma <command> [options] <file>")
        print("")
        print("Commands:")
        print("  run <file.suma>        Compile and run source file")
        print("  compile <file.suma>    Compile to .sumac bytecode")
        print("  execute <file.sumac>   Run compiled bytecode")
        print("")
        print("Options:")
        print("  --no-opt               Disable bytecode optimization")
        print("  --ir                   Use IR optimization pipeline")
        print("  --dump-opt             Print optimized bytecode pseudo-code")
        print("  -I, --import-path PATH Add Suma import search path")
        print("  -h, --help             Show this help message")
        sys.exit(0 if args and args[0] in ("--help", "-h") else 1)

    cmd = args[0]
    if len(args) < 2:
        print(f"Error: {cmd} requires a file argument", file=sys.stderr)
        sys.exit(1)

    path = args[1]

    if cmd == "run":
        cmd_build_and_run(path)
    elif cmd == "compile":
        output = args[2] if len(args) > 2 else None
        cmd_compile(path, output)
    elif cmd == "execute":
        cmd_run(path)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
