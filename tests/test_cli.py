from __future__ import annotations

import sys
from pathlib import Path

import pytest

import suma_lang.cli as cli


def _run_cli(args: list[str], *, capsys, source_path: Path, expected: str = "55") -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["suma", *args, "run", str(source_path)]
        cli.main()
    finally:
        sys.argv = old_argv

    captured = capsys.readouterr()
    assert captured.out.strip() == expected
    assert captured.err.strip() == ""


def test_dump_opt_flag_prints_pseudocode_to_stderr(tmp_path, capsys):
    source_path = tmp_path / "loop.suma"
    source_path.write_text("""
pub sum_to(n: Int): Int {
    total: Int = 0
    i: Int = 1
    loop {
        if (i > n) { break }
        @total += i
        @i += 1
    }
    return total
}

pub main(): Int {
    return sum_to(10)
}
""")

    old_argv = sys.argv
    try:
        sys.argv = ["suma", "--dump-opt", "run", str(source_path)]
        cli.main()
    finally:
        sys.argv = old_argv

    captured = capsys.readouterr()
    assert captured.out.strip() == "55"
    assert "loop while" in captured.err
    assert "function[0] sum_to/1" in captured.err


def test_cli_ir_and_opt_flag_combinations(tmp_path, capsys):
    source_path = tmp_path / "sum.suma"
    source_path.write_text("""
pub sum_to(n: Int): Int {
    total: Int = 0
    i: Int = 1
    loop {
        if (i > n) { break }
        @total += i
        @i += 1
    }
    return total
}

pub main(): Int {
    return sum_to(10)
}
""")

    for args in ([], ["--no-opt"], ["--ir"], ["--ir", "--no-opt"]):
        _run_cli(args, capsys=capsys, source_path=source_path)


def test_cli_options_do_not_leak_between_invocations(tmp_path, capsys):
    source_path = tmp_path / "main.suma"
    source_path.write_text("""
pub main(): Int {
    return 55
}
""")

    cli.main(["--ir", "run", str(source_path)])
    first = capsys.readouterr()
    cli.main(["run", str(source_path)])
    second = capsys.readouterr()

    assert first.out.strip() == "55"
    assert first.err.strip() == ""
    assert second.out.strip() == "55"
    assert second.err.strip() == ""


def test_cli_does_not_print_success_exit_code(tmp_path, capsys):
    source_path = tmp_path / "main.suma"
    source_path.write_text("""
pub main(): Int {
    print("ok")
    return 0
}
""")

    _run_cli([], capsys=capsys, source_path=source_path, expected="ok")


def test_cli_compile_then_execute_round_trip(tmp_path, capsys):
    source_path = tmp_path / "main.suma"
    output_path = tmp_path / "artifact.sumac"
    source_path.write_text("""
pub main(): Int {
    print("round trip")
    return 42
}
""")

    cli.main(["compile", str(source_path), str(output_path)])
    compiled = capsys.readouterr()
    assert output_path.exists()
    assert f"Compiled {source_path} -> {output_path}" in compiled.out
    assert compiled.err.strip() == ""

    cli.main(["execute", str(output_path)])
    executed = capsys.readouterr()
    assert executed.out.strip() == "round trip\n42".strip()
    assert executed.err.strip() == ""


def test_cli_import_path_flag_resolves_module(tmp_path, capsys):
    module_dir = tmp_path / "modules"
    module_dir.mkdir()
    (module_dir / "custom_tools.suma").write_text("""
pub triple(n: Int): Int {
    return n * 3
}
""")

    source_path = tmp_path / "main.suma"
    source_path.write_text("""
import "custom_tools"

pub main(): Int {
    return triple(14)
}
""")

    cli.main(["-I", str(module_dir), "run", str(source_path)])
    captured = capsys.readouterr()
    assert captured.out.strip() == "42"
    assert captured.err.strip() == ""


def test_cli_reports_runtime_errors_without_traceback(tmp_path, capsys):
    source_path = tmp_path / "main.suma"
    source_path.write_text("""
pub main(): Int {
    return 1 / 0
}
""")

    with pytest.raises(SystemExit) as exc:
        cli.main(["run", str(source_path)])

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert captured.out.strip() == ""
    assert "[Runtime] Division by zero" in captured.err
    assert "Traceback" not in captured.err


def test_argparse_accepts_options_before_and_after_command(monkeypatch):
    calls = []

    def fake_build_and_run(input_path: str, options: cli.CompileOptions | None = None) -> None:
        calls.append((input_path, options))

    monkeypatch.setattr(cli, "cmd_build_and_run", fake_build_and_run)

    cli.main(
        [
            "--ir",
            "-Ibefore",
            "run",
            "program.suma",
            "--no-opt",
            "--import-path=after",
        ]
    )

    assert len(calls) == 1
    input_path, options = calls[0]
    assert input_path == "program.suma"
    assert options == cli.CompileOptions(
        optimize=False,
        use_ir=True,
        dump_opt=False,
        import_paths=("before", "after"),
    )


def test_argparse_rejects_unknown_command(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["unknown", "program.suma"])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "invalid choice" in captured.err
    assert "unknown" in captured.err


def test_argparse_rejects_extra_run_argument(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "program.suma", "extra.suma"])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "run accepts only one file argument" in captured.err
