from __future__ import annotations

import main as suma_main
from src.backend.codegen.serializer import deserialize, serialize
from src.runtime.vm.vm import VM


def _compile(source: str, use_ir: bool = False):
    old_use_ir = suma_main._use_ir
    try:
        suma_main._use_ir = use_ir
        return suma_main.compile_source(source, "<decorator-test>")
    finally:
        suma_main._use_ir = old_use_ir


def _run(source: str, use_ir: bool = False):
    return VM(_compile(source, use_ir=use_ir)).run()


def test_python_decorator_replaces_function():
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


def test_decorator_chain_order():
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


def test_decorator_ir_pipeline():
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


def test_decorators_survive_serialization():
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
