from __future__ import annotations

import main as suma_main
from src.backend.codegen.serializer import deserialize, serialize
from src.runtime.vm.vm import VM


def _compile(source: str, use_ir: bool = False):
    old_use_ir = suma_main._use_ir
    try:
        suma_main._use_ir = use_ir
        return suma_main.compile_source(source, "<python-import-test>")
    finally:
        suma_main._use_ir = old_use_ir


def _run(source: str, use_ir: bool = False):
    return VM(_compile(source, use_ir=use_ir)).run()


def test_python_math_import_direct():
    source = """
import "py:math"

pub main(): Int {
    return to_int(math.sqrt(1764.0))
}
"""
    program = _compile(source)
    assert program.py_imports == {"math": "math"}
    assert VM(program).run() == 42


def test_python_json_bridge_preserves_list_order():
    source = """
import "py:json"

pub main(): Str {
    return json.dumps(List(1, 2, 3))
}
"""
    assert _run(source) == "[1, 2, 3]"


def test_python_dict_method_bridge():
    source = """
import "py:json"

pub main(): Int {
    data: PyObject = json.loads("{\\\"answer\\\": 42}")
    return data.get("answer")
}
"""
    assert _run(source) == 42


def test_python_import_ir_pipeline():
    source = """
import "py:math"

pub main(): Int {
    return to_int(math.sqrt(1764.0))
}
"""
    assert _run(source, use_ir=True) == 42


def test_python_imports_survive_serialization():
    source = """
import "py:math"

pub main(): Int {
    return to_int(math.sqrt(1764.0))
}
"""
    program = _compile(source)
    loaded = deserialize(serialize(program))
    assert loaded.py_imports == {"math": "math"}
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
