# Changelog

All notable changes to Suma-lang are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims
for [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it leaves
0.x.

## [Unreleased]

## [0.2.0] — 2026-06-07

### Added
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, GitHub issue and PR
  templates under `.github/`.
- Dedicated lexer test suite in `tests/test_lexer.py` (107 cases covering
  keywords, identifiers, numbers, strings, operators, comments, position
  tracking).
- CI coverage gate at 80% (`--cov-fail-under=80`).
- CI now runs on every branch push, not just `py-main`.
- `reportUnnecessaryComparison`, `reportMissingParameterType`, and
  `reportUnusedFunction` enabled as pyright errors.
- The lexer package (`suma_lang.frontend.lexer`) is the first module compiled
  with `# pyright: strict` — full Unknown-type checking.
- Performance benchmarks (`tests/test_benchmarks.py`) using `pytest-benchmark`,
  covering compile-only and run-only timings for fib, factorial, and the
  numeric/string stress programs. A separate CI `benchmarks` job runs them and
  uploads `benchmark.json` as an artifact (90-day retention).
- CI validates built wheel/sdist metadata with `twine check` before package
  smoke tests.
- Surface non-fatal analyzer diagnostics through `CompileResult`,
  `compile_source_with_diagnostics`, and CLI warning output. Warnings include
  structured `Diagnostic.location` data for embedders.
- EBNF grammar reference in `docs/grammar.md`, including the expression
  precedence table and parser implementation notes.

### Refactored
- **Parser split.** Extracted the expression-precedence ladder (19 methods,
  `_parse_expression` through `_parse_member`) from `parser.py` into a new
  `_expressions.py` module as `_ExpressionsMixin`. `parser.py` dropped from
  1544 → 1279 lines; behavior is unchanged (all 496 tests still pass).
- String interpolation now uses a structured `InterpolatedStringExpr` AST node
  instead of being expanded in the parser into `to_str(...)` calls and binary
  concatenation chains.
- **VM dispatch infrastructure split.** Moved the `OC` opcode-constant class,
  `_apply_binop_fast`, `_compare_values`, and the operator-method lookup
  tables from `vm.py` into a new `_dispatch.py` module. `vm.py` dropped from
  1618 → 1509 lines without touching the hot `_execute` loop.
- **Semantic analyzer split.** Moved scope state, flow narrowing state,
  expression type inference, and type/member registry state into
  `ScopeResolver`, `FlowAnalyzer`, `TypeInferrer`, and `TypeRegistry`.

### Changed
- README now documents `--ir` and `--dump-opt` CLI flags, and clarifies that
  dev dependencies require uv (PEP 735 `[dependency-groups]`).
- Standard library is now sourced exclusively from `src/suma_lang/stdlib/`.
  The duplicated root-level `stdlib/` directory was removed and the import
  resolver simplified accordingly. `SUMA_STDLIB_PATHS` continues to work for
  overrides.
- Parser parenthesized primary lookahead now classifies lambda, tuple, and
  grouped expressions through a shared cached path.
- Runtime overload dispatch now reuses the semantic type helper for base-type
  normalization, including legacy `Result<...>` spellings.

### Fixed
- Dead `or expected is None` branch in `analyzer._expect_type` removed
  (caught by the new pyright rule).
- Removed unused `_is_constant` helper from `mid/ir/optimizer.py`.
- IR bytecode optimization now elides more single-use spill temps for plain
  binary expressions, direct returns, and direct-call arguments.
- Added missing `TokenInfo` type annotations on parser/lexer error-handling
  parameters (`error_handler.report`, `parser._parse_destructure_decl`,
  `parser._parse_string_literal`, `parser._parse_interpolation_expr`).
- Annotated `SumaCallable.callback_any` `*args` parameter in `values.py`.
- Declared `__all__` in `runtime.vm.format` so cross-module imports of the
  hot-path `_to_str_fast` and `_format_value` helpers are visible to type
  checkers.
- Implicit-shadow diagnostics now catch bare assignment in nested scopes while
  preserving the `@name = ...` escape hatch for outer updates.
- `examples/stress_classes.suma` now updates the intended outer counter state;
  its expected result/output assertions were corrected accordingly.
- Compiler, IR, codegen, and bytecode-format failures are wrapped consistently
  as `CompileSourceError` diagnostics in the public API.

## [0.1.0] — 2026-05-31

Initial alpha release.

### Added
- Statically-typed language with Result types, pattern matching, enums,
  classes, and first-class functions.
- Bytecode compiler with multi-pass optimization (peephole + IR-based).
- Stack-based VM.
- Python host API for embedding.
- MkDocs Material documentation site.

[Unreleased]: https://github.com/SumaRoder/suma-lang/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SumaRoder/suma-lang/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SumaRoder/suma-lang/releases/tag/v0.1.0
