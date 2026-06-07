from __future__ import annotations

import contextlib
import io
from dataclasses import replace
from pathlib import Path

import pytest

from suma_lang.api import CompileOptions, compile_source
from suma_lang.runtime.vm.vm import VM

EXAMPLE_TESTS = sorted([*Path("examples/tests").glob("*.suma"), Path("examples/factorial.suma")])

ENTRYPOINT_EXAMPLES = [
    pytest.param(Path("examples/hello.suma"), 0, "Hello, World!\n", (), id="hello"),
    pytest.param(Path("examples/class.suma"), 0, "Hello, I'm Alice\nResult: 5\n", (), id="class"),
    pytest.param(Path("examples/loop.suma"), 0, "i = 1\ni = 2\ni = 3\ni = 4\n", (), id="loop"),
    pytest.param(
        Path("examples/import_absolute.suma"),
        100,
        "absolute score = 100\nabsolute class = excellent\neven score = true\n",
        (),
        id="import_absolute",
    ),
    pytest.param(
        Path("examples/import_custom_path.suma"),
        42,
        "== custom path ==\ntriple = 42\n",
        ("examples",),
        id="import_custom_path",
    ),
    pytest.param(
        Path("examples/import_stdlib.suma"),
        201,
        (
            "sum = 58\nproduct = 24\nmax/min = 12/3\nfib(12) = 144\npow(3, 5) = 243\n"
            "gcd/lcm = 42/42\nclamp = 100\nrepeat = hahaha\nscore class = excellent\n"
            "positive score = 201\n"
        ),
        (),
        id="import_stdlib",
    ),
    pytest.param(
        Path("examples/import_python.suma"),
        9,
        "sqrt = 9.0\n[1, 2, 3]\n",
        (),
        id="import_python",
    ),
    pytest.param(
        Path("examples/stress_classes.suma"),
        76,
        (
            "primary:14\nprimary:15\nprimary:17\nprimary:21\nprimary:25\nprimary:27\n"
            "primary:31\nprimary:38\nlast counter = 38\ntotal=385, count=10, avg=38\n"
            "reset counter = primary:38\n"
        ),
        (),
        id="stress_classes",
    ),
    pytest.param(
        Path("examples/stress_numeric.suma"),
        3746,
        (
            "fib_iter(20) = 6765\nfactorial_loop(12) = 479001600\ngcd(462, 1071) = 21\n"
            "lcm(21, 6) = 42\nbit_mix(123) = 99\nchecksum(40) = 3746\n"
        ),
        (),
        id="stress_numeric",
    ),
    pytest.param(
        Path("examples/stress_result_pipeline.suma"),
        0,
        (
            "first digit = 4\nsecond digit = 2\nthird digit = 0\nparsed number = 420\n"
            "division result = 60\npipeline ok = 60\nfirst digit = 9\n"
            "bad parse expected err = parse failed: not a digit: x\n"
            "first digit = 1\nsecond digit = 2\nthird digit = 0\nparsed number = 120\n"
            "bad div expected err = division failed: divide by zero\n"
        ),
        (),
        id="stress_result_pipeline",
    ),
    pytest.param(
        Path("examples/stress_strings_lists.suma"),
        89,
        (
            "classification suma = medium\nclassification language = long\n"
            "xs size = 6\nxs[0] = 1\nxs[3] = 5\na|e|i\nlist score = 86\nslice length = 3\n"
        ),
        (),
        id="stress_strings_lists",
    ),
]

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


@pytest.mark.parametrize(
    ("path", "expected_result", "expected_stdout", "import_paths"), ENTRYPOINT_EXAMPLES
)
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
def test_entrypoint_examples_smoke(
    path: Path,
    expected_result: object,
    expected_stdout: str,
    import_paths: tuple[str, ...],
    use_ir: bool,
    optimize: bool,
):
    options = CompileOptions(use_ir=use_ir, optimize=optimize)
    if import_paths:
        options = replace(options, import_paths=import_paths)
    result, stdout = _run_example(path, options)
    assert result == expected_result
    assert stdout == expected_stdout


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
def test_decorators_example_smoke(monkeypatch: pytest.MonkeyPatch, use_ir: bool, optimize: bool):
    # decorators.suma imports a Python helper module that is not in the default
    # py-import allowlist; the environment opt-in is part of the example's
    # contract, so the test exercises that path as well.
    monkeypatch.setenv("SUMA_PY_IMPORTS", "examples.decorator_helpers")
    options = CompileOptions(use_ir=use_ir, optimize=optimize)
    result, stdout = _run_example(Path("examples/decorators.suma"), options)
    assert result == 42
    assert stdout == "[trace:answer] before\n[trace:answer] after = 42\n"
