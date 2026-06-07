"""Unit tests for the lexer.

Tokenization is exercised end-to-end through parser/analyzer tests, but those
hide failures behind layers. These tests target the tokenizer directly so that
a regression in lexing surfaces immediately and points at the right file.
"""

from __future__ import annotations

import pytest

from suma_lang.frontend.lexer import Token, Tokenizer, TokenType


def lex(src: str) -> list[Token]:
    return Tokenizer.tokenize(src, "<test>")


def types(src: str) -> list[TokenType]:
    return [t.type for t in lex(src)]


def literals(src: str) -> list[str | None]:
    return [t.literal for t in lex(src)]


# ---------------------------------------------------------------------------
# Trivial / boundary
# ---------------------------------------------------------------------------


def test_empty_source_yields_only_eof():
    tokens = lex("")
    assert len(tokens) == 1
    assert tokens[0].type == TokenType.EOF


def test_whitespace_is_skipped():
    assert types("   \t\n\r ") == [TokenType.EOF]


def test_eof_appended_after_real_tokens():
    tokens = lex("42")
    assert tokens[-1].type == TokenType.EOF


# ---------------------------------------------------------------------------
# Keywords vs identifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("return", TokenType.RETURN),
        ("if", TokenType.IF),
        ("elif", TokenType.ELIF),
        ("else", TokenType.ELSE),
        ("while", TokenType.WHILE),
        ("for", TokenType.FOR),
        ("in", TokenType.IN),
        ("loop", TokenType.LOOP),
        ("break", TokenType.BREAK),
        ("continue", TokenType.CONTINUE),
        ("init", TokenType.INIT),
        ("this", TokenType.THIS),
        ("import", TokenType.IMPORT),
        ("true", TokenType.TRUE),
        ("false", TokenType.FALSE),
        ("null", TokenType.NULL),
        ("pub", TokenType.PUBLIC),
        ("pri", TokenType.PRIVATE),
        ("const", TokenType.CONST),
        ("static", TokenType.STATIC),
        ("is", TokenType.IS),
        ("enum", TokenType.ENUM),
        ("match", TokenType.MATCH),
        ("try", TokenType.TRY),
        ("catch", TokenType.CATCH),
        ("finally", TokenType.FINALLY),
        ("throw", TokenType.THROW),
    ],
)
def test_keywords_recognised(source: str, expected: TokenType):
    tokens = lex(source)
    assert tokens[0].type == expected


@pytest.mark.parametrize(
    "ident",
    ["foo", "_bar", "x1", "snake_case", "camelCase", "PascalCase", "_", "__init__"],
)
def test_identifiers(ident: str):
    tokens = lex(ident)
    assert tokens[0].type == TokenType.ID
    assert tokens[0].literal == ident


def test_keyword_prefix_is_still_identifier():
    # "returns" must not parse as RETURN + 's'
    tokens = lex("returns ifx elses")
    assert [t.type for t in tokens[:-1]] == [TokenType.ID, TokenType.ID, TokenType.ID]
    assert [t.literal for t in tokens[:-1]] == ["returns", "ifx", "elses"]


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def test_decimal_integer():
    tokens = lex("12345")
    assert tokens[0].type == TokenType.INT
    assert tokens[0].literal == "12345"


def test_integer_with_underscore_separators_is_normalised():
    tokens = lex("1_000_000")
    assert tokens[0].type == TokenType.INT
    assert tokens[0].literal == "1000000"


def test_hex_integer():
    tokens = lex("0xCAFE 0X10")
    assert tokens[0].type == TokenType.INT
    assert tokens[0].literal == "0xCAFE"
    assert tokens[1].type == TokenType.INT
    assert tokens[1].literal == "0X10"


def test_float_basic():
    tokens = lex("3.14")
    assert tokens[0].type == TokenType.FLOAT
    assert tokens[0].literal == "3.14"


def test_float_with_underscore():
    tokens = lex("1_234.567_8")
    assert tokens[0].type == TokenType.FLOAT
    assert tokens[0].literal == "1234.5678"


def test_dot_followed_by_dot_is_range_not_float():
    # 1..5 must lex as INT RANGE INT, not as 1. .5
    assert types("1..5") == [
        TokenType.INT,
        TokenType.RANGE,
        TokenType.INT,
        TokenType.EOF,
    ]


def test_inclusive_range():
    assert types("1..=5") == [
        TokenType.INT,
        TokenType.RANGE_INCLUSIVE,
        TokenType.INT,
        TokenType.EOF,
    ]


def test_invalid_number_suffix_raises():
    with pytest.raises(SyntaxError):
        lex("123abc")


def test_invalid_hex_no_digits_raises():
    with pytest.raises(SyntaxError):
        lex("0x")


def test_float_dot_without_digit_raises():
    with pytest.raises(SyntaxError):
        lex("1.x")


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------


def test_simple_string_double_quotes():
    tokens = lex('"hello"')
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].literal == "hello"


def test_simple_string_single_quotes():
    tokens = lex("'hi'")
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].literal == "hi"


