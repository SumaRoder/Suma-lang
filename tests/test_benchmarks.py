"""Performance benchmarks for the compile pipeline and the VM.

Run with `pytest --benchmark-enable --benchmark-only` to get measurements; the
default test run uses `--benchmark-disable` (set in pyproject.toml) so these
tests execute as cheap smoke checks instead of full timed runs.

The run benchmarks separate cold execution (VM construction + run) from hot
execution (reusing a VM instance) so initialization cost does not hide dispatch
or bytecode-shape regressions.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from suma_lang.api import CompileOptions, compile_source, run_program
from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser.ast_nodes import Program
from suma_lang.frontend.parser.parser import Parser
from suma_lang.frontend.semantic.analyzer import Analyzer
from suma_lang.runtime.vm.vm import VM

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"
EXPECTED_RESULTS = {
    "bench_fib.suma": 832040,
    "factorial.suma": 42,
    "stress_numeric.suma": 3746,
    "stress_strings_lists.suma": 89,
    "stress_classes.suma": 76,
    "stress_result_pipeline.suma": 0,
    "bench_closures.suma": 60900,
    "bench_match.suma": 36993,
}


def _load(name: str) -> str:
    return (EXAMPLES_ROOT / name).read_text(encoding="utf-8")


def _without_prints(source: str) -> str:
    """Keep benchmark results focused on VM work, not stdout capture."""
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("print("))


def _assert_result(label: str, run: Callable[[], object]) -> object:
    result = run()
    assert result == EXPECTED_RESULTS[label]
    return result


def _analyze_program(program: Program) -> list[str]:
    errors = Analyzer().analyze(program)
    assert errors == []
    return errors


@pytest.fixture(scope="module")
def fib_source() -> str:
    return _load("bench_fib.suma")


@pytest.fixture(scope="module")
def factorial_source() -> str:
    return _load("factorial.suma")


@pytest.fixture(scope="module")
def stress_numeric_source() -> str:
    return _without_prints(_load("stress_numeric.suma"))


@pytest.fixture(scope="module")
def stress_strings_source() -> str:
    return _without_prints(_load("stress_strings_lists.suma"))


@pytest.fixture(scope="module")
def stress_classes_source() -> str:
    return _without_prints(_load("stress_classes.suma"))


@pytest.fixture(scope="module")
def stress_result_pipeline_source() -> str:
    return _without_prints(_load("stress_result_pipeline.suma"))


@pytest.fixture(scope="module")
def bench_closures_source() -> str:
    return _load("bench_closures.suma")


@pytest.fixture(scope="module")
def bench_match_source() -> str:
    return _load("bench_match.suma")


# ---------------------------------------------------------------------------
# Compile-only benchmarks: isolates frontend + optimizer cost
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="compile")
def test_compile_fib(benchmark, fib_source):
    benchmark(compile_source, fib_source, "bench_fib.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_factorial(benchmark, factorial_source):
    benchmark(compile_source, factorial_source, "factorial.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_stress_numeric(benchmark, stress_numeric_source):
    benchmark(compile_source, stress_numeric_source, "stress_numeric.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_stress_strings(benchmark, stress_strings_source):
    benchmark(compile_source, stress_strings_source, "stress_strings_lists.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_stress_classes(benchmark, stress_classes_source):
    benchmark(compile_source, stress_classes_source, "stress_classes.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_stress_result_pipeline(benchmark, stress_result_pipeline_source):
    benchmark(compile_source, stress_result_pipeline_source, "stress_result_pipeline.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_bench_closures(benchmark, bench_closures_source):
    benchmark(compile_source, bench_closures_source, "bench_closures.suma")


@pytest.mark.benchmark(group="compile")
def test_compile_bench_match(benchmark, bench_match_source):
    benchmark(compile_source, bench_match_source, "bench_match.suma")


@pytest.mark.benchmark(group="compile-ir")
def test_compile_ir_stress_numeric(benchmark, stress_numeric_source):
    benchmark(
        compile_source,
        stress_numeric_source,
        "stress_numeric.suma",
        options=CompileOptions(use_ir=True),
    )


# ---------------------------------------------------------------------------
# Frontend stage benchmarks: isolates lexer, parser, and analyzer cost
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="frontend-stage")
def test_tokenize_stress_numeric(benchmark, stress_numeric_source):
    tokens = benchmark(Tokenizer.tokenize, stress_numeric_source, file_name="stress_numeric.suma")
    assert tokens


@pytest.mark.benchmark(group="frontend-stage")
def test_parse_stress_numeric(benchmark, stress_numeric_source):
    tokens = Tokenizer.tokenize(stress_numeric_source, file_name="stress_numeric.suma")
    program = benchmark(Parser.parse, tokens)
    assert program.declarations


@pytest.mark.benchmark(group="frontend-stage")
def test_analyze_stress_numeric(benchmark, stress_numeric_source):
    tokens = Tokenizer.tokenize(stress_numeric_source, file_name="stress_numeric.suma")
    program = Parser.parse(tokens)
    benchmark(_analyze_program, program)


# ---------------------------------------------------------------------------
# Cold-run benchmarks: VM construction + execution
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_fib(benchmark, fib_source):
    program = compile_source(fib_source, "bench_fib.suma")
    benchmark(lambda: _assert_result("bench_fib.suma", lambda: run_program(program)))


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_factorial(benchmark, factorial_source):
    program = compile_source(factorial_source, "factorial.suma")
    benchmark(lambda: _assert_result("factorial.suma", lambda: run_program(program)))


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_stress_numeric(benchmark, stress_numeric_source):
    program = compile_source(stress_numeric_source, "stress_numeric.suma")
    benchmark(lambda: _assert_result("stress_numeric.suma", lambda: run_program(program)))


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_stress_strings(benchmark, stress_strings_source):
    program = compile_source(stress_strings_source, "stress_strings_lists.suma")
    benchmark(lambda: _assert_result("stress_strings_lists.suma", lambda: run_program(program)))


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_stress_classes(benchmark, stress_classes_source):
    program = compile_source(stress_classes_source, "stress_classes.suma")
    benchmark(lambda: _assert_result("stress_classes.suma", lambda: run_program(program)))


@pytest.mark.benchmark(group="run-cold")
def test_cold_run_stress_result_pipeline(benchmark, stress_result_pipeline_source):
    program = compile_source(stress_result_pipeline_source, "stress_result_pipeline.suma")
    benchmark(lambda: _assert_result("stress_result_pipeline.suma", lambda: run_program(program)))


# ---------------------------------------------------------------------------
# Hot-run benchmarks: reuse VM and isolate the interpreter loop more closely
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_factorial(benchmark, factorial_source):
    program = compile_source(factorial_source, "factorial.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("factorial.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_stress_numeric(benchmark, stress_numeric_source):
    program = compile_source(stress_numeric_source, "stress_numeric.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_numeric.suma", vm.run))


@pytest.mark.benchmark(group="run-hot-ir")
def test_hot_run_ir_stress_numeric(benchmark, stress_numeric_source):
    program = compile_source(
        stress_numeric_source,
        "stress_numeric.suma",
        options=CompileOptions(use_ir=True),
    )
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_numeric.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_stress_strings(benchmark, stress_strings_source):
    program = compile_source(stress_strings_source, "stress_strings_lists.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_strings_lists.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_stress_classes(benchmark, stress_classes_source):
    program = compile_source(stress_classes_source, "stress_classes.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_classes.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_stress_result_pipeline(benchmark, stress_result_pipeline_source):
    program = compile_source(stress_result_pipeline_source, "stress_result_pipeline.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_result_pipeline.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_bench_closures(benchmark, bench_closures_source):
    program = compile_source(bench_closures_source, "bench_closures.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("bench_closures.suma", vm.run))


@pytest.mark.benchmark(group="run-hot")
def test_hot_run_bench_match(benchmark, bench_match_source):
    program = compile_source(bench_match_source, "bench_match.suma")
    vm = VM(program)
    benchmark(lambda: _assert_result("bench_match.suma", vm.run))


@pytest.mark.benchmark(group="run-hot-ir")
def test_hot_run_ir_stress_classes(benchmark, stress_classes_source):
    program = compile_source(
        stress_classes_source,
        "stress_classes.suma",
        options=CompileOptions(use_ir=True),
    )
    vm = VM(program)
    benchmark(lambda: _assert_result("stress_classes.suma", vm.run))


@pytest.mark.benchmark(group="run-hot-ir")
def test_hot_run_ir_bench_closures(benchmark, bench_closures_source):
    program = compile_source(
        bench_closures_source,
        "bench_closures.suma",
        options=CompileOptions(use_ir=True),
    )
    vm = VM(program)
    benchmark(lambda: _assert_result("bench_closures.suma", vm.run))


@pytest.mark.benchmark(group="run-hot-ir")
def test_hot_run_ir_bench_match(benchmark, bench_match_source):
    program = compile_source(
        bench_match_source,
        "bench_match.suma",
        options=CompileOptions(use_ir=True),
    )
    vm = VM(program)
    benchmark(lambda: _assert_result("bench_match.suma", vm.run))
