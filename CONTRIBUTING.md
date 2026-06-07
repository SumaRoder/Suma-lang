# Contributing to Suma-lang

Thanks for considering a contribution. This document describes how to set up the
project, the workflow we expect for changes, and the conventions the codebase
follows.

## Development setup

We use [uv](https://github.com/astral-sh/uv) for environment management. Plain
pip works for installing the runtime, but dev tooling (pytest, hypothesis,
pyright, pip-audit) lives in the PEP 735 `[dependency-groups].dev` table, which
only uv resolves automatically.

```bash
# Clone and enter
git clone https://github.com/SumaRoder/suma-lang.git
cd suma-lang

# Install everything (runtime + dev + lint + docs extras)
uv sync --extra lint --extra docs --dev

# Smoke check
uv run suma run examples/hello.suma
```

## Running the gates locally

The same gates run in CI; running them locally avoids the round-trip:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q --cov=suma_lang --cov-fail-under=80
```

CI also runs `pip-audit` against the resolved dependency set. New dependencies
have to clear that check.

## Branching and PRs

- Default branch is `py-main`. Open PRs against it.
- Feature branches push to any name; CI runs on every branch.
- Keep PRs focused. A bug fix and a refactor in the same PR are two PRs.
- Reference the issue in the PR body when one exists.

### Commit messages

Use the imperative mood ("Add IR pass for constant folding", not "Added" or
"Adds"). The body should explain *why*, not *what* — the diff is the *what*.

## Code conventions

- **Layout** — `frontend/` parses, `mid/` lowers and optimizes IR, `backend/`
  emits bytecode, `runtime/` executes. Cross-layer imports should respect that
  direction.
- **Public API** — `suma_lang.api` is the embedding surface. Anything reachable
  from there needs a docstring and a test.
- **Errors** — frontend raises `CompileSourceError` with diagnostics, runtime
  raises `VMError`, bytecode IO raises `BytecodeFormatError`. Do not invent new
  top-level error classes without discussion.
- **Style** — ruff handles formatting; do not hand-format. `target-version`
  is `py310` so language features newer than that are out.

## Tests

- New features need tests in `tests/`. The bar is "the test would have caught a
  regression that broke this feature."
- Bug fixes should include a test that fails without the fix.
- `tests/test_fuzz.py` uses hypothesis. If you touch the lexer or parser,
  consider whether a property-based test fits.
- Example programs under `examples/` double as integration tests through
  `tests/test_example_programs.py`.

## Benchmarks

`tests/test_benchmarks.py` uses `pytest-benchmark` to time the compile pipeline
and the VM on representative workloads. The default `pytest` run skips them
(they're slow — fib(30) alone is ~17s on the VM). Run them locally with:

```bash
uv run pytest tests/test_benchmarks.py \
  --benchmark-enable --benchmark-only \
  --benchmark-columns=min,mean,median,stddev,ops
```

CI runs the same command on every push and uploads `benchmark.json` as an
artifact. If you change the optimizer, IR lowering, or VM dispatch, check the
benchmark artifact on your PR to confirm you haven't regressed performance.

## Documentation

The site at <https://SumaRoder.github.io/suma-lang/> is built from `docs/` via
MkDocs Material. Run `uv run mkdocs serve` for a live preview. CI builds with
`--strict`, so broken links and unknown nav entries fail the docs job.

## Reporting issues

- Bug? Use the "Bug report" issue template.
- Feature idea? Use the "Feature request" template.
- Security issue? Read [SECURITY.md](SECURITY.md) first — do not file a public
  issue for unpatched vulnerabilities.
