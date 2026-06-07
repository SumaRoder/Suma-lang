"""Suma-lang command-line interface.

The compiler and VM Python APIs live in :mod:`suma_lang.api`; this module is
just the ``suma`` console script (argparse + a few ``cmd_*`` helpers).
"""

from __future__ import annotations

import argparse
import os
import sys

from suma_lang.api import (
    CompileOptions,
    CompileSourceError,
    compile_source,
    create_vm,
    inject_environment,
    make_environment,
    run_program,
    run_source,
)
from suma_lang.backend.codegen.serializer import BytecodeFormatError, deserialize, serialize
from suma_lang.runtime.vm.vm import VM, VMError

__all__ = [
    "CompileOptions",
    "CompileSourceError",
    "compile_source",
    "create_vm",
    "inject_environment",
    "make_environment",
    "run_program",
    "run_source",
    "cmd_compile",
    "cmd_run",
    "cmd_build_and_run",
    "main",
]


def cmd_compile(
    input_path: str, output_path: str | None = None, options: CompileOptions | None = None
) -> None:
    """Compile a .suma file to .sumac bytecode."""
    with open(input_path) as f:
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
    with open(input_path, "rb") as f:
        data = f.read()

    prog = deserialize(data)
    result = VM(prog).run()
    if result is not None and result != 0:
        print(result)


def cmd_build_and_run(input_path: str, options: CompileOptions | None = None) -> None:
    """Compile and run a .suma source file."""
    with open(input_path) as f:
        source = f.read()

    prog = compile_source(source, input_path, options=options)
    result = VM(prog).run()
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
    except BytecodeFormatError as err:
        print(f"[Bytecode] {err}", file=sys.stderr)
        sys.exit(1)
    except VMError as err:
        print(f"[Runtime] {err}", file=sys.stderr)
        sys.exit(1)
    except UnicodeError as err:
        print(f"[IO] {err}", file=sys.stderr)
        sys.exit(1)
    except OSError as err:
        print(f"[IO] {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