def test_string_escape_sequences():
    tokens = lex(r'"a\nb\tc\\d\"e"')
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].literal == 'a\nb\tc\\d"e'


def test_raw_string_no_escape_processing():
    tokens = lex(r'r"a\nb"')
    assert tokens[0].type == TokenType.RAW_STRING
    assert tokens[0].literal == r"a\nb"


def test_unterminated_string_raises():
    with pytest.raises(SyntaxError):
        lex('"unterminated')


# ---------------------------------------------------------------------------
# Operators and delimiters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("+", TokenType.ADD),
        ("-", TokenType.MINUS),
        ("*", TokenType.MULT),
        ("/", TokenType.DIV),
        ("%", TokenType.REM),
        ("^", TokenType.XOR),
        ("~", TokenType.NOTB),
        ("&", TokenType.ANDB),
        ("|", TokenType.ORB),
        ("!", TokenType.NOTL),
        ("=", TokenType.ASSIGN),
        (">", TokenType.GT),
        ("<", TokenType.LT),
        ("(", TokenType.LPAR),
        (")", TokenType.RPAR),
        ("[", TokenType.LBRACK),
        ("]", TokenType.RBRACK),
        ("{", TokenType.LBRA),
        ("}", TokenType.RBRA),
        (";", TokenType.SEM),
        (",", TokenType.COMMA),
        (".", TokenType.DOT),
        ("#", TokenType.HASH),
        ("@", TokenType.AT),
        (":", TokenType.COLON),
        ("?", TokenType.QUEST),
    ],
)
def test_single_char_operators(source: str, expected: TokenType):
    assert lex(source)[0].type == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("&&", TokenType.ANDL),
        ("||", TokenType.ORL),
        ("<<", TokenType.SHIFTL),
        (">>", TokenType.SHIFTR),
        ("==", TokenType.EQ),
        ("!=", TokenType.NE),
        (">=", TokenType.GE),
        ("<=", TokenType.LE),
        ("+=", TokenType.ADD_ASSIGN),
        ("-=", TokenType.MINUS_ASSIGN),
        ("*=", TokenType.MULT_ASSIGN),
        ("/=", TokenType.DIV_ASSIGN),
        ("%=", TokenType.REM_ASSIGN),
        ("->", TokenType.ARROW),
        ("=>", TokenType.FAT_ARROW),
        ("..", TokenType.RANGE),
        ("..=", TokenType.RANGE_INCLUSIVE),
        ("++", TokenType.PLUSPLUS),
        ("--", TokenType.MINUSMINUS),
        ("??", TokenType.NULL_COALESCE),
    ],
)
def test_multi_char_operators(source: str, expected: TokenType):
    assert lex(source)[0].type == expected


def test_unexpected_character_raises():
    with pytest.raises(SyntaxError):
        lex("`")


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def test_line_comment_skipped():
    tokens = lex("42 // a comment\n7")
    assert [t.type for t in tokens] == [TokenType.INT, TokenType.INT, TokenType.EOF]
    assert [t.literal for t in tokens[:-1]] == ["42", "7"]


def test_block_comment_skipped():
    tokens = lex("1 /* multi\nline */ 2")
    assert [t.type for t in tokens] == [TokenType.INT, TokenType.INT, TokenType.EOF]


def test_block_comment_at_end_of_file_is_tolerated_or_errors():
    # Either it silently skips OR raises a syntax error — both are acceptable
    # behaviors, what we don't want is a silent infinite loop. We just ensure
    # tokenize returns within a finite time.
    try:
        tokens = lex("1 /* unterminated")
        assert tokens[0].type == TokenType.INT
    except SyntaxError:
        pass


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------


def test_line_and_column_tracking():
    tokens = lex("a\n  b")
    assert tokens[0].literal == "a"
    assert tokens[0].info.line == 1
    assert tokens[1].literal == "b"
    assert tokens[1].info.line == 2
    assert tokens[1].info.column >= 3  # after two-space indent


def test_file_name_propagates_to_tokens():
    tokens = Tokenizer.tokenize("x", "my_file.suma")
    assert tokens[0].info.file == "my_file.suma"


# ---------------------------------------------------------------------------
# Realistic snippet
# ---------------------------------------------------------------------------


def test_function_declaration_sequence():
    src = "pub add(a: Int, b: Int): Int { return a + b }"
    expected = [
        TokenType.PUBLIC,
        TokenType.ID,  # add
        TokenType.LPAR,
        TokenType.ID,  # a
        TokenType.COLON,
        TokenType.ID,  # Int
        TokenType.COMMA,
        TokenType.ID,  # b
        TokenType.COLON,
        TokenType.ID,
        TokenType.RPAR,
        TokenType.COLON,
        TokenType.ID,
        TokenType.LBRA,
        TokenType.RETURN,
        TokenType.ID,
        TokenType.ADD,
        TokenType.ID,
        TokenType.RBRA,
        TokenType.EOF,
    ]
    assert types(src) == expected
