import inspect
import json
import struct
import sys
from contextlib import redirect_stdout
from io import StringIO

import pytest

from src.backend.codegen.compiler import Compiler
from src.backend.codegen.serializer import MAGIC, VERSION, _encode_constants, deserialize, serialize
from src.frontend.lexer.token_types import TokenType
from src.frontend.lexer.tokenizer import Tokenizer
from src.frontend.parser.parser import ParseError, Parser
from src.frontend.semantic.analyzer import Analyzer
from src.mid.ir.codegen import CodegenError, ir_to_bytecode
from src.mid.ir.ir import BasicBlock, IRFunction, IRProgram, Label, Return, VirtualReg
from src.mid.ir.lower import lower_to_ir
from src.mid.ir.optimizer import optimize_ir
from src.runtime.vm.vm import VM, SumaCallable, SumaErr


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


def test_parser_reports_multiple_top_level_errors():
    source = """
pub broken(: Int {
    return 1
}

pub also_broken(: Int {
    return 2
}
"""
    try:
        _parse(source)
        assert False, "expected parse failure"
    except ParseError as exc:
        assert str(exc).count("[ParseError]") >= 2


def test_fn_is_plain_identifier_not_keyword_direct_and_ir():
    tokens = Tokenizer.tokenize("fn", file_name="<test>")
    assert tokens[0].type is TokenType.ID
    assert tokens[0].literal == "fn"

    source = """
pub main(): Int {
    fn: Int = 41
    return fn + 1
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_legacy_fn_lambda_syntax_is_rejected():
    source = """
pub main(): Int {
    mapper: Any = fn(x: Int) -> x
    return 0
}
"""
    with pytest.raises(ParseError):
        _parse(source)


def test_multiline_raw_interpolated_strings_and_numeric_separators_direct_and_ir():
    source = '''
pub main(): Int {
    text: Str = """Hello,
World!"""
    path: Str = r"C:\\Users\\name"
    name: Str = "Suma"
    message: Str = "hello {name} {40 + 2}"
    score: Int = 1_000_000 / 25_000 + to_int(3.141_592_653) - 1
    if (text.size != 13) { return 0 }
    if (path != "C:\\\\Users\\\\name") { return 0 }
    if (message != "hello Suma 42") { return 0 }
    return score
}
'''
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_result_propagation_operator_direct_and_ir():
    source = """
pub parse_digit(text: Str): R {
    return parse_int(text)
}

pub add(a: Str, b: Str): R {
    va: Int = parse_digit(a)?
    vb: Int = parse_digit(b)?
    return Ok(va + vb)
}

pub main(): Int {
    result: R = add("40", "2")
    return result -> { Ok = it; Err = 0 }
}
"""
    for use_ir in (False, True):
        assert _run(source, use_ir=use_ir) == 42


def test_result_propagation_returns_err_direct_and_ir():
    source = """
pub parse_digit(text: Str): R {
    return parse_int(text)
}

pub add(a: Str, b: Str): R {
    va: Int = parse_digit(a)?
    vb: Int = parse_digit(b)?
    return Ok(va + vb)
}

pub main(): Int {
    result: R = add("nope", "2")
    return result -> { Ok = 0; Err = 42 }
}
"""
    for use_ir in (False, True):
        assert _run(source, use_ir=use_ir) == 42


def test_result_propagation_preserves_success_type():
    source = """
pub parse_digit(text: Str): R<Int, Str> {
    return parse_int(text)
}

pub add_one(text: Str): R<Int, Str> {
    value: Int = parse_digit(text)?
    return Ok(value + 1)
}

