import sys
from contextlib import redirect_stdout
from io import StringIO

import pytest

from src.backend.codegen.compiler import Compiler
from src.backend.codegen.serializer import VERSION, deserialize, serialize
from src.frontend.lexer.tokenizer import Tokenizer
from src.frontend.parser.parser import Parser
from src.frontend.semantic.analyzer import Analyzer
from src.mid.ir.codegen import CodegenError, ir_to_bytecode
from src.mid.ir.ir import BasicBlock, IRFunction, IRProgram, Label, Return, VirtualReg
from src.mid.ir.lower import lower_to_ir
from src.mid.ir.optimizer import optimize_ir
from src.runtime.vm.vm import VM


def _parse(source: str):
    return Parser.parse(Tokenizer.tokenize(source, file_name="<test>"))


def _analyze(source: str) -> list[str]:
    return Analyzer().analyze(_parse(source))


def _program(source: str, use_ir: bool):
    ast = _parse(source)
    errors = Analyzer().analyze(ast)
    assert errors == []
    if use_ir:
        return ir_to_bytecode(optimize_ir(lower_to_ir(ast)))
    return Compiler().compile(ast)


def _run(source: str, use_ir: bool = False):
    return VM(_program(source, use_ir=use_ir)).run()


def _run_ir(source: str):
    return _run(source, use_ir=True)


def _run_with_stdout(source: str, use_ir: bool = False):
    stream = StringIO()
    with redirect_stdout(stream):
        result = _run(source, use_ir=use_ir)
    return result, stream.getvalue()


def test_ir_recursive_call_returns_value():
    source = """
pub fib(n: Int): Int {
    if (n <= 1) {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

pub main(): Int {
    return fib(10)
}
"""
    assert _run_ir(source) == 55


def test_ir_bytecode_optimizer_preserves_loop_entry_target():
    source = """
pub main(): Int {
    i: Int = 0
    loop {
        if (i > 2) { break }
        i += 1
    }
    return i
}
"""
    program = _program(source, use_ir=True)
    from src.backend.codegen.optimizer import optimize

    assert VM(optimize(program)).run() == 3


def test_ir_lambda_returns_value():
    source = """
pub main(): Int {
    inc: Function = fn(n: Int): Int { return n + 1 }
    return inc(41)
}
"""
    assert _run_ir(source) == 42


def test_ir_nested_side_effect_calls_match_direct_output():
    source = """
pub fact(n: Int): Int {
    if (n <= 1) { return 1 }
    return n * fact(n - 1)
}

pub main(): Int {
    i: Int = 1
    loop {
        if (i > 3) { break }
        print(to_str(i) + "! = " + to_str(fact(i)))
        i += 1
    }
    return fact(5)
}
"""
    expected = (120, "1! = 1\n2! = 2\n3! = 6\n")
    assert _run_with_stdout(source) == expected
    assert _run_with_stdout(source, use_ir=True) == expected


def test_ir_stack_contract_with_objects_results_and_indexing():
    source = """
Box {
    value: Int
    doubled: Int .getter { return this.value * 2 }
    init(v: Int) { this.value = v }
    get(): Int { return this.value }
}

pub main(): Int {
    box: Box = Box(20)
    values: List = List(1, 2, 3)
    values[1] = box.doubled
    ok_value: R = Ok(1)
    err_value: R = Err(5)
    missing: R = Err(0)

    total: Int = box.get() + values[1]
    total += (ok_value ?: 0).value
    total += (err_value ?: 1)
    total += ok_value -> { Ok = it; Err = 0 }
    if (missing?.get() == null) {
        total += box?.get()
    }
    return total
}
"""
    assert _run(source) == 83
    assert _run_ir(source) == 83


def test_global_assignment_direct_and_ir():
    source = """
value: Int = 0

pub main(): Int {
    value = 41
    value += 1
    return value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_ir_codegen_rejects_undefined_virtual_register():
    missing = VirtualReg("missing")
    entry = BasicBlock(Label("entry"), [Return(missing)])
    func = IRFunction(name="main", params=[], arity=0, entry=entry, blocks=[entry])

    with pytest.raises(CodegenError, match="before definition"):
        ir_to_bytecode(IRProgram(functions=[func], entry=0))


def test_ir_elvis_uses_right_only_for_err():
    source = """
pub main(): Int {
    ok_value: R = Ok(42)
    err_value: R = Err(1)
    return (ok_value ?: 0).value + (err_value ?: 40)
}
"""
    assert _run_ir(source) == 82


def test_ir_safe_call_returns_null_for_err_and_calls_ok_receiver():
    source = """
Box {
    value: Int
    init(v: Int) { this.value = v }
    get(): Int { return this.value }
}

pub main(): Int {
    box: Box = Box(42)
    missing: R = Err(1)
    if (missing?.get() == null) {
        return box?.get()
    }
    return 0
}
"""
    assert _run_ir(source) == 42


def test_ir_pattern_match_returns_arm_expression():
    source = """
pub main(): Int {
    value: R = Ok(40)
    return value -> {
        Ok = it + 2
        Err = 0
    }
}
"""
    assert _run_ir(source) == 42


def test_pattern_match_supports_type_and_literal_arms_direct_and_ir():
    source = """
