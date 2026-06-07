from __future__ import annotations

from suma_lang.api import compile_source_with_diagnostics
from suma_lang.frontend.imports.resolver import ImportResolver
from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser.parser import Parser
from suma_lang.frontend.semantic.analyzer import Analyzer


def _analyze(src: str, *, strict: bool = False) -> Analyzer:
    tokens = Tokenizer.tokenize(src, file_name="<test>")
    ast = Parser.parse(tokens)
    ast = ImportResolver.with_defaults(()).resolve_program(ast, "<test>")
    a = Analyzer(strict_shadowing=strict)
    a.analyze(ast)
    return a


def test_implicit_shadow_in_nested_block_warns():
    src = """
    pub main(): Int {
        i: Int = 0
        if true {
            i = 99
        }
        return i
    }
    """
    a = _analyze(src)
    assert a.errors == []
    assert any("shadows outer binding" in w for w in a.warnings), a.warnings


def test_at_prefix_assignment_does_not_warn():
    src = """
    pub main(): Int {
        i: Int = 0
        if true {
            @i = 99
        }
        return i
    }
    """
    a = _analyze(src)
    assert a.errors == []
    assert a.warnings == []


def test_function_top_level_assignment_does_not_warn():
    src = """
    pub main(): Int {
        i = 0
        i = 99
        return i
    }
    """
    a = _analyze(src)
    assert a.errors == []
    assert a.warnings == []


def test_match_arm_expression_body_does_not_warn():
    # Match arm expression bodies use a synthetic scope solely to bind `it`;
    # the compiler does not introduce a real scope there, so bare assignments
    # should not be flagged.
    src = """
    pub flag(x: Bool) {
        if x { return Ok(1) }
        return Err("no")
    }

    pub main(): Int {
        total: Int = 0
        match flag(true) {
            Ok => total = total + it
            Err => total = total - 10
        }
        return total
    }
    """
    a = _analyze(src)
    assert a.errors == []
    assert a.warnings == [], a.warnings


def test_strict_shadowing_promotes_warning_to_error():
    src = """
    pub main(): Int {
        i: Int = 0
        if true {
            i = 99
        }
        return i
    }
    """
    a = _analyze(src, strict=True)
    assert a.warnings == []
    assert any("shadows outer binding" in e for e in a.errors), a.errors


def test_compile_source_with_diagnostics_returns_warnings():
    src = """
    pub main(): Int {
        i: Int = 0
        if true {
            i = 99
        }
        return i
    }
    """
    result = compile_source_with_diagnostics(src, "<test>")
    assert result.program is not None
    assert any(
        d.level == "warning" and "shadows outer binding" in d.message for d in result.warnings
    ), result.warnings
    warning = next(d for d in result.warnings if "shadows outer binding" in d.message)
    assert warning.source == "Analyzer"
    assert warning.location == (5, 13)