pub main(): Int {
    result: R<Int, Str> = add_one("41")
    return result -> { Ok = it; Err = 0 }
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_result_propagation_success_type_is_checked():
    source = """
pub parse_digit(text: Str): R<Int, Str> {
    return parse_int(text)
}

pub bad(text: Str): R<Int, Str> {
    value: Str = parse_digit(text)?
    return Ok(1)
}

pub main(): Int {
    return 0
}
"""
    errors = _analyze(source)
    assert any(
        "Cannot assign Int to 'value'" in error and "expected Str" in error for error in errors
    )


def test_result_match_preserves_it_type():
    source = """
pub main(): Int {
    result: R<Int, Str> = Ok(42)
    return result -> {
        Ok = it
        Err = 0
    }
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_result_match_it_type_is_checked():
    source = """
pub main(): Int {
    result: R<Int, Str> = Ok(1)
    return result -> {
        Ok = {
            value: Str = it
            0
        }
        Err = 0
    }
}
"""
    errors = _analyze(source)
    assert any(
        "Cannot assign Int to 'value'" in error and "expected Str" in error for error in errors
    )


def test_typed_result_assignment_accepts_matching_ok_and_err():
    source = """
pub main(): Int {
    ok_value: R<Int, Str> = Ok(1)
    err_value: R<Int, Str> = Err("bad")
    return ok_value -> {
        Ok = it + err_value -> { Ok = it; Err = 0 }
        Err = 0
    }
}
"""
    assert _run(source) == 1
    assert _run_ir(source) == 1


def test_typed_result_assignment_rejects_mismatched_payloads():
    errors = _analyze(
        """
pub main(): Int {
    ok_value: R<Int, Str> = Ok("bad")
    err_value: R<Int, Str> = Err(1)
    return 0
}
"""
    )
    assert any("Cannot assign Ok<Str>" in error and "ok_value" in error for error in errors)
    assert any("Cannot assign Err<Int>" in error and "err_value" in error for error in errors)


def test_unwrap_preserves_result_success_type():
    source = """
pub main(): Int {
    ok_value: R<Int, Str> = Ok(42)
    value: Int = unwrap(ok_value)
    return value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_unwrap_or_checks_default_type():
    errors = _analyze(
        """
pub main(): Int {
    result: R<Int, Str> = Err("bad")
    value: Int = unwrap_or(result, "fallback")
    return value
}
"""
    )
    assert any("'unwrap_or' default expects Int, got Str" in error for error in errors)


def test_class_members_default_private():
    source = """
Box {
    value: Int
    init(value: Int) {
        this.value = value
    }
}

pub main(): Int {
    box: Box = Box(42)
    return box.value
}
"""
    errors = _analyze(source)
    assert any("private member 'value'" in error for error in errors)


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
    inc: Function = (n: Int): Int -> { return n + 1 }
    return inc(41)
}
"""
    assert _run_ir(source) == 42


def test_lambda_accepts_single_statement_body_direct_and_ir():
    source = """
pub main(): Int {
    f: Function = (): Int -> return 42
    return f()
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_lambda_closure_captures_outer_value_direct_and_ir():
    source = """
pub main(): Int {
    x: Int = 40
    f: Function = (): Int -> { return x + 2 }
    return f()
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_typed_function_value_checks_args_and_return_direct_and_ir():
    source = """
pub main(): Int {
    inc: Function<Int, Int> = (n: Int): Int -> n + 1
    value: Int = inc(41)
    return value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_typed_function_value_rejects_wrong_argument_type():
    errors = _analyze(
        """
pub main(): Int {
    inc: Function<Int, Int> = (n: Int): Int -> n + 1
    return inc("bad")
}
"""
    )
    assert any("Function value argument expects Int, got Str" in error for error in errors)


def test_typed_function_value_return_type_is_checked():
    errors = _analyze(
        """
pub main(): Int {
    make_text: Function<Int, Str> = (n: Int): Str -> "x"
    value: Int = make_text(1)
    return value
}
"""
    )
    assert any(
        "Cannot assign Str to 'value'" in error and "expected Int" in error for error in errors
    )


def test_assignment_infers_missing_local_type_direct_and_ir():
    source = """
pub main(): Int {
    x = 40
    return x + 2
}
"""
    assert _run(source) == 42
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
    pub get doubled(): Int { return this.value * 2 }
    init(v: Int) { this.value = v }
    pub get(): Int { return this.value }
}

pub main(): Int {
    box: Box = Box(20)
    values: List = List(1, 2, 3)
    values[1] = box.doubled
    ok_value: R = Ok(1)
    err_value: R = Err(5)
    missing: R = Err(0)

    total: Int = box.get() + values[1]
    total += (ok_value ?: 0)
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
    ok_value: R<Int, Str> = Ok(42)
    err_value: R = Err(1)
    return (ok_value ?: 0) + (err_value ?: 40)
}
"""
    assert _run(source) == 82
    assert _run_ir(source) == 82


def test_elvis_unwraps_ok_payload_and_checks_type_direct_and_ir():
    source = """
pub main(): Int {
    ok_value: R<Int, Str> = Ok(7)
    err_value: R<Int, Str> = Err("bad")
    value: Int = ok_value ?: 0
    return value + (err_value ?: 35)
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_null_coalescing_short_circuits_direct_and_ir():
    source = """
pub crash(): Int {
    panic("boom")
    return 0
}

pub main(): Int {
    present: Int = 40
    missing = null
    return (present ?? crash()) + (missing ?? 2)
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_safe_member_access_field_direct_and_ir():
    source = """
Person {
    pub name: Str
    pub age: Int
    init(name: Str, age: Int) {
        this.name = name
        this.age = age
    }
}

pub main(): Int {
    person: Person = Person("ada", 41)
    missing = null
    err: R = Err(1)
    name: Str = person?.name ?? "missing"
    age: Int = missing?.age ?? 1
    err_value: Int = err?.value ?? 1
    return name.size + person?.age - age - err_value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_safe_access_unwraps_ok_receiver_direct_and_ir():
    source = """
Box {
    value: Int
    init(value: Int) { this.value = value }
    pub get(): Int { return this.value }
}

pub main(): Int {
    ok_box: R<Box, Str> = Ok(Box(39))
    ok_text: R<Str, Str> = Ok("abc")
    err_box: R<Box, Str> = Err("missing")
    return ok_box?.get() + ok_text?.size + (err_box?.get() ?? 0)
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_destructure_assignment_from_list_direct_and_ir():
    source = """
pub main(): Int {
    (a, b, c) = List(10, 30, 2)
    return a + b + c
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_logical_operators_short_circuit_direct_and_ir():
    source = """
pub crash(): Bool {
    panic("boom")
    return true
}

pub main(): Int {
    if (false && crash()) { return 0 }
    if (true || crash()) { return 42 }
    return 0
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_ir_safe_call_returns_null_for_err_and_calls_ok_receiver():
    source = """
Box {
    value: Int
    init(v: Int) { this.value = v }
    pub get(): Int { return this.value }
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
    pub value: Int
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


def test_if_expression_assigns_branch_value_direct_and_ir():
    source = """
pub main(): Int {
    value: Int = 7
    label: Str = if (value is Int) { "int" } elif (value is Str) { "str" } else { "other" }
    if (label == "int") { return 42 }
    return 0
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_if_expression_branch_types_must_match():
    source = """
pub main(): Int {
    label: Str = if (true) { "yes" } else { 1 }
    return 0
}
"""
    errors = _analyze(source)
    assert any("if expression branch types must match" in error for error in errors)


def test_match_expression_supports_literal_result_type_direct_and_ir():
    source = """
pub main(): Int {
    value: Int = 7
    kind: Str = value -> {
        6 = "six"
        7 = "seven"
        _ = "other"
    }
    if (kind == "seven") { return 42 }
    return 0
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_while_loop_direct_and_ir():
    source = """
pub main(): Int {
    i: Int = 0
    total: Int = 0
    while (i < 7) {
        total += i
        i += 1
    }
    return total * 2
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_for_in_list_and_ranges_direct_and_ir():
    source = """
pub main(): Int {
    values: List = List(10, 11, 12)
    total: Int = 0
    for item in values {
        total += item
    }
    for i in 0..3 {
        total += i
    }
    for i in 1..=3 {
        total += i
    }
    return total
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_increment_and_decrement_sugar_direct_and_ir():
    source = """
Counter {
    pub value: Int
    init(value: Int) { this.value = value }
}

pub main(): Int {
    i: Int = 39
    i++
    ++i
    i--
    --i

    counter: Counter = Counter(40)
    counter.value++
    ++counter.value
    counter.value--
    --counter.value

    values: List = List(40)
    values[0]++
    ++values[0]
    values[0]--
    --values[0]

    return i + counter.value + values[0] - 77
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_increment_expression_returns_updated_value_direct_and_ir():
    source = """
pub main(): Int {
    i: Int = 40
    return i++ + ++i - 41
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_increment_requires_numeric_assignment_target():
    errors = _analyze("""
pub main(): Int {
    name: Str = "suma"
    name++
    return 0
}
""")
    assert any("'++/--' target must be numeric" in error for error in errors)


def test_increment_rejects_non_assignment_target():
    errors = _analyze("""
pub main(): Int {
    1++
    return 0
}
""")
    assert any("Invalid assignment target" in error for error in errors)


def test_nested_pattern_match_restores_outer_it_direct_and_ir():
    source = """
pub main(): Int {
    value: R = Ok(40)
    return value -> {
        Ok = (Ok(1) -> {
            Ok = it + 1
            Err = 0
        }) + it
        Err = 0
    }
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_finally_runs_when_catch_rethrows_direct_and_ir():
    source = """
value: Int = 0

pub main(): Int {
    try {
        throw 1
    } catch (err) {
        throw 2
    } finally {
        value = 42
    }
    return value
}
"""
    for use_ir in (False, True):
        vm = VM(_program(source, use_ir=use_ir))
        result = vm.run()
        assert isinstance(result, SumaErr)
        assert result.value == 2
        assert vm.globals["value"] == 42


def test_suma_callable_keeps_fixed_signature_above_three_args():
    source = """
pub add5(a: Int, b: Int, c: Int, d: Int, e: Int): Int {
    return a + b + c + d + e
}

pub main(): Int {
    return 0
}
"""
    vm = VM(_program(source, use_ir=False))
    callback = SumaCallable(vm, "add5", "add5").python_callable
    assert len(inspect.signature(callback).parameters) == 5
    assert callback(1, 2, 3, 4, 32) == 42


def test_vm_stack_grows_for_large_argument_lists_direct_and_ir():
    values = ", ".join("1" for _ in range(1200))
    source = f"""
pub main(): Int {{
    values: List = List({values})
    return values.size
}}
"""
    assert _run(source) == 1200
    assert _run_ir(source) == 1200


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
    _value: Int
    pub get value(): Int { return this._value }
    pub set value(v: Int) { this._value = v }
    pub get doubled(): Int { return this.value * 2 }
    init(v: Int) { this.value = v }
}

pub main(): Int {
    c: Counter = Counter(21)
    c.value = c.value + 1
    return c.doubled
}
"""
    assert _run(source) == 44
    assert _run_ir(source) == 44


def test_legacy_dot_getter_syntax_is_rejected():
    source = """
Counter {
    value: Int
    doubled: Int .getter { return this.value * 2 }
}

pub main(): Int {
    return 0
}
"""
    with pytest.raises(ParseError):
        _parse(source)


def test_setter_parameter_type_is_checked():
    errors = _analyze("""
Counter {
    _value: Int
    pub set value(v: Int) { this._value = v }
}

pub main(): Int {
    c: Counter = Counter()
    c.value = "bad"
    return 0
}
""")
    assert any("Cannot assign Str to Int" in err for err in errors)


def test_private_accessor_access_is_rejected():
    errors = _analyze("""
Counter {
    _value: Int
    get value(): Int { return this._value }
    set value(v: Int) { this._value = v }
}

pub main(): Int {
    c: Counter = Counter()
    return c.value
}
""")
    assert any("Cannot access private member 'value' on Counter" in err for err in errors)


def test_get_prefixed_method_is_not_a_property_accessor():
    errors = _analyze("""
Counter {
    pub get_value(): Int { return 42 }
}

pub main(): Int {
    c: Counter = Counter()
    return c.value
}
""")
    assert any("No member 'value' on Counter" in err for err in errors)


def test_serializer_version_round_trip_after_set_index_opcode():
    source = """
pub main(): Int {
    values: List = List(0, 0)
    values[0] = 42
    return values[0]
}
"""
    loaded = deserialize(serialize(_program(source, use_ir=False)))
    assert VERSION == 8
    assert VM(loaded).run() == 42


def test_serializer_accepts_previous_v6_bytecode():
    program = _program(
        """
pub main(): Int {
    return 42
}
""",
        use_ir=False,
    )

    parts = [MAGIC, struct.pack("<I", 6), struct.pack("<I", program.entry)]
    for payload in (
        _encode_constants(program.constants),
        json.dumps(program.classes).encode("utf-8"),
        json.dumps(program.py_imports).encode("utf-8"),
        json.dumps(program.decorators).encode("utf-8"),
    ):
        parts.append(struct.pack("<I", len(payload)))
        parts.append(payload)

    parts.append(struct.pack("<I", len(program.functions)))
    for function in program.functions:
        name_bytes = function.name.encode("utf-8")
        class_name_bytes = (function.class_name or "").encode("utf-8")
        code_data = struct.pack(f"<{len(function.code)}i", *function.code)
        function_parts = [
            struct.pack("<I", len(name_bytes)),
            name_bytes,
            struct.pack("<I", function.arity),
            struct.pack("<I", function.locals_count),
            struct.pack("<B", 1 if function.is_method else 0),
            struct.pack("<I", len(class_name_bytes)),
            class_name_bytes,
            struct.pack("<I", len(function.code)),
            code_data,
            _encode_constants(function.constants),
        ]
        function_payload = b"".join(function_parts)
        parts.append(struct.pack("<I", len(function_payload)))
        parts.append(function_payload)

    loaded = deserialize(b"".join(parts))
    assert VM(loaded).run() == 42


def test_deserializer_rejects_truncated_bytecode():
    program = _program(
        """
pub main(): Int {
    return 42
}
""",
        use_ir=False,
    )

    with pytest.raises(ValueError, match="truncated data"):
        deserialize(serialize(program)[:-1])


def test_deserializer_rejects_unknown_constant_tags():
    bad_constants = struct.pack("<I", 1) + struct.pack("<B", 99)
    parts = [MAGIC, struct.pack("<I", VERSION), struct.pack("<I", 0)]
    parts.append(struct.pack("<I", len(bad_constants)))
    parts.append(bad_constants)
    for payload in (b"{}", b"{}", b"{}", b"{}", b"{}"):
        parts.append(struct.pack("<I", len(payload)))
        parts.append(payload)
    parts.append(struct.pack("<I", 0))

    with pytest.raises(ValueError, match="unknown constant tag 99"):
        deserialize(b"".join(parts))


def test_bool_constants_round_trip_without_int_coercion():
    source = """
pub main(): Int {
    flag: Bool = true
    if (type_of(flag) == "Bool") { return 42 }
    return 0
}
"""
    loaded = deserialize(serialize(_program(source, use_ir=False)))
    assert VM(loaded).run() == 42


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
    pub value: Int
    init(v: Int = 42) { this.value = v }
}

pub main(): Int {
    box: Box = Box()
    return box.value
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


def test_analyzer_rejects_optional_parameter_without_default():
    errors = _analyze("""
pub value(x: Int?): Int {
    return x
}

pub main(): Int {
    return value()
}
""")
    assert any("Optional parameter 'x' must provide a default value" in err for err in errors)


def test_analyzer_rejects_required_parameter_after_optional():
    errors = _analyze("""
pub value(x: Int = 1, y: Int): Int {
    return x + y
}

pub main(): Int {
    return value(41)
}
""")
    assert any(
        "Required parameter 'y' cannot follow an optional parameter" in err for err in errors
    )


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
pub main(): Int {
    if (42 is Int) { return 42 }
    return 0
}
"""
    assert _run(source) == 42
    assert _run_ir(source) == 42


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


def test_analyzer_rejects_private_member_access():
    errors = _analyze("""
Box {
    pri value: Int
    pri secret(): Int { return this.value }
    pub init() { this.value = 42 }
}

pub main(): Int {
    box: Box = Box()
    return box.value + box.secret()
}
""")
    assert any("Cannot access private member 'value' on Box" in err for err in errors)
    assert any("Cannot access private member 'secret' on Box" in err for err in errors)


def test_analyzer_validates_entrypoint_shape():
    errors = _analyze("""
pub main(code: Int): Int {
    return code
}
""")
    assert any("main' must not take parameters" in err for err in errors)


def test_analyzer_validates_entrypoint_return_type():
    errors = _analyze("""
pub main(): Str {
    return "ok"
}
""")
    assert any("main' must return Int" in err for err in errors)


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
