from __future__ import annotations

import sys

import src.cli as cli


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
