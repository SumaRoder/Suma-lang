from __future__ import annotations

import os
import tempfile
from importlib import resources
from pathlib import Path

from suma_lang.api import CompileOptions, CompileSourceError, compile_source
from suma_lang.frontend.imports import resolver as resolver_mod
from suma_lang.runtime.vm.vm import VM


def _run(source: str, filename: str, import_paths: list[str] | None = None):
    program = compile_source(source, filename, import_paths=import_paths)
    return VM(program).run()


def _run_with_ir(source: str, filename: str, import_paths: list[str] | None = None):
    program = compile_source(
        source,
        filename,
        import_paths=import_paths,
        options=CompileOptions(use_ir=True),
    )
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


def test_stdlib_paths_env_uses_list_order(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        first = root / "stdlib-first"
        second = root / "stdlib-second"
        first.mkdir()
        second.mkdir()
        (first / "ordering.suma").write_text("""
pub value(): Int {
    return 40
}
""")
        (second / "ordering.suma").write_text("""
pub value(): Int {
    return 99
}
""")
        monkeypatch.setenv(
            "SUMA_STDLIB_PATHS",
            os.pathsep.join([str(first), str(second)]),
        )
        source = """
import "ordering"

pub main(): Int {
    return value() + 2
}
"""
        assert _run(source, str(root / "main.suma")) == 42


def test_stdlib_paths_env_keeps_builtin_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("SUMA_STDLIB_PATHS", tmpdir)
        source = """
import "core"

pub main(): Int {
    return clamp(99, 0, 42)
}
"""
        assert _run(source, "<stdin>") == 42


def test_package_stdlib_resources_are_available():
    stdlib = resources.files("suma_lang").joinpath("stdlib")
    assert stdlib.joinpath("core.suma").is_file()
    assert stdlib.joinpath("math.suma").is_file()
    assert stdlib.joinpath("list.suma").is_file()
    assert stdlib.joinpath("json.suma").is_file()


def test_package_stdlib_fallback_without_source_tree(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(resolver_mod, "_source_tree_root", lambda: None)
    source = """
import "core"

pub main(): Int {
    return clamp(99, 0, 42)
}
"""
    assert _run(source, "<stdin>") == 42


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


def test_import_only_exposes_public_top_level_names_direct_and_ir():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "service.suma").write_text("""
helper(): Int {
    return 40
}

pri secret(): Int {
    return 1
}

pub answer(): Int {
    return helper() + secret() + 1
}
""")
        source = """
import "./service.suma"

pub main(): Int {
    return answer()
}
"""
        assert _run(source, str(root / "main.suma")) == 42
        assert _run_with_ir(source, str(root / "main.suma")) == 42


def test_imported_private_top_level_names_are_not_visible_to_importer():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "service.suma").write_text("""
helper(): Int {
    return 42
}

pub answer(): Int {
    return helper()
}
""")
        source = """
import "./service.suma"

pub main(): Int {
    return helper()
}
"""
        try:
            _run(source, str(root / "main.suma"))
            raise AssertionError("expected private import failure")
        except CompileSourceError as exc:
            assert "Undefined name 'helper'" in str(exc)


def test_import_visibility_modifiers_are_rejected():
    source = """
pub import "core"

pub main(): Int {
    return 42
}
"""
    try:
        _run(source, "<stdin>")
        raise AssertionError("expected import visibility parse failure")
    except CompileSourceError as exc:
        assert "import declarations cannot be marked pub or pri" in str(exc)


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
            raise AssertionError("expected import failure")
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
            raise AssertionError("expected circular import failure")
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
