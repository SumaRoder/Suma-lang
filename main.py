"""Compatibility shim for the Suma-lang CLI.

The installable console script lives in `suma_lang.cli`. This file lets you
run `python main.py ...` directly from a source checkout (before
`pip install -e .`), and lets legacy tests/scripts import names via
`from main import compile_source, CompileSourceError, ...`.

Suma-lang CLI 的兼容性垫片：允许在未安装时直接 `python main.py`，
并保留 `from main import ...` 的旧入口。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from suma_lang import cli as _cli  # noqa: E402
from suma_lang.cli import (  # noqa: E402,F401
    CompileOptions,
    CompileSourceError,
    cmd_build_and_run,
    cmd_compile,
    cmd_run,
    compile_source,
    create_vm,
    inject_environment,
    main,
    make_environment,
    run_program,
    run_source,
)


def __getattr__(name: str):
    # Forward any other lookup (e.g. legacy `_use_ir` reads) to the cli module.
    return getattr(_cli, name)


if __name__ == "__main__":
    main()
