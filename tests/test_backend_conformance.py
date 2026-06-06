from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass

import pytest

from suma_lang.api import CompileOptions, CompileSourceError, compile_source
from suma_lang.runtime.vm.vm import VM

PIPELINES = [
    ("direct-opt", CompileOptions(use_ir=False, optimize=True)),
    ("ir-opt", CompileOptions(use_ir=True, optimize=True)),
    ("direct-no-opt", CompileOptions(use_ir=False, optimize=False)),
    ("ir-no-opt", CompileOptions(use_ir=True, optimize=False)),
]


@dataclass(frozen=True)
class RuntimeCase:
    name: str
    source: str
    expected_result: object = 42
    expected_stdout: str = ""


def _run_source(source: str, options: CompileOptions) -> tuple[object, str]:
    program = compile_source(source, "<backend-conformance>", options=options)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = VM(program).run()
    return result, stdout.getvalue()


def _diagnostics(source: str, options: CompileOptions) -> list[str]:
    try:
        compile_source(source, "<backend-conformance>", options=options)
    except CompileSourceError as exc:
        return [diagnostic.message for diagnostic in exc.diagnostics]
    raise AssertionError("expected compile error")


RUNTIME_CASES = [
    RuntimeCase(
        name="finally_abrupt_completion",
        source="""
value: Int = 0

pub from_try_return(): Int {
    try {
        return 5
    } finally {
        @value += 10
    }
}

pub from_catch_return(): Int {
    try {
        throw 6
    } catch (err) {
        return err
    } finally {
        @value += 11
    }
}

pub from_break_continue(): Int {
    i = 0
    loop {
        try {
            break
        } finally {
            @value += 12
        }
    }
    while i < 1 {
        @i += 1
        try {
            continue
        } finally {
            @value += 13
        }
        @value = 0
    }
    return i
}

pub main(): Int {
    return from_try_return() + from_catch_return() + from_break_continue() + value
}
""",
        expected_result=58,
    ),
    RuntimeCase(
        name="nested_finally_rethrows_to_outer_catch",
        source="""
log: Int = 0

pub main(): Int {
    try {
        try {
            try {
                throw 5
            } finally {
                @log += 10
            }
        } finally {
            @log += 20
        }
    } catch (err) {
        @log += err
    }
    return log + 7
}
""",
    ),
    RuntimeCase(
        name="finally_return_overrides_pending_throw",
        source="""
pub main(): Int {
    try {
        throw 1
    } finally {
        return 42
    }
    return 0
}
""",
    ),
    RuntimeCase(
        name="finally_throw_overrides_pending_return",
        source="""
pub main(): Int {
    try {
        try {
            return 1
        } finally {
            throw 15
        }
    } catch (err) {
        return err + 27
    }
    return 0
}
""",
    ),
    RuntimeCase(
        name="finally_break_overrides_pending_continue",
        source="""
pub main(): Int {
    value = 0
    while value < 1 {
        @value += 1
        try {
            continue
        } finally {
            break
        }
        return 0
    }
    return value + 41
}
""",
    ),
    RuntimeCase(
        name="finally_continue_overrides_pending_break",
        source="""
pub main(): Int {
    value = 0
    while value < 1 {
        @value += 1
        try {
            break
        } finally {
            continue
        }
        return 0
    }
    return value + 41
}
""",
    ),
    RuntimeCase(
        name="result_nullable_and_match",
        source="""
pub parse_add(left: Str, right: Str): R<Int, Str> {
    a: Int = parse_int(left)?
    b: Int = parse_int(right)?
    return Ok(a + b)
}

pub main(): Int {
    value: Int? = match parse_add("40", "2") {
        Ok => it
        Err => null
    }
    return value ?? 0
}
""",
    ),
    RuntimeCase(
        name="enum_match_literals_and_types",
        source="""
enum Packet {
    Data(Int),
    Text(Str),
    Empty
}

Box {
    pub value: Int
    init(v: Int) { this.value = v }
}

pub main(): Int {
    packet: Packet = Packet.Data(40)
    first: Int = match packet {
        Packet.Data => it
        Packet.Text => 0
        Packet.Empty => 0
    }

    box: Box = Box(first)
    second: Int = match box {
        is Box => it.value
        _ => 0
    }
    third: Int = match "two" {
        "one" => 1
        "two" => 2
        _ => 0
    }
    return second + third
}
""",
    ),
    RuntimeCase(
        name="tuple_list_destructure_and_index_assignment",
        source="""
pub pair(): (Int, Str) {
    return (40, "two")
}

pub main(): Int {
    (left, right) = pair()
    values: List = List(1, 2, 3)
    values[0] = left
    values[-1] = right.size
    a: Int = 0;
    b: Str = "";
    again: (Int, Str) = pair();
    (a, b) = again
    return values[0] + values[2] + a - 41
}
""",
    ),
    RuntimeCase(
        name="nested_constructors_return_their_own_objects",
        source="""
Box {
    pub value: Int
    init(value: Int) { this.value = value }
}

Pair {
    pub left: Box
    pub right: Box

    init() {
        this.left = Box(20)
        this.right = Box(22)
    }
}

pub main(): Int {
    pair: Pair = Pair()
    return pair.left.value + pair.right.value
}
""",
    ),
    RuntimeCase(
        name="to_int_bool_returns_int",
        source="""
pub main(): Int {
    one = to_int(true)
    if type_of(one) != "Int" { return 0 }
    return one + to_int(false) + 41
}
""",
    ),
    RuntimeCase(
        name="suma_decorators_and_closures",
        source="""
pub plus_ten(func: Function<Int>): Function<Int> {
    return (): Int -> {
        return func() + 10
    }
}

@plus_ten
pub answer(): Int {
    base = 32
    read = (): Int -> {
        return base
    }
    return read()
}

pub main(): Int {
    return answer()
}
""",
    ),
    RuntimeCase(
        name="stdout_side_effect_order",
        source="""
pub emit(label: Str, value: Int): Int {
    print(label)
    return value
}

pub main(): Int {
    total = emit("a", 20) + emit("b", 22)
    return total
}
""",
        expected_stdout="a\nb\n",
    ),
]


