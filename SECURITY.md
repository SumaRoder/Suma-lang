# Security Policy

## Supported versions

Suma-lang is pre-1.0 (currently 0.1.x). Only the latest release on `py-main`
receives security fixes. There is no LTS.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Report privately via GitHub's [private vulnerability reporting](https://github.com/SumaRoder/suma-lang/security/advisories/new),
or email the maintainer at 1493813167@qq.com with subject prefix `[suma-lang
security]`.

Include:

- A clear description of the issue
- Reproduction steps or a minimal `.suma` / `.sumac` sample
- The Suma-lang version (`suma --version` once available, or commit SHA)
- Your Python version and OS

We will acknowledge within 7 days and aim to publish a fix within 30 days for
high-severity issues.

## Scope

In scope:

- Crashes or memory corruption in the VM
- Sandbox escapes from compiled `.sumac` bytecode (e.g. arbitrary host code
  execution beyond what `SUMA_PY_IMPORTS` allows)
- Bytecode deserialization vulnerabilities in `backend/codegen/serializer.py`
- Import resolution issues that load files outside the configured search paths

Out of scope:

- Issues that only manifest when `SUMA_PY_IMPORTS` explicitly allows an unsafe
  Python module — the user opted in
- Denial of service via pathological input to the compiler (we'll fix these but
  they don't qualify for embargo)
- Bugs in development tooling (ruff, pyright, pytest) — report upstream
