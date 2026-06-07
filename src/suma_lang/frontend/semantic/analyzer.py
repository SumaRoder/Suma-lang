from __future__ import annotations

from collections.abc import Sequence

from suma_lang.frontend.lexer.token_types import TokenInfo
from suma_lang.frontend.parser.ast_nodes import (
    BlockStmt,
    BreakStmt,
    ClassDecl,
    ContinueStmt,
    Decorator,
    DestructureAssignStmt,
    DestructureDeclStmt,
    EnumDecl,
    Expr,
    ExprStmt,
    ForInStmt,
    FunctionDecl,
    GetterDecl,
    Identifier,
    IfStmt,
    LoopStmt,
    Param,
    Program,
    ReturnStmt,
    SetterDecl,
    Stmt,
    ThrowStmt,
    TopLevel,
    TryCatchStmt,
    VarDecl,
    WhileStmt,
)
from suma_lang.frontend.semantic.flow_analyzer import FlowAnalyzer
from suma_lang.frontend.semantic.scope_resolver import ScopeResolver, format_location
from suma_lang.frontend.semantic.symbol_table import Scope, Symbol
from suma_lang.frontend.semantic.type_inferrer import TypeInferrer
from suma_lang.frontend.semantic.type_registry import TypeRegistry
from suma_lang.frontend.semantic.types import (
    base_type,
    erase_type,
    split_type_args,
)


class AnalysisError(Exception):
    pass


