"""Import resolution for Suma source files."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser.ast_nodes import ImportDecl, Program, TopLevel
from suma_lang.frontend.parser.parser import Parser


class ImportResolveError(Exception):
    pass


DEFAULT_PY_IMPORT_ALLOWLIST = frozenset(
    {
        "json",
        "math",
        "statistics",
    }
)


@dataclass
class ImportResolver:
    """Expands ImportDecl nodes into declarations from imported source files."""

    import_paths: list[str] = field(default_factory=list)
    loaded: set[str] = field(default_factory=set)
    loading: list[str] = field(default_factory=list)

    @classmethod
    def with_defaults(cls, import_paths: Iterable[str] | None = None) -> ImportResolver:
        paths: list[str] = []
        paths.extend(_env_path_list("SUMA_PATH"))
        if import_paths:
            paths.extend(str(p) for p in import_paths if str(p))
        paths.extend(_default_import_paths())
        return cls(import_paths=_dedupe_paths(paths))

    def resolve_program(self, program: Program, filename: str | None = None) -> Program:
        current_file = _normalize_filename(filename)
        py_imports: dict[str, str] = dict(program.py_imports)
        decls = self._expand_declarations(program.declarations, current_file, py_imports)
        return Program(declarations=decls, py_imports=py_imports)

    def load_file(self, path: str) -> Program:
        full_path = _real(path)
        if full_path in self.loaded:
            return Program(declarations=[])
        if full_path in self.loading:
            cycle = " -> ".join([*self.loading, full_path])
            raise ImportResolveError(f"Circular import detected: {cycle}")

        self.loading.append(full_path)
        try:
            source = Path(full_path).read_text()
            tokens = Tokenizer.tokenize(source, file_name=full_path)
            program = Parser.parse(tokens)
            expanded = self.resolve_program(program, full_path)
            self.loaded.add(full_path)
            return expanded
        finally:
            self.loading.pop()

    def _expand_declarations(
        self,
        declarations: Iterable[TopLevel],
        current_file: str | None,
        py_imports: dict[str, str],
    ) -> list[TopLevel]:
        expanded: list[TopLevel] = []
        for decl in declarations:
            if isinstance(decl, ImportDecl):
                if decl.path.startswith("py:"):
                    module_name, alias = _parse_py_import(decl.path[3:])
                    if not module_name:
                        raise ImportResolveError("Python import path cannot be empty")
                    if not is_python_import_allowed(module_name):
                        raise ImportResolveError(
                            f"Python import '{module_name}' is not allowed; "
                            "set SUMA_PY_IMPORTS to allow trusted modules"
                        )
                    py_imports[alias] = module_name
                    continue
                imported_path = self._resolve_import_path(decl.path, current_file)
                imported = self.load_file(imported_path)
                py_imports.update(imported.py_imports)
                expanded.extend(imported.declarations)
            else:
                expanded.append(decl)
        return expanded

    def _resolve_import_path(self, import_path: str, current_file: str | None) -> str:
        attempted: list[str] = []
        raw = Path(import_path).expanduser()

        if raw.is_absolute():
            for candidate in _candidate_files(raw):
                attempted.append(str(candidate))
                if candidate.is_file():
                    return _real(candidate)
            raise self._not_found(import_path, attempted)

        search_roots: list[Path] = []
        if current_file and current_file not in ("<stdin>", "<unknown>"):
            search_roots.append(Path(current_file).resolve().parent)
        if not import_path.startswith(("./", "../")):
            search_roots.extend(Path(p).expanduser() for p in self.import_paths)

        for root in search_roots:
            for candidate in _candidate_files(root / raw):
                attempted.append(str(candidate))
                if candidate.is_file():
                    return _real(candidate)

        raise self._not_found(import_path, attempted)

    def _not_found(self, import_path: str, attempted: list[str]) -> ImportResolveError:
        tried = "\n  ".join(attempted) if attempted else "<no search paths>"
        return ImportResolveError(f"Cannot resolve import '{import_path}'. Tried:\n  {tried}")


def resolve_imports(
    program: Program,
    filename: str | None = None,
    import_paths: Iterable[str] | None = None,
) -> Program:
    return ImportResolver.with_defaults(import_paths).resolve_program(program, filename)


def _candidate_files(path: Path) -> list[Path]:
    if path.suffix:
        return [path]
    return [path, path.with_suffix(".suma")]


def _default_import_paths() -> list[str]:
    project_root = Path(__file__).resolve().parents[4]
    return [
        str(Path.cwd()),
        str(project_root),
        *_stdlib_import_paths(project_root),
    ]


def _stdlib_import_paths(project_root: Path) -> list[str]:
    configured = _env_path_list("SUMA_STDLIB_PATHS")
    return [*configured, str(project_root / "stdlib")]


def _env_path_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    if not raw:
        return []
    return [part for part in raw.split(os.pathsep) if part]


def _dedupe_paths(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        full_path = _real(Path(path).expanduser())
        if full_path not in seen:
            seen.add(full_path)
            result.append(full_path)
    return result


def _normalize_filename(filename: str | None) -> str | None:
    if filename is None or filename.startswith("<"):
        return filename
    return _real(filename)


def _real(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _py_alias(module_name: str) -> str:
    return module_name.rsplit(".", 1)[-1]


def _parse_py_import(spec: str) -> tuple[str, str]:
    module_name = spec.strip()
    if " as " not in module_name:
        return module_name, _py_alias(module_name)

    module_name, alias = (part.strip() for part in module_name.rsplit(" as ", 1))
    if not module_name or not alias:
        raise ImportResolveError(f"Invalid Python import alias: py:{spec}")
    return module_name, alias


def is_python_import_allowed(module_name: str) -> bool:
    """Return whether a host Python module may be imported by Suma code."""
    allowed = set(DEFAULT_PY_IMPORT_ALLOWLIST)
    env_allowlist = os.environ.get("SUMA_PY_IMPORTS", "")
    allowed.update(item.strip() for item in env_allowlist.split(",") if item.strip())
    for item in allowed:
        if item.endswith(".*") and module_name.startswith(item[:-1]):
            return True
        if module_name == item:
            return True
    return False
