from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from suma_lang.api import CompileOptions, compile_source
from suma_lang.runtime.vm.vm import VM

EXAMPLE_TESTS = sorted([*Path("examples/tests").glob("*.suma"), Path("examples/factorial.suma")])

PIPELINES = [
    ("direct-opt", CompileOptions(use_ir=False, optimize=True)),
    ("ir-opt", CompileOptions(use_ir=True, optimize=True)),
    ("direct-no-opt", CompileOptions(use_ir=False, optimize=False)),
    ("ir-no-opt", CompileOptions(use_ir=True, optimize=False)),
]


def _run_example(path: Path, options: CompileOptions) -> tuple[object, str]:
    program = compile_source(path.read_text(), str(path), options=options)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = VM(program).run()
    return result, buf.getvalue()


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
    options = CompileOptions(use_ir=use_ir, optimize=optimize)
    result, _ = _run_example(path, options)
    assert result == 42


@pytest.mark.parametrize("path", EXAMPLE_TESTS, ids=lambda path: path.stem)
def test_pipelines_agree_on_stdout(path: Path):
    """All four (direct|IR) × (opt|no-opt) pipelines must agree on stdout."""
    runs = {label: _run_example(path, opts) for label, opts in PIPELINES}
    baseline_label, (baseline_result, baseline_stdout) = next(iter(runs.items()))
    for label, (result, stdout) in runs.items():
        assert result == baseline_result, (
            f"{label} returned {result!r}, baseline {baseline_label} returned {baseline_result!r}"
        )
        assert stdout == baseline_stdout, (
            f"{label} stdout diverges from {baseline_label}:\n"
            f"--- {baseline_label} ---\n{baseline_stdout}"
            f"--- {label} ---\n{stdout}"
        )
