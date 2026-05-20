from __future__ import annotations

import tempfile
from pathlib import Path

from main import CompileSourceError, compile_source
from src.runtime.vm.vm import VM


def _run(source: str, filename: str, import_paths: list[str] | None = None):
    program = compile_source(source, filename, import_paths=import_paths)
    return VM(program).run()


def test_relative_import():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        lib_dir = root / "lib"
        lib_dir.mkdir()
        (lib_dir / "math_utils.suma").write_text("""
pub add2(n: Int): Int {
    return n + 2
}
""")
        source = """
import "./lib/math_utils.suma"

pub main(): Int {
    return add2(40)
}
"""
        assert _run(source, str(root / "main.suma")) == 42


def test_absolute_import():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        util = root / "util.suma"
        util.write_text("""
pub mul3(n: Int): Int {
    return n * 3
}
""")
        source = f"""
import \"{util.as_posix()}\"\n

pub main(): Int {{
    return mul3(14)
}}
"""
        assert _run(source, str(root / "main.suma")) == 42


def test_custom_import_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        custom_dir = root / "custom"
        custom_dir.mkdir()
        (custom_dir / "tools.suma").write_text("""
pub join_score(a: Int, b: Int): Int {
    return a * 10 + b
}
""")
        source = """
import "tools"

pub main(): Int {
    return join_score(4, 2)
}
"""
        assert _run(source, str(root / "main.suma"), import_paths=[str(custom_dir)]) == 42


def test_stdlib_imports():
    path = Path("examples/import_stdlib.suma")
    source = path.read_text()
    assert _run(source, str(path)) == 201


def test_duplicate_import_is_deduped():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        lib_dir = root / "lib"
        lib_dir.mkdir()
        (lib_dir / "calc.suma").write_text("""
pub answer(): Int {
    return 42
}
""")
        source = """
import "./lib/calc.suma"
import "./lib/calc.suma"

pub main(): Int {
    return answer()
}
        """
        assert _run(source, str(root / "main.suma")) == 42


def test_missing_import_reports_candidates():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source = """
import "missing_mod"

pub main(): Int {
    return 42
}
"""
        try:
            _run(source, str(root / "main.suma"))
            assert False, "expected import failure"
        except CompileSourceError as exc:
            assert "Cannot resolve import 'missing_mod'" in str(exc)


def test_circular_import_is_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "a.suma").write_text("""
import "./b.suma"

pub main(): Int {
    return 42
}
""")
        (root / "b.suma").write_text("""
import "./a.suma"
""")
        try:
            _run((root / "a.suma").read_text(), str(root / "a.suma"))
            assert False, "expected circular import failure"
        except CompileSourceError as exc:
            assert "Circular import detected" in str(exc)


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
