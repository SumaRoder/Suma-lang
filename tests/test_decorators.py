from __future__ import annotations

import os

import pytest

from suma_lang.backend.codegen.serializer import deserialize, serialize
from suma_lang.cli import CompileOptions, CompileSourceError, compile_source
from suma_lang.runtime.vm.vm import VM


def _compile(source: str, use_ir: bool = False):
    return compile_source(
        source,
        "<decorator-test>",
        options=CompileOptions(use_ir=use_ir),
    )


def _run(source: str, use_ir: bool = False):
    return VM(_compile(source, use_ir=use_ir)).run()


def _compile_errors(source: str) -> list[str]:
    try:
        _compile(source)
    except CompileSourceError as exc:
        return [diagnostic.message for diagnostic in exc.diagnostics]
    raise AssertionError("expected compile error")


@pytest.fixture
def allow_decorator_helpers(monkeypatch):
    existing = os.environ.get("SUMA_PY_IMPORTS", "")
    allowed = "examples.decorator_helpers"
    if existing:
        allowed = f"{existing},{allowed}"
    monkeypatch.setenv("SUMA_PY_IMPORTS", allowed)


def test_python_decorator_replaces_function(allow_decorator_helpers):
    source = """
import "py:examples.decorator_helpers"

@decorator_helpers.plus(10)
pub answer(): Int {
    return 32
}

pub main(): Int {
    return answer()
}
"""
    assert _run(source) == 42


def test_decorator_chain_order(allow_decorator_helpers):
    source = """
import "py:examples.decorator_helpers"

@decorator_helpers.plus(1)
@decorator_helpers.plus(2)
pub value(): Int {
    return 39
}

pub main(): Int {
    return value()
}
"""
    assert _run(source) == 42


def test_decorator_ir_pipeline(allow_decorator_helpers):
    source = """
import "py:examples.decorator_helpers"

@decorator_helpers.plus(10)
pub answer(): Int {
    return 32
}

pub main(): Int {
    return answer()
}
"""
    assert _run(source, use_ir=True) == 42


def test_decorators_survive_serialization(allow_decorator_helpers):
    source = """
import "py:examples.decorator_helpers"

@decorator_helpers.plus(10)
pub answer(): Int {
    return 32
}

pub main(): Int {
    return answer()
}
"""
    program = _compile(source)
    loaded = deserialize(serialize(program))
    assert loaded.decorators
    assert VM(loaded).run() == 42


def test_suma_decorator_replaces_function_direct_and_ir():
    source = """
pub plus_ten(func: Function): Function {
    return () -> {
        return func() + 10
    }
}

@plus_ten
pub answer(): Int {
    return 32
}

pub main(): Int {
    return answer()
}
"""
    assert _run(source) == 42
    assert _run(source, use_ir=True) == 42


def test_suma_decorator_on_class_and_method():
    source = """
pub wrap_ctor(ctor: Function): Function {
    return (value: Int) -> {
        box: Box = ctor(value)
        box.value += 1
        return box
    }
}

pub add_five(func: Function): Function {
    return () -> {
        return func() + 5
    }
}

@wrap_ctor
Box {
    pub value: Int
    init(value: Int) {
        this.value = value
    }

    @add_five
    pub value_plus_five(): Int {
        return this.value
    }
}

pub main(): Int {
    box: Box = Box(36)
    return box.value_plus_five()
}
"""
    assert _run(source) == 42
    assert _run(source, use_ir=True) == 42
    loaded = deserialize(serialize(_compile(source)))
    assert loaded.decorators
    assert loaded.method_decorators
    assert VM(loaded).run() == 42


def test_typed_suma_decorators_direct_and_ir():
    source = """
pub plus_ten(func: Function<Int>): Function<Int> {
    return (): Int -> {
        return func() + 10
    }
}

pub wrap_ctor(ctor: Function<Int, Box>): Function<Int, Box> {
    return (value: Int): Box -> {
        box: Box = ctor(value)
        box.value += 1
        return box
    }
}

@plus_ten
pub answer(): Int {
    return 21
}

@wrap_ctor
Box {
    pub value: Int
    init(value: Int) {
        this.value = value
    }

    @plus_ten
    pub value_plus_ten(): Int {
        return this.value
    }
}

pub main(): Int {
    box: Box = Box(answer())
    return box.value_plus_ten()
}
"""
    assert _run(source) == 42
    assert _run(source, use_ir=True) == 42


def test_typed_decorator_rejects_incompatible_target_signature():
    errors = _compile_errors("""
pub needs_int_arg(func: Function<Int, Int>): Function<Int, Int> {
    return (value: Int): Int -> {
        return func(value)
    }
}

@needs_int_arg
pub answer(): Int {
    return 42
}

pub main(): Int {
    return answer()
}
""")
    assert any(
        "Decorator expects Function<Int,Int>, got Function<Int>" in error for error in errors
    )


def test_typed_decorator_rejects_non_function_replacement():
    errors = _compile_errors("""
pub bad(func: Function<Int>): Int {
    return 0
}

@bad
pub answer(): Int {
    return 42
}

pub main(): Int {
    return answer()
}
""")
    assert any("Decorator must return Function, got Int" in error for error in errors)


def test_typed_decorator_rejects_incompatible_replacement_signature():
    errors = _compile_errors("""
pub replace_with_text(func: Function<Int>): Function<Str> {
    return (): Str -> {
        return "bad"
    }
}

@replace_with_text
pub answer(): Int {
    return 42
}

pub main(): Int {
    return answer()
}
""")
    assert any(
        "Decorator chain returns Function<Str>, expected Function<Int>" in error for error in errors
    )


def test_typed_decorators_check_class_and_method_targets():
    errors = _compile_errors("""
pub wrap_str_ctor(ctor: Function<Str, Box>): Function<Str, Box> {
    return (value: Str): Box -> {
        return ctor(value)
    }
}

pub wrap_text_method(func: Function<Str>): Function<Str> {
    return (): Str -> {
        return func()
    }
}

@wrap_str_ctor
Box {
    pub value: Int
    init(value: Int) {
        this.value = value
    }

    @wrap_text_method
    pub value_int(): Int {
        return this.value
    }
}

pub main(): Int {
    box: Box = Box(42)
    return box.value_int()
}
""")
    assert any(
        "Decorator expects Function<Str,Box>, got Function<Int,Box>" in error for error in errors
    )
    assert any("Decorator expects Function<Str>, got Function<Int>" in error for error in errors)


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
    raise SystemExit(1 if failed else 0)
