import pytest

from suma_lang.backend.codegen.compiler import Compiler
from suma_lang.backend.codegen.serializer import deserialize, serialize
from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser.parser import Parser
from suma_lang.frontend.semantic.analyzer import Analyzer
from suma_lang.mid.ir.codegen import ir_to_bytecode
from suma_lang.mid.ir.lower import lower_to_ir
from suma_lang.runtime.vm.vm import VM


def _parse(source: str):
    return Parser.parse(Tokenizer.tokenize(source, file_name="<test>"))


def _analyze(source: str) -> list[str]:
    return Analyzer().analyze(_parse(source))


def _program(source: str, use_ir: bool):
    ast = _parse(source)
    errors = Analyzer().analyze(ast)
    assert errors == []
    if use_ir:
        return ir_to_bytecode(lower_to_ir(ast))
    return Compiler().compile(ast)


def _run(source: str, use_ir: bool = False):
    return VM(_program(source, use_ir=use_ir)).run()


@pytest.mark.parametrize("use_ir", [False, True])
def test_generic_function_and_class_type_inference(use_ir: bool):
    source = """
pub id<T>(value: T): T {
    return value
}

Box<T> {
    pub value: T

    init(value: T) {
        this.value = value
    }

    pub get(): T {
        return this.value
    }
}

pub main(): Int {
    box: Box<Int> = Box(id(40))
    word: Str = id("xy")
    return box.get() + word.size
}
"""
    assert _run(source, use_ir=use_ir) == 42


@pytest.mark.parametrize("use_ir", [False, True])
def test_java_style_top_level_overload_by_parameter_type(use_ir: bool):
    source = """
pub score(value: Int): Int {
    return value + 1
}

pub score(value: Str): Int {
    return value.size
}

pub main(): Int {
    return score(38) + score("abc")
}
"""
    assert _run(source, use_ir=use_ir) == 42


@pytest.mark.parametrize("use_ir", [False, True])
def test_enum_argument_runtime_overload_dispatch(use_ir: bool):
    source = """
enum Packet {
    Data(Int),
    Empty
}

pub score(value: Packet): Int {
    return match value {
        Packet.Data => it + 1
        Packet.Empty => 0
    }
}

pub score(value: Int): Int {
    return value
}

pub main(): Int {
    return score(Packet.Data(41))
}
"""
    assert _run(source, use_ir=use_ir) == 42


@pytest.mark.parametrize("use_ir", [False, True])
def test_method_overload_by_parameter_type(use_ir: bool):
    source = """
Scorer {
    pub score(value: Int): Int {
        return value + 2
    }

    pub score(value: Str): Int {
        return value.size
    }
}

pub main(): Int {
    scorer: Scorer = Scorer()
    return scorer.score(37) + scorer.score("abc")
}
"""
    assert _run(source, use_ir=use_ir) == 42


@pytest.mark.parametrize("use_ir", [False, True])
def test_operator_overload_binary_and_unary(use_ir: bool):
    source = """
Vec {
    pub x: Int

    init(x: Int) {
        this.x = x
    }

    pub op_add(other: Vec): Vec {
        return Vec(this.x + other.x)
    }

    pub op_neg(): Vec {
        return Vec(0 - this.x)
    }
}

pub main(): Int {
    sum: Vec = Vec(50) + -Vec(8)
    return sum.x
}
"""
    assert _run(source, use_ir=use_ir) == 42


def test_hex_literals_still_work_and_digit_leading_identifiers_are_rejected():
    hex_source = """
pub main(): Int {
    return 0x28 + 2
}
"""
    assert _run(hex_source) == 42

    for source in ("123abc", "2cool", "42foo", "0x", "0x1g"):
        with pytest.raises(SyntaxError, match="Invalid numeric literal suffix"):
            Tokenizer.tokenize(source, file_name="<test>")

    with pytest.raises(SyntaxError, match="Invalid numeric literal suffix"):
        _parse("""
pub main(): Int {
    return 2cool()
}
""")


def test_generic_overloads_with_same_erasure_are_rejected():
    source = """
pub head(values: List<Int>): Int {
    return 1
}

pub head(values: List<Str>): Int {
    return 2
}

pub main(): Int {
    return 0
}
"""
    errors = _analyze(source)
    assert any("Duplicate overload" in error and "head" in error for error in errors)


def test_overloaded_defaults_are_rejected_to_avoid_ambiguous_calls():
    source = """
pub f(value: Int = 1): Int {
    return value
}

pub f(value: Str): Int {
    return value.size
}

pub main(): Int {
    return 0
}
"""
    errors = _analyze(source)
    assert any("default parameters" in error and "f" in error for error in errors)


def test_overload_metadata_survives_serialization():
    source = """
pub score(value: Int): Int {
    return value + 1
}

pub score(value: Str): Int {
    return value.size
}

pub main(): Int {
    return score(38) + score("abc")
}
"""
    program = _program(source, use_ir=False)
    loaded = deserialize(serialize(program))
    assert loaded.overloads
    assert VM(loaded).run() == 42


@pytest.mark.parametrize("use_ir", [False, True])
def test_generic_method_overload_runtime_dispatch(use_ir: bool):
    source = """
Box<T> {
    pub value: T

    init(value: T) {
        this.value = value
    }

    pub get(): T {
        return this.value
    }

    pub get(value: Int): Int {
        return value + 1
    }
}

pub main(): Int {
    box: Box<Int> = Box(40)
    return box.get() + box.get(1)
}
"""
    assert _run(source, use_ir=use_ir) == 42


def test_generic_method_rejects_return_type_erasure_soundness_bug():
    source = """
Box<T> {
    pub value: T

    init(value: T) {
        this.value = value
    }

    pub get_bad(): Int {
        return this.value
    }
}

pub main(): Int {
    box: Box<Str> = Box("x")
    return box.value.size
}
"""
    errors = _analyze(source)
    assert any(
        "Function 'get_bad' returns T" in error and "expected Int" in error for error in errors
    )


def test_generic_method_rejects_bad_assignment_to_generic_field():
    source = """
Box<T> {
    pub value: T

    init(value: T) {
        this.value = value
    }

    pub overwrite_bad(): Int {
        this.value = 1
        return 0
    }
}

pub main(): Int {
    box: Box<Str> = Box("x")
    return box.value.size
}
"""
    errors = _analyze(source)
    assert any("Cannot assign Int to T" in error and "expected T" in error for error in errors)


def test_overloaded_function_with_decorator_is_rejected():
    source = """
pub trace(func: Function): Function {
    return () -> {
        return func() + 1
    }
}

@trace
pub pick(value: Int): Int {
    return value
}

pub pick(value: Str): Int {
    return value.size
}

pub main(): Int {
    return 0
}
"""
    errors = _analyze(source)
    assert any("cannot use decorators" in error and "pick" in error for error in errors)


def test_ambiguous_generic_overload_is_rejected():
    source = """
pub choose<T>(value: T): Int {
    return 1
}

pub choose<T>(value: T): Int {
    return 2
}

pub main(): Int {
    return choose(42)
}
"""
    errors = _analyze(source)
    assert any("Duplicate overload" in error and "choose" in error for error in errors)
