"""Suma-lang Mid-level IR — intermediate representation for optimization."""

from .ir import *
from .codegen import ir_to_bytecode
from .lower import lower_to_ir
from .optimizer import optimize_ir

__all__ = [name for name in globals() if not name.startswith("_") and name not in {"annotations"}]