Box {
    value: Int
    init(v: Int) { this.value = v }
}

pub main(): Int {
    box: Box = Box(40)
    text: Str = "yes"
    number: Int = 7

    total: Int = box -> {
        is Box = it.value
        _ = 0
    }
    total += text -> {
        "no" = 1
        "yes" = 2
        _ = 0
    }
    total += number -> {
        6 = 10
        7 = 0
        _ = 100
    }
    flag: Int = 0
    box -> {
        is Box = { flag = it.value }
        _ = { flag = 1 }
    }
    return total + flag - 40
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_index_assignment_direct_and_ir():
    source = """
pub main(): Int {
    values: List = List(1, 2, 3)
    values[1] = 40
    values[-1] = 2
    return values[1] + values[2]
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_ir_getter_and_setter_are_lowered():
    source = """
Counter {
    value: Int
    doubled: Int .getter { return this.value * 2 }
    init(v: Int) { this.value = v }
}

pub main(): Int {
    c: Counter = Counter(21)
    return c.doubled
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_serializer_version_round_trip_after_set_index_opcode():
    source = """
pub main(): Int {
    values: List = List(0, 0)
    values[0] = 42
    return values[0]
}
"""
    loaded = deserialize(serialize(_program(source, use_ir=False)))
    assert VERSION == 6
    assert VM(loaded).run() == 42


def test_bool_constants_round_trip_without_int_coercion():
    source = """
pub main(): Bool {
    return true
}
"""
    loaded = deserialize(serialize(_program(source, use_ir=False)))
    assert VM(loaded).run() is True


def test_default_arguments_direct_and_ir():
    source = """
pub value(x: Int = 42): Int {
    return x
}

pub main(): Int {
    return value()
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_constructor_default_arguments_direct_and_ir():
    source = """
Box {
    value: Int
    init(v: Int = 42) { this.value = v }
}

pub main(): Int {
    box: Box = Box()
    return box.value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_try_catch_skips_catch_without_throw_direct_and_ir():
    source = """
pub main(): Int {
    x: Int = 0
    try { x = 42 } catch (e) { x = 0 }
    return x
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_throw_jumps_to_catch_direct_and_ir():
    source = """
pub main(): Int {
    try { throw 42 } catch (e) { return e }
    return 0
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_is_operator_direct_and_ir():
    source = """
pub main(): Bool {
    return 42 is Int
}
"""
    assert _run(source) is True
    assert _run_ir(source) is True


def test_top_level_global_initializers_direct_and_ir():
    source = """
answer: Int = 42

pub main(): Int {
    return answer
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_assignment_to_unknown_local_infers_type_direct_and_ir():
    source = """
pub main(): Int {
    v = 1
    return v
}
"""
    assert _analyze(source) == []
    assert _run(source) == 1
    assert _run_ir(source) == 1


def test_inferred_assignment_remains_static():
    errors = _analyze("""
pub main(): Int {
    v = 1
    v = "one"
    return 0
}
""")
    assert any("Cannot assign Str to Int" in err for err in errors)


def test_any_initializer_infers_static_type():
    errors = _analyze("""
pub main(): Int {
    v: Any = 1
    v = "one"
    return 0
}
""")
    assert any("Cannot assign Str to Int" in err for err in errors)


def test_any_without_initializer_is_not_dynamic():
    errors = _analyze("""
pub main(): Int {
    v: Any
    return v + 1
}
""")
    assert any("left operand must be numeric, got Any" in err for err in errors)


def test_any_parameter_is_polymorphic_but_not_dynamic():
    errors = _analyze("""
pub accepts(value: Any): Int {
    return value + 1
}

pub main(): Int {
    return accepts(41)
}
""")
    assert any("left operand must be numeric, got Any" in err for err in errors)


def test_any_parameter_accepts_multiple_static_types():
    source = """
pub classify(value: Any): Int {
    if (value is Int) { return 1 }
    if (value is Str) { return 2 }
    return 0
}

pub main(): Int {
    return classify(1) + classify("x")
}
"""
    assert _analyze(source) == []


def test_analyzer_rejects_bad_assignment_type():
    errors = _analyze("""
pub main(): Int {
    x: Int = "not an int"
    return 0
}
""")
    assert any("Cannot assign Str to 'x'" in err for err in errors)


def test_analyzer_rejects_bad_argument_type():
    errors = _analyze("""
pub add(a: Int, b: Int): Int {
    return a + b
}

pub main(): Int {
    return add(1, "two")
}
""")
    assert any("Argument 'b' expects Int, got Str" in err for err in errors)


def test_analyzer_rejects_bad_return_type():
    errors = _analyze("""
pub main(): Int {
    return "zero"
}
""")
    assert any("Function 'main' returns Str" in err for err in errors)


def test_analyzer_rejects_non_bool_condition():
    errors = _analyze("""
pub main(): Int {
    if (1) {
        return 1
    }
    return 0
}
""")
    assert any("if condition must be Bool" in err for err in errors)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {passed + failed} tests")
    sys.exit(1 if failed else 0)
