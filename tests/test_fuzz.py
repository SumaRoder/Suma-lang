"""Property-based smoke tests for the Suma frontend and serializer.

These never assert correctness against a reference — only that "random input
in" never produces "Python exception out" for input the harness was supposed
to handle gracefully. The win is catching parser/tokenizer / round-trip
crashes that the deterministic suite happens not to reach.
"""

from __future__ import annotations

import contextlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from suma_lang.api import CompileOptions, CompileSourceError, compile_source
from suma_lang.backend.codegen.opcodes import Function, Op, ProgramBytecode
from suma_lang.backend.codegen.serializer import (
    BytecodeFormatError,
    deserialize,
    serialize,
)
from suma_lang.frontend.lexer.tokenizer import Tokenizer

FUZZ = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# Tokenizer fuzz: arbitrary text must either tokenize or raise SyntaxError,
# never a Python-internal crash (IndexError, AttributeError, …).
@FUZZ
@given(st.text(max_size=200))
def test_tokenizer_never_crashes(source: str) -> None:
    with contextlib.suppress(SyntaxError):
        Tokenizer.tokenize(source, file_name="<fuzz>")


# Compiler fuzz: any random text must surface as either bytecode or a
# CompileSourceError. SyntaxError can leak through if Tokenizer raises before
# Parser, and that's still a controlled failure.
@FUZZ
@given(st.text(max_size=200))
def test_compile_source_never_crashes_on_garbage(source: str) -> None:
    with contextlib.suppress(CompileSourceError, SyntaxError):
        compile_source(source, "<fuzz>", options=CompileOptions(optimize=False))


# Valid programs generated from a tiny grammar must compile cleanly and run.
_INT_PROGRAM = st.builds(
    lambda lhs, op, rhs: f"pub main(): Int {{\n    return {lhs} {op} {rhs}\n}}\n",
    st.integers(min_value=-1000, max_value=1000),
    st.sampled_from(["+", "-", "*"]),
    st.integers(min_value=-1000, max_value=1000),
)


@FUZZ
@given(_INT_PROGRAM)
def test_simple_int_programs_compile(source: str) -> None:
    compile_source(source, "<fuzz>", options=CompileOptions(optimize=False))


# Round-trip: a hand-built ProgramBytecode survives serialize → deserialize.
_CONSTANT = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=20),
)


def _serializer_program(consts: list, fn_consts: list) -> ProgramBytecode:
    fn = Function(
        name="main",
        arity=0,
        code=[int(Op.LOAD_NULL), int(Op.RETURN)],
        constants=fn_consts,
        locals_count=0,
    )
    return ProgramBytecode(functions=[fn], constants=consts, entry=0)


@FUZZ
@given(
    st.lists(_CONSTANT, max_size=10),
    st.lists(_CONSTANT, max_size=10),
)
def test_serializer_round_trip(consts: list, fn_consts: list) -> None:
    program = _serializer_program(consts, fn_consts)
    blob = serialize(program)
    restored = deserialize(blob)
    assert restored.entry == program.entry
    assert restored.constants == program.constants
    assert len(restored.functions) == 1
    assert restored.functions[0].code == program.functions[0].code
    assert restored.functions[0].constants == program.functions[0].constants


# Mutated bytecode: bad bytes must produce a typed BytecodeFormatError, never
# an undeclared exception class.
@FUZZ
@given(st.binary(max_size=64))
def test_deserialize_rejects_random_bytes(blob: bytes) -> None:
    with contextlib.suppress(BytecodeFormatError):
        deserialize(blob)


def test_deserialize_rejects_empty_function_table() -> None:
    blob = serialize(ProgramBytecode(functions=[], constants=[], entry=0))
    with pytest.raises(BytecodeFormatError, match="no functions"):
        deserialize(blob)


def test_deserialize_rejects_unknown_opcode() -> None:
    fn = Function(name="main", arity=0, code=[999], locals_count=0)
    blob = serialize(ProgramBytecode(functions=[fn], constants=[], entry=0))
    with pytest.raises(BytecodeFormatError, match="unknown opcode"):
        deserialize(blob)


def test_deserialize_rejects_truncated_opcode_operand() -> None:
    fn = Function(name="main", arity=0, code=[int(Op.LOAD_CONST)], locals_count=0)
    blob = serialize(ProgramBytecode(functions=[fn], constants=[], entry=0))
    with pytest.raises(BytecodeFormatError, match="truncated LOAD_CONST"):
        deserialize(blob)


def test_deserialize_rejects_call_global_arity_mismatch() -> None:
    helper = Function(
        name="helper",
        arity=0,
        code=[int(Op.LOAD_NULL), int(Op.RETURN)],
        locals_count=0,
    )
    main = Function(
        name="main",
        arity=0,
        code=[int(Op.CALL_GLOBAL), (3 << 16) | 0, int(Op.RETURN)],
        locals_count=0,
    )
    blob = serialize(ProgramBytecode(functions=[helper, main], constants=[], entry=1))
    with pytest.raises(BytecodeFormatError, match="call arity"):
        deserialize(blob)


def test_deserialize_rejects_bad_decorator_function_index() -> None:
    fn = Function(name="main", arity=0, code=[int(Op.LOAD_NULL), int(Op.RETURN)], locals_count=0)
    blob = serialize(ProgramBytecode(functions=[fn], constants=[], decorators={"main": 999}))
    with pytest.raises(BytecodeFormatError, match="decorators"):
        deserialize(blob)
