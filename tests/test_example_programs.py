from __future__ import annotations

from pathlib import Path

import pytest

import src.cli as cli
from src.runtime.vm.vm import VM

EXAMPLE_TESTS = sorted([*Path("examples/tests").glob("*.suma"), Path("examples/factorial.suma")])


def _run_example(path: Path, *, use_ir: bool, optimize: bool):
    old_use_ir = cli._use_ir
    old_optimize = cli._optimize
    old_import_paths = list(cli._import_paths)
    try:
        cli._use_ir = use_ir
        cli._optimize = optimize
        cli._import_paths = []
        program = cli.compile_source(path.read_text(), str(path))
        return VM(program).run()
    finally:
        cli._use_ir = old_use_ir
        cli._optimize = old_optimize
        cli._import_paths = old_import_paths


@pytest.mark.parametrize("path", EXAMPLE_TESTS, ids=lambda path: path.stem)
@pytest.mark.parametrize(
    ("use_ir", "optimize"),
    [
        (False, True),
        (True, True),
        (False, False),
        (True, False),
    ],
    ids=["direct-opt", "ir-opt", "direct-no-opt", "ir-no-opt"],
)
def test_example_program_returns_42(path: Path, use_ir: bool, optimize: bool):
    assert _run_example(path, use_ir=use_ir, optimize=optimize) == 42