class Analyzer:
    """Semantic analyzer: scope resolution, basic type checks, arity checks."""

    BUILTINS = {
        "print": ("func", None, -1),
        "to_str": ("func", "Str", 1),
        "to_int": ("func", "Int", 1),
        "to_float": ("func", "Float", 1),
        "to_bool": ("func", "Bool", 1),
        "List": ("func", "List", -1),  # variadic, type constructor
        "Ok": ("func", None, 1),  # type constructor
        "Err": ("func", None, 1),  # type constructor
        "parse_int": ("func", "R<Int,Str>", 1),
        "is_ok": ("func", "Bool", 1),
        "is_err": ("func", "Bool", 1),
        "unwrap": ("func", None, 1),
        "unwrap_or": ("func", None, 2),
        "panic": ("func", None, 1),
        "assert": ("func", None, -1),
        "len": ("func", "Int", 1),
        "type_of": ("func", "Str", 1),
        "__suma_is_type": ("func", "Bool", 2),
    }

    def __init__(self, *, strict_shadowing: bool = False) -> None:
        self.errors: list[str] = []
        # Non-fatal diagnostics surfaced to callers via Analyzer.warnings or
        # Diagnostic(level="warning") on the api.py side. Warnings never block
        # compilation; they exist so embedders/LSPs can render them.
        self.warnings: list[str] = []
        # When strict_shadowing is enabled, the implicit-shadow warning becomes
        # an error instead. The flag is opt-in so existing programs keep
        # compiling; see docs/language.md on assignment-and-scoping.
        self._strict_shadowing = strict_shadowing
        self._scopes = ScopeResolver()
        self._registry = TypeRegistry()
        self._flow = FlowAnalyzer(self)
        self._type_inferrer = TypeInferrer(self)
        self.current_class: str | None = None
        self.current_function: FunctionDecl | None = None

    @property
    def global_scope(self) -> Scope:
        return self._scopes.global_scope

    @property
    def current_scope(self) -> Scope:
        return self._scopes.current_scope

    def __getattr__(self, name: str):
        # Helper methods are owned by subcomponents. Keeping delegation in one
        # place lets older call sites use the historical method names while the
        # implementation lives in the responsible component.
        for attr in ("_type_inferrer", "_flow"):
            try:
                component = object.__getattribute__(self, attr)
            except AttributeError:
                continue
            if any(name in cls.__dict__ for cls in type(component).__mro__):
                return getattr(component, name)
        try:
            registry = object.__getattribute__(self, "_registry")
        except AttributeError:
            pass
        else:
            try:
                return getattr(registry, name)
            except AttributeError:
                pass
        raise AttributeError(name)

    @property
    def _class_decls(self) -> dict[str, ClassDecl]:
        return self._registry.class_decls

    @property
    def _class_fields(self) -> dict[str, dict[str, VarDecl]]:
        return self._registry.class_fields

    @property
    def _class_field_types(self) -> dict[str, dict[str, str | None]]:
        return self._registry.class_field_types

    @property
    def _class_methods(self) -> dict[str, dict[str, FunctionDecl]]:
        return self._registry.class_methods

    @property
    def _class_getters(self) -> dict[str, dict[str, FunctionDecl]]:
        return self._registry.class_getters

    @property
    def _class_setters(self) -> dict[str, dict[str, FunctionDecl]]:
        return self._registry.class_setters

    @property
    def _enum_decls(self) -> dict[str, EnumDecl]:
        return self._registry.enum_decls

    @property
    def _enum_variants(self) -> dict[str, dict[str, str | None]]:
        return self._registry.enum_variants

    @property
    def _function_overloads(self) -> dict[str, list[FunctionDecl]]:
        return self._registry.function_overloads

    @property
    def _class_method_overloads(self) -> dict[str, dict[str, list[FunctionDecl]]]:
        return self._registry.class_method_overloads

    @property
    def _class_chain_cache(self) -> dict[str | None, tuple[str, ...]]:
        return self._registry.class_chain_cache

    @property
    def _project_type_cache(self) -> dict[tuple[str | None, str | None], str | None]:
        return self._registry.project_type_cache

    @property
    def _method_candidate_cache(
        self,
    ) -> dict[tuple[str | None, str], tuple[tuple[str, FunctionDecl], ...]]:
        return self._registry.method_candidate_cache

    @property
    def _field_candidate_cache(self) -> dict[tuple[str | None, str], tuple[str, VarDecl] | None]:
        return self._registry.field_candidate_cache

    @property
    def _getter_candidate_cache(
        self,
    ) -> dict[tuple[str | None, str], tuple[str, FunctionDecl] | None]:
        return self._registry.getter_candidate_cache

    @property
    def _setter_candidate_cache(
        self,
    ) -> dict[tuple[str | None, str], tuple[str, FunctionDecl] | None]:
        return self._registry.setter_candidate_cache

    @property
    def _assignable_cache(self) -> dict[tuple[str | None, str | None], bool]:
        return self._registry.assignable_cache

    @property
    def _loop_depth(self) -> int:
        return self._flow.loop_depth

    @_loop_depth.setter
    def _loop_depth(self, value: int) -> None:
        self._flow.loop_depth = value

    @property
    def _narrowed_types(self) -> list[dict[int, str | None]]:
        return self._flow.narrowed_types

    @_narrowed_types.setter
    def _narrowed_types(self, value: list[dict[int, str | None]]) -> None:
        self._flow.narrowed_types = value

    def _clear_query_caches(self) -> None:
        self._registry.clear_query_caches()

    def _next_slot(self) -> int:
        return self._scopes.next_slot()

    def _error(self, msg: str, info: TokenInfo | None = None) -> None:
        self.errors.append(f"{format_location(info)}{msg}")

    def _warn(self, msg: str, info: TokenInfo | None = None) -> None:
        self.warnings.append(f"{format_location(info)}{msg}")

    def _push_scope(self, scope_type: str = "block", class_name: str | None = None) -> Scope:
        return self._scopes.push(scope_type, class_name)

    def _pop_scope(self) -> None:
        self._scopes.pop()

    def _resolve_outer(self, name: str) -> Symbol | None:
        return self._scopes.resolve_outer(name)

    def _check_implicit_shadow(self, name: str, info: TokenInfo | None) -> None:
        # Only flag when the assignment occurs in a non-top scope and the
        # outer binding is a `var`/`param`. Class members, globals defined in
        # the function-entry scope, and function-local top-level bindings are
        # intentionally allowed to be re-declared/shadowed without noise.
        outer = self._scopes.implicit_shadow_target(name)
        if outer is None:
            return
        msg = (
            f"'{name}' shadows outer binding; write '@{name} = ...' to update "
            f"it, or '{name}: T = ...' to make the new local explicit"
        )
        if self._strict_shadowing:
            self._error(msg, info)
        else:
            self._warn(msg, info)

    def _getter_function(self, member: GetterDecl) -> FunctionDecl:
        return FunctionDecl(
            name=f"get_{member.name}",
            params=[],
            return_type=member.return_type,
            body=member.body,
            is_pub=member.is_pub,
            is_static=False,
            info=member.info,
        )

    def _setter_function(self, member: SetterDecl) -> FunctionDecl:
        return FunctionDecl(
            name=f"set_{member.name}",
            params=[
                Param(
                    name=member.param_name,
                    type_annotation=member.param_type,
                    default=None,
                    is_optional=False,
                )
            ],
            return_type=None,
            body=member.body,
            is_pub=member.is_pub,
            is_static=False,
            info=member.info,
        )

    def _erased_signature(self, func: FunctionDecl) -> tuple[str | None, ...]:
        return tuple(erase_type(param.type_annotation) for param in func.params)

    def _validate_overload_set(self, owner: str, funcs: Sequence[FunctionDecl]) -> None:
        if len(funcs) <= 1:
            return
        signatures: dict[tuple[int, tuple[str | None, ...]], FunctionDecl] = {}
        for func in funcs:
            if func.decorators:
                self._error(f"Overloaded function '{owner}' cannot use decorators", func.info)
            for param in func.params:
                if param.default is not None:
                    self._error(
                        f"Overloaded function '{owner}' cannot use default parameters",
                        func.info,
                    )
                    break
            signature = (len(func.params), self._erased_signature(func))
            if signature in signatures:
                self._error(
                    f"Duplicate overload for '{owner}' with erased signature {signature[1]}",
                    func.info,
                )
            signatures[signature] = func

    def _validate_overloads(self) -> None:
        for name, funcs in self._function_overloads.items():
            self._validate_overload_set(name, funcs)
        for class_name, methods in self._class_method_overloads.items():
            for name, funcs in methods.items():
                if name == "init" and len(funcs) > 1:
                    self._error(
                        f"Class '{class_name}' cannot overload init constructors yet", funcs[1].info
                    )
                self._validate_overload_set(f"{class_name}.{name}", funcs)

    def _validate_inheritance(self) -> None:
        for class_name, cls in self._class_decls.items():
            if cls.base_type is None:
                continue
            base_name = base_type(cls.base_type)
            base_cls = self._class_decls.get(base_name or "")
            if base_name is None or base_cls is None:
                self._error(f"Unknown base class '{cls.base_type}' for '{class_name}'", cls.info)
                continue
            if base_name == class_name:
                self._error(f"Class '{class_name}' cannot inherit from itself", cls.info)
                continue
            base_args = split_type_args(cls.base_type)
            if base_cls.type_params and len(base_args) != len(base_cls.type_params):
                self._error(
                    f"Base class '{base_name}' expects {len(base_cls.type_params)} type arguments, "
                    f"got {len(base_args)}",
                    cls.info,
                )
            if not base_cls.type_params and base_args:
                self._error(f"Class '{base_name}' is not generic", cls.info)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(class_name: str, path: list[str]) -> None:
            if class_name in visited:
                return
            if class_name in visiting:
                cycle = " -> ".join([*path, class_name])
                self._error(
                    f"Inheritance cycle detected: {cycle}", self._class_decls[class_name].info
                )
                return
            visiting.add(class_name)
            base_name = self._base_class_name(class_name)
            if base_name in self._class_decls:
                visit(base_name, [*path, class_name])
            visiting.remove(class_name)
            visited.add(class_name)

        for class_name in self._class_decls:
            visit(class_name, [])

        for class_name, cls in self._class_decls.items():
            inherited_fields: set[str] = set()
            for base_name in self._class_chain(self._base_class_name(class_name)):
                inherited_fields.update(self._class_fields.get(base_name, {}))
            for member in cls.members:
                if isinstance(member, VarDecl) and member.name in inherited_fields:
                    self._error(
                        f"Field '{member.name}' in '{class_name}' conflicts with inherited field",
                        member.info,
                    )

            inherited_methods: dict[
                tuple[str, tuple[int, tuple[str | None, ...]]], FunctionDecl
            ] = {}
            for base_name in self._class_chain(self._base_class_name(class_name)):
                for method_name, methods in self._class_method_overloads.get(base_name, {}).items():
                    if method_name == "init":
                        continue
                    for method in methods:
                        bound = self._bind_method_to_object(class_name, base_name, method)
                        inherited_methods.setdefault(
                            (method_name, self._method_signature(bound)), bound
                        )
            for member in cls.members:
                if not isinstance(member, FunctionDecl) or member.name == "init":
                    continue
                inherited = inherited_methods.get((member.name, self._method_signature(member)))
                if inherited is None:
                    continue
                if inherited.is_pub and not member.is_pub:
                    self._error(
                        f"Method '{class_name}.{member.name}' cannot reduce inherited visibility",
                        member.info,
                    )
                if not self._is_assignable(inherited.return_type, member.return_type):
                    self._error(
                        f"Method '{class_name}.{member.name}' return type {member.return_type} "
                        f"is not compatible with inherited return type {inherited.return_type}",
                        member.info,
                    )

    # public API
    def analyze(self, program: Program) -> list[str]:
        for alias, module_name in program.py_imports.items():
            err = self.global_scope.define(
                Symbol(
                    name=alias,
                    type_name="PyModule",
                    kind="py_module",
                    decl=module_name,
                    is_pub=True,
                    index=self._next_slot(),
                )
            )
            if err:
                self._error(err)

        for decl in program.declarations:
            self._register_toplevel(decl)

        self._clear_query_caches()
        self._validate_inheritance()
        self._validate_overloads()
        self._validate_entrypoint()

        for decl in program.declarations:
            self._analyze_toplevel(decl)

        return self.errors

    def _validate_entrypoint(self) -> None:
        main = self.global_scope.resolve_local("main")
        if main is None:
            self._error("Program must define main()")
            return
        if not isinstance(main.decl, FunctionDecl):
            self._error("Program entrypoint 'main' must be a function")
            return
        if main.decl.params:
            self._error("Program entrypoint 'main' must not take parameters", main.decl.info)
        if main.decl.return_type != "Int":
            self._error("Program entrypoint 'main' must return Int", main.decl.info)

    def _register_toplevel(self, decl: TopLevel) -> None:
        if isinstance(decl, FunctionDecl):
            overloads = self._function_overloads.setdefault(decl.name, [])
            overloads.append(decl)
            existing = self.global_scope.resolve_local(decl.name)
            if existing is not None:
                if existing.kind != "func":
                    self._error(f"'{decl.name}' is already defined in this scope", decl.info)
                return
            sym = Symbol(
                name=decl.name,
                type_name=decl.return_type,
                kind="func",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        elif isinstance(decl, ClassDecl):
            self._class_decls[decl.name] = decl
            self._class_fields[decl.name] = {
                member.name: member for member in decl.members if isinstance(member, VarDecl)
            }
            self._class_field_types[decl.name] = {
                member.name: member.type_annotation
                for member in decl.members
                if isinstance(member, VarDecl)
            }
            method_overloads: dict[str, list[FunctionDecl]] = {}
            getters: dict[str, FunctionDecl] = {}
            setters: dict[str, FunctionDecl] = {}
            for member in decl.members:
                if isinstance(member, FunctionDecl):
                    method_overloads.setdefault(member.name, []).append(member)
                elif isinstance(member, GetterDecl):
                    getters[member.name] = self._getter_function(member)
                elif isinstance(member, SetterDecl):
                    setters[member.name] = self._setter_function(member)
            self._class_method_overloads[decl.name] = method_overloads
            self._class_methods[decl.name] = {
                name: funcs[0] for name, funcs in method_overloads.items() if len(funcs) == 1
            }
            self._class_getters[decl.name] = getters
            self._class_setters[decl.name] = setters
            sym = Symbol(
                name=decl.name,
                type_name=decl.name,
                kind="class",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        elif isinstance(decl, EnumDecl):
            self._enum_decls[decl.name] = decl
            variants: dict[str, str | None] = {}
            for variant in decl.variants:
                if variant.name in variants:
                    self._error(
                        f"Duplicate variant '{variant.name}' in enum '{decl.name}'",
                        variant.info,
                    )
                variants[variant.name] = variant.payload_type
            self._enum_variants[decl.name] = variants
            sym = Symbol(
                name=decl.name,
                type_name=decl.name,
                kind="enum",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        elif isinstance(decl, VarDecl):
            sym = Symbol(
                name=decl.name,
                type_name=decl.type_annotation,
                kind="var",
                decl=decl,
                is_pub=decl.is_pub,
                index=self._next_slot(),
            )
            err = self.global_scope.define(sym)
            if err:
                self._error(err, decl.info)
        # ImportDecl: skip for now, future will complete

    def _analyze_toplevel(self, decl: TopLevel) -> None:
        if isinstance(decl, FunctionDecl):
            self._analyze_decorators(decl.decorators, self._function_value_type(decl))
            self._analyze_function(decl)
        elif isinstance(decl, ClassDecl):
            self._analyze_decorators(decl.decorators, self._constructor_value_type(decl))
            self._analyze_class(decl)
        elif isinstance(decl, VarDecl) and decl.initializer:
            init_type = self._infer_expr(decl.initializer)
            type_name = self._resolve_decl_type(decl.type_annotation, init_type)
            self._check_assignable(
                type_name, init_type, decl.info, f"Cannot assign {init_type} to '{decl.name}'"
            )
            sym = self.global_scope.resolve_local(decl.name)
            if sym:
                sym.type_name = type_name

    def _validate_class_accessors(self, cls: ClassDecl) -> None:
        fields = {member.name: member for member in cls.members if isinstance(member, VarDecl)}
        methods = {
            member.name: member for member in cls.members if isinstance(member, FunctionDecl)
        }
        getter_types: dict[str, str | None] = {}
        setter_types: dict[str, str | None] = {}
        getter_decls: dict[str, GetterDecl] = {}
        setter_decls: dict[str, SetterDecl] = {}

        for member in cls.members:
            if isinstance(member, GetterDecl):
                if member.name in getter_decls:
                    self._error(f"Duplicate getter for '{member.name}'", member.info)
                getter_types[member.name] = member.return_type
                getter_decls[member.name] = member
                internal_name = f"get_{member.name}"
            elif isinstance(member, SetterDecl):
                if member.name in setter_decls:
                    self._error(f"Duplicate setter for '{member.name}'", member.info)
                setter_types[member.name] = member.param_type
                setter_decls[member.name] = member
                internal_name = f"set_{member.name}"
            else:
                continue
            if member.name in fields:
                self._error(
                    f"Accessor '{member.name}' conflicts with field '{member.name}'", member.info
                )
            if member.name in methods:
                self._error(
                    f"Accessor '{member.name}' conflicts with method '{member.name}'", member.info
                )
            if internal_name in methods:
                self._error(
                    f"Accessor '{member.name}' conflicts with method '{internal_name}'", member.info
                )

        for name, getter_type in getter_types.items():
            setter_type = setter_types.get(name)
            if setter_type is not None and not (
                self._is_assignable(getter_type, setter_type)
                and self._is_assignable(setter_type, getter_type)
            ):
                self._error(
                    f"Setter '{name}' parameter type {setter_type} is not compatible "
                    f"with getter return type {getter_type}",
                    cls.info,
                )

    def _analyze_class(self, cls: ClassDecl) -> None:
        prev_class = self.current_class
        self.current_class = cls.name
        self._validate_class_accessors(cls)
        scope = self._push_scope("class", cls.name)

        for member in cls.members:
            if isinstance(member, VarDecl):
                sym = Symbol(
                    name=member.name,
                    type_name=member.type_annotation,
                    kind="var",
                    decl=member,
                    is_pub=member.is_pub,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)
            elif isinstance(member, FunctionDecl):
                existing = scope.resolve_local(member.name)
                if existing is not None and existing.kind == "func":
                    continue
                sym = Symbol(
                    name=member.name,
                    type_name=member.return_type,
                    kind="func",
                    decl=member,
                    is_pub=member.is_pub,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)
            elif isinstance(member, GetterDecl):
                sym = Symbol(
                    name=member.name,
                    type_name=member.return_type,
                    kind="var",
                    decl=member,
                    is_pub=member.is_pub,
                )
                err = scope.define(sym)
                if err:
                    self._error(err, member.info)

        for member in cls.members:
            if isinstance(member, FunctionDecl):
                self._analyze_decorators(member.decorators, self._function_value_type(member))
                self._analyze_function(member, is_method=True)
            elif isinstance(member, GetterDecl):
                func = self._class_getters[cls.name][member.name]
                self._analyze_function(func, is_method=True)
            elif isinstance(member, SetterDecl):
                func = self._class_setters[cls.name][member.name]
                self._analyze_function(func, is_method=True)
            elif isinstance(member, VarDecl) and member.initializer:
                init_type = self._infer_expr(member.initializer)
                type_name = self._resolve_decl_type(member.type_annotation, init_type)
                self._class_field_types[cls.name][member.name] = type_name
                field_sym = scope.resolve_local(member.name)
                if field_sym:
                    field_sym.type_name = type_name
                self._check_assignable(
                    type_name,
                    init_type,
                    member.info,
                    f"Cannot assign {init_type} to field '{member.name}'",
                )

        self._pop_scope()
        self.current_class = prev_class

    def _analyze_decorators(self, decorators: Sequence[Decorator], target_type: str | None) -> None:
        decorated_type = target_type
        for decorator in reversed(decorators):
            decorator_type = self._infer_decorator_expr_type(decorator.expr)
            if (
                decorator_type not in (None, "PyObject", "PyCallable")
                and base_type(decorator_type) != "Function"
            ):
                self._error(
                    f"Decorator expression must be callable, got {decorator_type}", decorator.info
                )
                continue
            next_type = self._apply_decorator_type(decorator_type, decorated_type, decorator.info)
            if next_type is not None:
                decorated_type = next_type
        if decorators and not self._is_assignable(target_type, decorated_type):
            self._error(
                f"Decorator chain returns {decorated_type}, expected {target_type}",
                decorators[0].info,
            )

    def _function_value_type(self, func: FunctionDecl) -> str:
        arg_types = [param.type_annotation or "Any" for param in func.params]
        return_type = func.return_type or "Null"
        return f"Function<{','.join([*arg_types, return_type])}>"

    def _infer_decorator_expr_type(self, expr: Expr) -> str | None:
        if isinstance(expr, Identifier):
            sym = self.current_scope.resolve(expr.name)
            if sym and sym.kind == "func" and isinstance(sym.decl, FunctionDecl):
                overloads = self._function_overloads.get(expr.name, [sym.decl])
                if len(overloads) == 1:
                    return self._function_value_type(overloads[0])
        return self._infer_expr(expr)

    def _constructor_value_type(self, cls: ClassDecl) -> str:
        init = next(
            (
                member
                for member in cls.members
                if isinstance(member, FunctionDecl) and member.name == "init"
            ),
            None,
        )
        params = init.params if init is not None else ()
        arg_types = [param.type_annotation or "Any" for param in params]
        return_type = cls.name
        if cls.type_params:
            return_type = f"{cls.name}<{','.join(cls.type_params)}>"
        return f"Function<{','.join([*arg_types, return_type])}>"

    def _current_class_instance_type(self) -> str | None:
        if self.current_class is None:
            return None
        cls = self._class_decls.get(self.current_class)
        if cls is None or not cls.type_params:
            return self.current_class
        return f"{cls.name}<{','.join(cls.type_params)}>"

    def _apply_decorator_type(
        self, decorator_type: str | None, target_type: str | None, info: TokenInfo
    ) -> str | None:
        if decorator_type in (None, "PyObject", "PyCallable", "Function"):
            return target_type
        if base_type(decorator_type) != "Function":
            return target_type
        args = split_type_args(decorator_type)
        if not args:
            return target_type
        if len(args) != 2:
            self._error(
                f"Decorator callable must accept one function value, got {len(args) - 1} parameters",
                info,
            )
            return target_type
        expected_target, replacement_type = args
        if not self._is_assignable(expected_target, target_type):
            self._error(
                f"Decorator expects {expected_target}, got {target_type}",
                info,
            )
        if base_type(replacement_type) != "Function":
            self._error(f"Decorator must return Function, got {replacement_type}", info)
            return target_type
        return replacement_type

    def _analyze_function(self, func: FunctionDecl, is_method: bool = False) -> None:
        prev_func = self.current_function
        self.current_function = func
        scope = self._push_scope("function")

        self._validate_params(func)

        # 'this'
        if is_method:
            sym = Symbol(name="this", type_name=self._current_class_instance_type(), kind="param")
            scope.define(sym)

        for param in func.params:
            sym = Symbol(name=param.name, type_name=param.type_annotation, kind="param")
            err = scope.define(sym)
            if err:
                self._error(err, func.info)
            if param.default:
                default_type = self._infer_expr(param.default)
                self._check_assignable(
                    param.type_annotation,
                    default_type,
                    func.info,
                    f"Default value for parameter '{param.name}' has type {default_type}",
                )

        self._analyze_block(func.body)

        self._pop_scope()
        self.current_function = prev_func

    def _validate_params(self, func: FunctionDecl) -> None:
        seen_default = False
        for param in func.params:
            has_default = param.default is not None
            if seen_default and not has_default:
                self._error(
                    f"Required parameter '{param.name}' cannot follow a parameter with a default value",
                    func.info,
                )
            if has_default:
                seen_default = True

    def _analyze_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, ExprStmt):
            self._infer_expr(stmt.expr)
        elif isinstance(stmt, VarDecl):
            init_type = None
            if stmt.initializer:
                init_type = self._infer_expr(stmt.initializer)
                type_name = self._resolve_decl_type(stmt.type_annotation, init_type)
                self._check_assignable(
                    type_name, init_type, stmt.info, f"Cannot assign {init_type} to '{stmt.name}'"
                )
            else:
                type_name = stmt.type_annotation
            sym = Symbol(
                name=stmt.name,
                type_name=stmt.type_annotation,
                kind="var",
                decl=stmt,
                is_pub=stmt.is_pub,
            )
            sym.type_name = type_name
            err = self.current_scope.define(sym)
            if err:
                self._error(err, stmt.info)
        elif isinstance(stmt, ReturnStmt):
            value_type = self._infer_expr(stmt.value) if stmt.value else "Null"
            if self.current_function and self.current_function.return_type != "Any":
                self._check_assignable(
                    self.current_function.return_type,
                    value_type,
                    stmt.info,
                    f"Function '{self.current_function.name}' returns {value_type}",
                )
        elif isinstance(stmt, BlockStmt):
            self._push_scope()
            for s in stmt.statements:
                self._analyze_stmt(s)
            self._pop_scope()
        elif isinstance(stmt, IfStmt):
            cond_type = self._infer_expr(stmt.condition)
            self._expect_type(cond_type, "Bool", stmt.condition.info, "if condition must be Bool")
            then_narrow, else_narrow = self._condition_narrowings(stmt.condition)
            self._analyze_block(stmt.then_branch, then_narrow)
            pending_else_narrow = else_narrow
            for elif_cond, elif_body in stmt.elif_branches:
                self._push_narrowing(pending_else_narrow)
                try:
                    elif_type = self._infer_expr(elif_cond)
                    self._expect_type(
                        elif_type, "Bool", elif_cond.info, "elif condition must be Bool"
                    )
                    elif_then, elif_else = self._condition_narrowings(elif_cond)
                finally:
                    self._pop_narrowing()
                self._analyze_block(elif_body, {**pending_else_narrow, **elif_then})
                pending_else_narrow = {**pending_else_narrow, **elif_else}
            if stmt.else_branch:
                self._analyze_block(stmt.else_branch, pending_else_narrow)
        elif isinstance(stmt, LoopStmt):
            self._loop_depth += 1
            self._analyze_block(stmt.body)
            self._loop_depth -= 1
        elif isinstance(stmt, WhileStmt):
            cond_type = self._infer_expr(stmt.condition)
            self._expect_type(
                cond_type, "Bool", stmt.condition.info, "while condition must be Bool"
            )
            body_narrow, _ = self._condition_narrowings(stmt.condition)
            self._loop_depth += 1
            self._analyze_block(stmt.body, body_narrow)
            self._loop_depth -= 1
        elif isinstance(stmt, ForInStmt):
            iterable_type = self._infer_expr(stmt.iterable)
            item_type = self._iter_item_type(iterable_type)
            self._loop_depth += 1
            self._push_scope()
            self.current_scope.define(Symbol(name=stmt.var_name, type_name=item_type, kind="var"))
            self._analyze_block(stmt.body)
            self._pop_scope()
            self._loop_depth -= 1
        elif isinstance(stmt, BreakStmt):
            if self._loop_depth == 0:
                self._error("'break' outside of loop", stmt.info)
        elif isinstance(stmt, ContinueStmt):
            if self._loop_depth == 0:
                self._error("'continue' outside of loop", stmt.info)
        elif isinstance(stmt, ThrowStmt):
            self._infer_expr(stmt.value)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_block(stmt.try_body)
            if stmt.catch_body:
                self._push_scope()
                if stmt.catch_var:
                    sym = Symbol(name=stmt.catch_var, type_name=None, kind="var")
                    self.current_scope.define(sym)
                self._analyze_block(stmt.catch_body)
                self._pop_scope()
            if stmt.finally_body:
                self._analyze_block(stmt.finally_body)
        elif isinstance(stmt, DestructureAssignStmt):
            value_type = self._infer_expr(stmt.value)
            element_types = self._destructure_element_types(
                value_type, len(stmt.targets), stmt.info
            )
            for target, item_type in zip(stmt.targets, element_types, strict=False):
                sym = self.current_scope.resolve_local(target)
                if sym is None:
                    err = self.current_scope.define(
                        Symbol(name=target, type_name=item_type, kind="var")
                    )
                    if err:
                        self._error(err, stmt.info)
                else:
                    self._check_assignable(
                        sym.type_name,
                        item_type,
                        stmt.info,
                        f"Cannot assign destructured {item_type} to {sym.type_name}",
                    )
                    self._clear_narrowing(sym)
        elif isinstance(stmt, DestructureDeclStmt):
            value_type = self._infer_expr(stmt.value)
            element_types = self._destructure_element_types(
                value_type, len(stmt.targets), stmt.info
            )
            for target, item_type in zip(stmt.targets, element_types, strict=False):
                err = self.current_scope.define(
                    Symbol(name=target, type_name=item_type, kind="var")
                )
                if err:
                    self._error(err, stmt.info)

    def _analyze_block(
        self, block: BlockStmt, narrowings: dict[int, str | None] | None = None
    ) -> None:
        self._push_scope()
        self._push_narrowing(narrowings)
        try:
            for stmt in block.statements:
                self._analyze_stmt(stmt)
        finally:
            self._pop_narrowing()
            self._pop_scope()
