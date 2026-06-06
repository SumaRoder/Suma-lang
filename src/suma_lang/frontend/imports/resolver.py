"""Import resolution for Suma source files."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from hashlib import blake2s
from pathlib import Path

from suma_lang.frontend.lexer.tokenizer import Tokenizer
from suma_lang.frontend.parser import ast_nodes as ast
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
            expanded = _rewrite_imported_program(expanded, full_path)
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


_TYPE_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _rewrite_imported_program(program: Program, module_path: str) -> Program:
    """Hide non-public imported top-level names while preserving internal calls."""
    visibility_by_name: dict[str, set[bool]] = {}
    for decl in program.declarations:
        name = _top_level_name(decl)
        if name is None:
            continue
        visibility_by_name.setdefault(name, set()).add(_top_level_is_pub(decl))

    mixed = [name for name, visibility in visibility_by_name.items() if len(visibility) > 1]
    if mixed:
        names = ", ".join(sorted(mixed))
        raise ImportResolveError(
            f"Cannot import module '{module_path}' with mixed pub/pri overload visibility: {names}"
        )

    mapping = {
        name: _mangled_private_name(module_path, name)
        for name, visibility in visibility_by_name.items()
        if visibility == {False}
    }
    if not mapping:
        return program

    return Program(
        declarations=tuple(_rewrite_decl(decl, mapping) for decl in program.declarations),
        py_imports=dict(program.py_imports),
    )


def _top_level_name(decl: TopLevel) -> str | None:
    if isinstance(decl, ast.FunctionDecl | ast.ClassDecl | ast.EnumDecl | ast.VarDecl):
        return decl.name
    return None


def _top_level_is_pub(decl: TopLevel) -> bool:
    return bool(getattr(decl, "is_pub", False))


def _mangled_private_name(module_path: str, name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", Path(module_path).stem).strip("_") or "module"
    digest = blake2s(module_path.encode("utf-8"), digest_size=5).hexdigest()
    return f"__suma_private_{stem}_{digest}_{name}"


def _rewrite_type_name(
    type_name: str | None, mapping: dict[str, str], type_bound: set[str]
) -> str | None:
    if type_name is None:
        return None

    def replace_name(match: re.Match[str]) -> str:
        name = match.group(0)
        if name in type_bound:
            return name
        return mapping.get(name, name)

    return _TYPE_IDENT_RE.sub(replace_name, type_name)


def _rewrite_param(param: ast.Param, mapping: dict[str, str], type_bound: set[str]) -> ast.Param:
    default = _rewrite_expr(param.default, mapping, set(), type_bound) if param.default else None
    return replace(
        param,
        type_annotation=_rewrite_type_name(param.type_annotation, mapping, type_bound),
        default=default,
    )


def _rewrite_decorator(
    decorator: ast.Decorator, mapping: dict[str, str], type_bound: set[str]
) -> ast.Decorator:
    return replace(decorator, expr=_rewrite_expr(decorator.expr, mapping, set(), type_bound))


def _rewrite_decl(decl: TopLevel, mapping: dict[str, str]) -> TopLevel:
    if isinstance(decl, ast.FunctionDecl):
        return _rewrite_function_decl(decl, mapping, rename_name=True, inherited_type_bound=set())
    if isinstance(decl, ast.ClassDecl):
        type_bound = set(decl.type_params)
        members = []
        for member in decl.members:
            if isinstance(member, ast.FunctionDecl):
                members.append(
                    _rewrite_function_decl(
                        member,
                        mapping,
                        rename_name=False,
                        inherited_type_bound=type_bound,
                    )
                )
            elif isinstance(member, ast.GetterDecl):
                members.append(
                    replace(
                        member,
                        return_type=_rewrite_type_name(member.return_type, mapping, type_bound),
                        body=_rewrite_block(member.body, mapping, {"this"}, type_bound),
                    )
                )
            elif isinstance(member, ast.SetterDecl):
                body_bound = {"this", member.param_name}
                members.append(
                    replace(
                        member,
                        param_type=_rewrite_type_name(member.param_type, mapping, type_bound),
                        body=_rewrite_block(member.body, mapping, body_bound, type_bound),
                    )
                )
            elif isinstance(member, ast.VarDecl):
                init = (
                    _rewrite_expr(member.initializer, mapping, set(), type_bound)
                    if member.initializer
                    else None
                )
                members.append(
                    replace(
                        member,
                        type_annotation=_rewrite_type_name(
                            member.type_annotation, mapping, type_bound
                        ),
                        initializer=init,
                    )
                )
        return replace(
            decl,
            name=mapping.get(decl.name, decl.name),
            base_type=_rewrite_type_name(decl.base_type, mapping, type_bound),
            members=tuple(members),
            decorators=tuple(_rewrite_decorator(d, mapping, type_bound) for d in decl.decorators),
        )
    if isinstance(decl, ast.EnumDecl):
        variants = tuple(
            replace(
                variant,
                payload_type=_rewrite_type_name(variant.payload_type, mapping, set()),
            )
            for variant in decl.variants
        )
        return replace(decl, name=mapping.get(decl.name, decl.name), variants=variants)
    if isinstance(decl, ast.VarDecl):
        init = _rewrite_expr(decl.initializer, mapping, set(), set()) if decl.initializer else None
        return replace(
            decl,
            name=mapping.get(decl.name, decl.name),
            type_annotation=_rewrite_type_name(decl.type_annotation, mapping, set()),
            initializer=init,
        )
    return decl


def _rewrite_function_decl(
    func: ast.FunctionDecl,
    mapping: dict[str, str],
    *,
    rename_name: bool,
    inherited_type_bound: set[str],
) -> ast.FunctionDecl:
    type_bound = {*inherited_type_bound, *func.type_params}
    params = tuple(_rewrite_param(param, mapping, type_bound) for param in func.params)
    value_bound = {param.name for param in params}
    return replace(
        func,
        name=mapping.get(func.name, func.name) if rename_name else func.name,
        params=params,
        return_type=_rewrite_type_name(func.return_type, mapping, type_bound),
        body=_rewrite_block(func.body, mapping, value_bound, type_bound),
        decorators=tuple(_rewrite_decorator(d, mapping, type_bound) for d in func.decorators),
    )


def _rewrite_block(
    block: ast.BlockStmt,
    mapping: dict[str, str],
    bound: set[str],
    type_bound: set[str],
) -> ast.BlockStmt:
    current_bound = set(bound)
    statements: list[ast.Stmt] = []
    for stmt in block.statements:
        statements.append(_rewrite_stmt(stmt, mapping, current_bound, type_bound))
        current_bound.update(_declared_names(stmt))
    return replace(block, statements=tuple(statements))


def _declared_names(stmt: ast.Stmt) -> set[str]:
    if isinstance(stmt, ast.VarDecl):
        return {stmt.name}
    if isinstance(stmt, ast.DestructureAssignStmt | ast.DestructureDeclStmt):
        return set(stmt.targets)
    if (
        isinstance(stmt, ast.ExprStmt)
        and isinstance(stmt.expr, ast.AssignExpr)
        and isinstance(stmt.expr.target, ast.Identifier)
    ):
        return {stmt.expr.target.name}
    return set()


def _rewrite_stmt(
    stmt: ast.Stmt,
    mapping: dict[str, str],
    bound: set[str],
    type_bound: set[str],
) -> ast.Stmt:
    if isinstance(stmt, ast.ExprStmt):
        return replace(stmt, expr=_rewrite_expr(stmt.expr, mapping, bound, type_bound))
    if isinstance(stmt, ast.VarDecl):
        init = (
            _rewrite_expr(stmt.initializer, mapping, bound, type_bound)
            if stmt.initializer
            else None
        )
        return replace(
            stmt,
            type_annotation=_rewrite_type_name(stmt.type_annotation, mapping, type_bound),
            initializer=init,
        )
    if isinstance(stmt, ast.ReturnStmt):
        value = _rewrite_expr(stmt.value, mapping, bound, type_bound) if stmt.value else None
        return replace(stmt, value=value)
    if isinstance(stmt, ast.BlockStmt):
        return _rewrite_block(stmt, mapping, bound, type_bound)
    if isinstance(stmt, ast.IfStmt):
        return replace(
            stmt,
            condition=_rewrite_expr(stmt.condition, mapping, bound, type_bound),
            then_branch=_rewrite_block(stmt.then_branch, mapping, bound, type_bound),
            elif_branches=tuple(
                (
                    _rewrite_expr(cond, mapping, bound, type_bound),
                    _rewrite_block(body, mapping, bound, type_bound),
                )
                for cond, body in stmt.elif_branches
            ),
            else_branch=(
                _rewrite_block(stmt.else_branch, mapping, bound, type_bound)
                if stmt.else_branch
                else None
            ),
        )
    if isinstance(stmt, ast.LoopStmt):
        return replace(stmt, body=_rewrite_block(stmt.body, mapping, bound, type_bound))
    if isinstance(stmt, ast.WhileStmt):
        return replace(
            stmt,
            condition=_rewrite_expr(stmt.condition, mapping, bound, type_bound),
            body=_rewrite_block(stmt.body, mapping, bound, type_bound),
        )
    if isinstance(stmt, ast.ForInStmt):
        return replace(
            stmt,
            iterable=_rewrite_expr(stmt.iterable, mapping, bound, type_bound),
            body=_rewrite_block(stmt.body, mapping, {*bound, stmt.var_name}, type_bound),
        )
    if isinstance(stmt, ast.ThrowStmt):
        return replace(stmt, value=_rewrite_expr(stmt.value, mapping, bound, type_bound))
    if isinstance(stmt, ast.TryCatchStmt):
        catch_bound = {*bound, stmt.catch_var} if stmt.catch_var else bound
        return replace(
            stmt,
            try_body=_rewrite_block(stmt.try_body, mapping, bound, type_bound),
            catch_body=(
                _rewrite_block(stmt.catch_body, mapping, catch_bound, type_bound)
                if stmt.catch_body
                else None
            ),
            finally_body=(
                _rewrite_block(stmt.finally_body, mapping, bound, type_bound)
                if stmt.finally_body
                else None
            ),
        )
    if isinstance(stmt, ast.DestructureAssignStmt | ast.DestructureDeclStmt):
        return replace(stmt, value=_rewrite_expr(stmt.value, mapping, bound, type_bound))
    return stmt


def _rewrite_expr(
    expr: ast.Expr | None,
    mapping: dict[str, str],
    bound: set[str],
    type_bound: set[str],
) -> ast.Expr:
    if expr is None:
        raise ValueError("cannot rewrite missing expression")
    if isinstance(expr, ast.Identifier):
        if expr.name in mapping and expr.name not in bound:
            return replace(expr, name=mapping[expr.name])
        return expr
    if isinstance(expr, ast.OuterIdentifier):
        if expr.name in mapping and expr.name not in bound:
            return replace(expr, name=mapping[expr.name])
        return expr
    if isinstance(
        expr,
        ast.IntLiteral
        | ast.FloatLiteral
        | ast.StrLiteral
        | ast.BoolLiteral
        | ast.NullLiteral
        | ast.ThisExpr
        | ast.ItExpr,
    ):
        return expr
    if isinstance(expr, ast.UnaryExpr):
        return replace(expr, operand=_rewrite_expr(expr.operand, mapping, bound, type_bound))
    if isinstance(expr, ast.BinaryExpr):
        return replace(
            expr,
            left=_rewrite_expr(expr.left, mapping, bound, type_bound),
            right=_rewrite_expr(expr.right, mapping, bound, type_bound),
        )
    if isinstance(expr, ast.AssignExpr):
        return replace(
            expr,
            target=_rewrite_assignment_target(expr.target, mapping, bound, type_bound),
            value=_rewrite_expr(expr.value, mapping, bound, type_bound),
        )
    if isinstance(expr, ast.CompoundAssignExpr):
        return replace(
            expr,
            target=_rewrite_assignment_target(expr.target, mapping, bound, type_bound),
            value=_rewrite_expr(expr.value, mapping, bound, type_bound),
        )
    if isinstance(expr, ast.IncrementExpr):
        return replace(
            expr, target=_rewrite_assignment_target(expr.target, mapping, bound, type_bound)
        )
    if isinstance(expr, ast.CallExpr):
        return replace(
            expr,
            callee=_rewrite_expr(expr.callee, mapping, bound, type_bound),
            args=tuple(_rewrite_expr(arg, mapping, bound, type_bound) for arg in expr.args),
        )
    if isinstance(expr, ast.MemberExpr):
        return replace(expr, obj=_rewrite_expr(expr.obj, mapping, bound, type_bound))
    if isinstance(expr, ast.IndexExpr):
        return replace(
            expr,
            obj=_rewrite_expr(expr.obj, mapping, bound, type_bound),
            index=_rewrite_expr(expr.index, mapping, bound, type_bound),
        )
    if isinstance(expr, ast.SliceExpr):
        return replace(
            expr,
            obj=_rewrite_expr(expr.obj, mapping, bound, type_bound),
            start=_rewrite_expr(expr.start, mapping, bound, type_bound) if expr.start else None,
            end=_rewrite_expr(expr.end, mapping, bound, type_bound) if expr.end else None,
        )
    if isinstance(expr, ast.ListExpr):
        return replace(
            expr,
            elements=tuple(
                _rewrite_expr(elem, mapping, bound, type_bound) for elem in expr.elements
            ),
        )
    if isinstance(expr, ast.TupleExpr):
        return replace(
            expr,
            elements=tuple(
                _rewrite_expr(elem, mapping, bound, type_bound) for elem in expr.elements
            ),
        )
    if isinstance(expr, ast.OkExpr | ast.ErrExpr):
        return replace(expr, value=_rewrite_expr(expr.value, mapping, bound, type_bound))
    if isinstance(expr, ast.LambdaExpr):
        lambda_type_bound = set(type_bound)
        params = []
        for name, type_annotation in expr.params:
            params.append((name, _rewrite_type_name(type_annotation, mapping, lambda_type_bound)))
        lambda_bound = {*bound, *(name for name, _ in params)}
        body = (
            _rewrite_block(expr.body, mapping, lambda_bound, lambda_type_bound)
            if isinstance(expr.body, ast.BlockStmt)
            else _rewrite_expr(expr.body, mapping, lambda_bound, lambda_type_bound)
        )
        return replace(
            expr,
            params=tuple(params),
            return_type=_rewrite_type_name(expr.return_type, mapping, lambda_type_bound),
            body=body,
        )
    if isinstance(expr, ast.ElvExpr | ast.NullCoalesceExpr):
        return replace(
            expr,
            left=_rewrite_expr(expr.left, mapping, bound, type_bound),
            right=_rewrite_expr(expr.right, mapping, bound, type_bound),
        )
    if isinstance(expr, ast.PropagateExpr):
        return replace(expr, value=_rewrite_expr(expr.value, mapping, bound, type_bound))
    if isinstance(expr, ast.SafeCallExpr):
        return replace(
            expr,
            obj=_rewrite_expr(expr.obj, mapping, bound, type_bound),
            args=tuple(_rewrite_expr(arg, mapping, bound, type_bound) for arg in expr.args),
        )
    if isinstance(expr, ast.SafeMemberExpr):
        return replace(expr, obj=_rewrite_expr(expr.obj, mapping, bound, type_bound))
    if isinstance(expr, ast.PatternMatchExpr):
        arms = []
        for arm in expr.arms:
            arm_bound = {*bound, arm.binding or "it"}
            body = (
                _rewrite_block(arm.body, mapping, arm_bound, type_bound)
                if isinstance(arm.body, ast.BlockStmt)
                else _rewrite_expr(arm.body, mapping, arm_bound, type_bound)
            )
            arms.append(
                replace(
                    arm,
                    pattern=_rewrite_match_pattern(arm.pattern, mapping, type_bound),
                    body=body,
                )
            )
        return replace(
            expr,
            scrutinee=_rewrite_expr(expr.scrutinee, mapping, bound, type_bound),
            arms=tuple(arms),
        )
    if isinstance(expr, ast.IfExpr):
        return replace(
            expr,
            condition=_rewrite_expr(expr.condition, mapping, bound, type_bound),
            then_branch=_rewrite_block(expr.then_branch, mapping, bound, type_bound),
            elif_branches=tuple(
                (
                    _rewrite_expr(cond, mapping, bound, type_bound),
                    _rewrite_block(body, mapping, bound, type_bound),
                )
                for cond, body in expr.elif_branches
            ),
            else_branch=(
                _rewrite_block(expr.else_branch, mapping, bound, type_bound)
                if expr.else_branch
                else None
            ),
        )
    if isinstance(expr, ast.RangeExpr):
        return replace(
            expr,
            start=_rewrite_expr(expr.start, mapping, bound, type_bound),
            end=_rewrite_expr(expr.end, mapping, bound, type_bound),
        )
    return expr


def _rewrite_assignment_target(
    target: ast.Expr,
    mapping: dict[str, str],
    bound: set[str],
    type_bound: set[str],
) -> ast.Expr:
    if isinstance(target, ast.Identifier):
        return target
    if isinstance(target, ast.OuterIdentifier):
        if target.name in mapping and target.name not in bound:
            return replace(target, name=mapping[target.name])
        return target
    if isinstance(target, ast.MemberExpr):
        return replace(target, obj=_rewrite_expr(target.obj, mapping, bound, type_bound))
    if isinstance(target, ast.IndexExpr):
        return replace(
            target,
            obj=_rewrite_expr(target.obj, mapping, bound, type_bound),
            index=_rewrite_expr(target.index, mapping, bound, type_bound),
        )
    return _rewrite_expr(target, mapping, bound, type_bound)


def _rewrite_match_pattern(
    pattern: ast.MatchPattern, mapping: dict[str, str], type_bound: set[str]
) -> ast.MatchPattern:
    if pattern.kind == "enum" and isinstance(pattern.value, str):
        enum_name, variant = pattern.value.split(".", 1)
        return replace(pattern, value=f"{mapping.get(enum_name, enum_name)}.{variant}")
    if pattern.kind == "type" and isinstance(pattern.value, str):
        return replace(pattern, value=_rewrite_type_name(pattern.value, mapping, type_bound))
    if pattern.kind == "literal" and not isinstance(pattern.value, ast.Identifier):
        return replace(
            pattern,
            value=_rewrite_expr(pattern.value, mapping, set(), type_bound),  # type: ignore[arg-type]
        )
    return pattern