@pytest.mark.parametrize("case", RUNTIME_CASES, ids=lambda case: case.name)
def test_direct_and_ir_runtime_semantics_agree(case: RuntimeCase) -> None:
    runs = {label: _run_source(case.source, options) for label, options in PIPELINES}
    baseline_label, (baseline_result, baseline_stdout) = next(iter(runs.items()))

    assert baseline_result == case.expected_result
    assert baseline_stdout == case.expected_stdout
    for label, (result, stdout) in runs.items():
        assert result == baseline_result, (
            f"{case.name}: {label} returned {result!r}, "
            f"but {baseline_label} returned {baseline_result!r}"
        )
        assert stdout == baseline_stdout, (
            f"{case.name}: {label} stdout diverges from {baseline_label}:\n"
            f"--- {baseline_label} ---\n{baseline_stdout}"
            f"--- {label} ---\n{stdout}"
        )


def test_direct_and_ir_compile_time_invariants_agree() -> None:
    source = """
pub main(): Int {
    pair: (Int, Int) = (1, 2)
    pair[0] = 40
    text = "ab"
    text[0] = "z"
    span = 0..2
    span[0] = 1
    return 0
}
"""
    diagnostics_by_pipeline = {label: _diagnostics(source, options) for label, options in PIPELINES}
    baseline_label, baseline = next(iter(diagnostics_by_pipeline.items()))

    assert any("Cannot assign through index on Tuple<Int,Int>" in item for item in baseline)
    assert any("Cannot assign through index on Str" in item for item in baseline)
    assert any("Cannot assign through index on Range" in item for item in baseline)
    for label, diagnostics in diagnostics_by_pipeline.items():
        assert diagnostics == baseline, (
            f"{label} diagnostics diverge from {baseline_label}:\n"
            f"--- {baseline_label} ---\n{baseline}\n"
            f"--- {label} ---\n{diagnostics}"
        )
