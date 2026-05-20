from __future__ import annotations

from src.cli import compile_source
from src.runtime.vm.vm import VM


def _run(source: str):
    return VM(compile_source(source, "<stdlib-test>")).run()


def test_core_repeat_and_validation_helpers():
    source = """
import "core"

pub main(): Int {
    score = 0
    if (repeat_str("ha", 0) != "") { return 0 }
    if (repeat_str("ha", 3) != "hahaha") { return 0 }
    require_positive(0) -> {
        Ok = score = 1000
        Err = score = score + 1
    }
    require_positive(-1) -> {
        Ok = score = 1000
        Err = score = score + 1
    }
    require_positive(2) -> {
        Ok = score = score + it
        Err = score = 1000
    }
    if (score != 4) { return 0 }
    return 42
}
"""
    assert _run(source) == 42


def test_math_helpers_cover_zero_and_negative_edges():
    source = """
import "math"

pub main(): Int {
    if (abs_int(-7) != 7) { return 0 }
    if (pow_int(3, 0) != 1) { return 0 }
    if (gcd_int(0, 18) != 18) { return 0 }
    if (lcm_int(0, 18) != 0) { return 0 }
    if (factorial_int(0) != 1) { return 0 }
    if (fib_int(0) != 0) { return 0 }
    if (fib_int(1) != 1) { return 0 }
    return 42
}
"""
    assert _run(source) == 42


def test_list_helpers_cover_empty_and_inclusive_ranges():
    source = """
import "list"

pub main(): Int {
    values: List = List()
    if (list_sum(values) != 0) { return 0 }
    if (list_product(values) != 1) { return 0 }
    if (list_max(values) != 0) { return 0 }
    if (list_min(values) != 0) { return 0 }
    if (list_push_range(values, 3, 3) != 1) { return 0 }
    if (list_push_range(values, 5, 4) != 1) { return 0 }
    if (values[0] != 3) { return 0 }
    return 42
}
"""
    assert _run(source) == 42


def test_json_helpers_escape_and_object_round_trip():
    source = """
import "json"

pub main(): Int {
    if (json_escape("\\n").size != 2) { return 0 }
    if (json_escape("\\\"").size != 2) { return 0 }
    obj: JsonObject = json_object()
    obj.put("name", "Alice")
    obj.put("city", "Paris")
    if (obj.has("name") == false) { return 0 }
    if (obj.get("name").size != 5) { return 0 }
    if (obj.size() != 2) { return 0 }
    if (obj.keys().size != 2) { return 0 }
    return 42
}
"""
    assert _run(source) == 42


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
