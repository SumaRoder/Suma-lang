from __future__ import annotations

import sys
from pathlib import Path

import pytest

import src.cli as cli


def _run_cli(args: list[str], *, capsys, source_path: Path, expected: str = "55") -> None:
    old_argv = sys.argv
    old_optimize = cli._optimize
    old_use_ir = cli._use_ir
    old_dump_opt = cli._dump_opt
    old_import_paths = list(cli._import_paths)
    try:
        sys.argv = ["suma", *args, "run", str(source_path)]
        cli._optimize = True
        cli._use_ir = False
        cli._dump_opt = False
        cli._import_paths = []
        cli.main()
    finally:
        sys.argv = old_argv
        cli._optimize = old_optimize
        cli._use_ir = old_use_ir
        cli._dump_opt = old_dump_opt
        cli._import_paths = old_import_paths

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
        total += i
        i += 1
    }
    return total
}

pub main(): Int {
    return sum_to(10)
}
""")

    old_argv = sys.argv
    old_optimize = cli._optimize
    old_use_ir = cli._use_ir
    old_dump_opt = cli._dump_opt
    old_import_paths = list(cli._import_paths)
    try:
        sys.argv = ["suma", "--dump-opt", "run", str(source_path)]
        cli._optimize = True
        cli._use_ir = False
        cli._dump_opt = False
        cli._import_paths = []
        cli.main()
    finally:
        sys.argv = old_argv
        cli._optimize = old_optimize
        cli._use_ir = old_use_ir
        cli._dump_opt = old_dump_opt
        cli._import_paths = old_import_paths

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
        total += i
        i += 1
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
    assert cli._use_ir is False


def test_cli_does_not_print_success_exit_code(tmp_path, capsys):
    source_path = tmp_path / "main.suma"
    source_path.write_text("""
pub main(): Int {
    print("ok")
    return 0
}
""")

    _run_cli([], capsys=capsys, source_path=source_path, expected="ok")


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
