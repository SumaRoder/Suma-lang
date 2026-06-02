from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from suma_lang.frontend.lexer.token_types import TokenInfo
from suma_lang.frontend.parser.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BlockStmt,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    ClassDecl,
    CompoundAssignExpr,
    ContinueStmt,
    Decorator,
    DestructureAssignStmt,
    ElvExpr,
    ErrExpr,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForInStmt,
    FunctionDecl,
    GetterDecl,
    Identifier,
    IfExpr,
    IfStmt,
    IncrementExpr,
    IndexExpr,
    IntLiteral,
    ItExpr,
    LambdaExpr,
    ListExpr,
    LoopStmt,
    MatchPattern,
    MemberExpr,
    NullCoalesceExpr,
    NullLiteral,
    OkExpr,
    Param,
    PatternMatchExpr,
    Program,
    PropagateExpr,
    RangeExpr,
    ReturnStmt,
    SafeCallExpr,
    SafeMemberExpr,
    SetterDecl,
    SliceExpr,
    Stmt,
    StrLiteral,
    ThisExpr,
    ThrowStmt,
    TopLevel,
    TryCatchStmt,
    UnaryExpr,
    VarDecl,
    WhileStmt,
)
from suma_lang.frontend.semantic.symbol_table import Scope, Symbol
from suma_lang.frontend.semantic.types import (
    base_type,
    erase_type,
    function_arg_types,
    function_return_type,
    lambda_type,
    result_err_type,
    result_ok_type,
    split_type_args,
    substitute_type,
)


class AnalysisError(Exception):
    pass


class Analyzer:
    """Semantic analyzer: scope resolution, basic type checks, arity checks."""

    BUILTINS = {
        "print": ("func", None, 1),
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

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.global_scope = Scope(parent=None, scope_type="global")
        self.current_scope: Scope = self.global_scope
        self.current_class: str | None = None
        self.current_function: FunctionDecl | None = None
        self._slot_counter = 0
        self._class_decls: dict[str, ClassDecl] = {}
        self._class_fields: dict[str, dict[str, VarDecl]] = {}
        self._class_field_types: dict[str, dict[str, str | None]] = {}
        self._class_methods: dict[str, dict[str, FunctionDecl]] = {}
        self._class_getters: dict[str, dict[str, FunctionDecl]] = {}
        self._class_setters: dict[str, dict[str, FunctionDecl]] = {}
        self._function_overloads: dict[str, list[FunctionDecl]] = {}
        self._class_method_overloads: dict[str, dict[str, list[FunctionDecl]]] = {}
        self._loop_depth = 0

    def _next_slot(self) -> int:
        s = self._slot_counter
        self._slot_counter += 1
        return s

    def _error(self, msg: str, info: TokenInfo | None = None) -> None:
        loc = (
            f"{info.file or '<unknown>'}:{info.line}:{info.column}: " if info else "<program>:0:0: "
        )
        self.errors.append(f"{loc}{msg}")

    def _push_scope(self, scope_type: str = "block", class_name: str | None = None) -> Scope:
        self.current_scope = Scope(
            parent=self.current_scope, scope_type=scope_type, class_name=class_name
        )
        return self.current_scope

    def _pop_scope(self) -> None:
        if self.current_scope.parent is not None:
            self.current_scope = self.current_scope.parent

    def _class_type_mapping(self, obj_type: str | None) -> dict[str, str | None]:
        base = base_type(obj_type)
        if base is None:
            return {}
        cls = self._class_decls.get(base)
        if cls is None or not cls.type_params:
            return {}
        args = split_type_args(obj_type)
        return {
            name: args[index] if index < len(args) else None
            for index, name in enumerate(cls.type_params)
        }

    def _base_class_name(self, class_name: str) -> str | None:
        cls = self._class_decls.get(class_name)
        if cls is None or cls.base_type is None:
            return None
        return base_type(cls.base_type)

    def _class_chain(self, class_name: str | None) -> list[str]:
        chain: list[str] = []
        seen: set[str] = set()
        current = class_name
        while current is not None and current not in seen:
            chain.append(current)
            seen.add(current)
            current = self._base_class_name(current)
        return chain

    def _project_type_to_base(self, actual_type: str | None, target_base: str | None) -> str | None:
        if actual_type is None or target_base is None:
            return None
        current_type = actual_type
        seen: set[str] = set()
        while current_type is not None:
            current_base = base_type(current_type)
            if current_base == target_base:
                return current_type
            if current_base is None or current_base in seen:
                return None
            seen.add(current_base)
            cls = self._class_decls.get(current_base)
            if cls is None or cls.base_type is None:
                return None
            current_type = substitute_type(cls.base_type, self._class_type_mapping(current_type))
        return None

    def _class_type_mapping_for(
        self, obj_type: str | None, owner_class: str
    ) -> dict[str, str | None]:
        owner_type = self._project_type_to_base(obj_type, owner_class)
        return self._class_type_mapping(owner_type)

    def _bind_method_to_object(
        self, obj_type: str | None, owner_class: str, method: FunctionDecl
    ) -> FunctionDecl:
        mapping = self._class_type_mapping_for(obj_type, owner_class)
        if not mapping:
            return method
        params = tuple(
            replace(param, type_annotation=substitute_type(param.type_annotation, mapping))
            for param in method.params
        )
        return replace(
            method,
            params=params,
            return_type=substitute_type(method.return_type, mapping),
        )

    def _method_signature(self, func: FunctionDecl) -> tuple[int, tuple[str | None, ...]]:
        return len(func.params), self._erased_signature(func)

    def _class_method_candidates(
        self, obj_type: str | None, method_name: str
    ) -> list[tuple[str, FunctionDecl]]:
        base = base_type(obj_type)
        candidates: list[tuple[str, FunctionDecl]] = []
        seen_signatures: set[tuple[int, tuple[str | None, ...]]] = set()
        for owner_class in self._class_chain(base):
            for method in self._class_method_overloads.get(owner_class, {}).get(method_name, []):
                bound = self._bind_method_to_object(obj_type, owner_class, method)
                signature = self._method_signature(bound)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                candidates.append((owner_class, bound))
        return candidates

    def _class_field_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, VarDecl] | None:
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            field = self._class_fields.get(owner_class, {}).get(member)
            if field is not None:
                return owner_class, field
        return None

    def _class_getter_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, FunctionDecl] | None:
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            getter = self._class_getters.get(owner_class, {}).get(member)
            if getter is not None:
                return owner_class, self._bind_method_to_object(obj_type, owner_class, getter)
        return None

    def _class_setter_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, FunctionDecl] | None:
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            setter = self._class_setters.get(owner_class, {}).get(member)
            if setter is not None:
                return owner_class, self._bind_method_to_object(obj_type, owner_class, setter)
        return None

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
                if param.default is not None or param.is_optional:
                    self._error(
                        f"Overloaded function '{owner}' cannot use optional/default parameters",
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
                        f"Class '{class_name}' cannot overload init constructors yet",
                        funcs[1].info,
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

    def _match_type_pattern(
        self,
        expected: str | None,
        actual: str | None,
        type_params: Sequence[str],
        bindings: dict[str, str | None],
    ) -> bool:
        if expected is None or expected == "Any" or actual is None:
            return True
        if expected in type_params:
            bound = bindings.get(expected)
            if bound is None:
                bindings[expected] = actual
                return True
            return self._is_assignable(bound, actual) or self._is_assignable(actual, bound)
        expected_base = base_type(expected)
        actual_base = base_type(actual)
        if expected_base != actual_base:
            return self._is_assignable(expected, actual)
        expected_args = split_type_args(expected)
        actual_args = split_type_args(actual)
        if not expected_args:
            return self._is_assignable(expected, actual)
        if not actual_args:
            return True
        if len(expected_args) != len(actual_args):
            return False
        return all(
            self._match_type_pattern(exp, act, type_params, bindings)
            for exp, act in zip(expected_args, actual_args, strict=False)
        )

    def _overload_score(
        self,
        func: FunctionDecl,
        arg_types: Sequence[str | None],
        initial_mapping: dict[str, str | None] | None = None,
    ) -> tuple[int, dict[str, str | None]] | None:
        required = sum(
            1 for param in func.params if not param.is_optional and param.default is None
        )
        if len(arg_types) < required or len(arg_types) > len(func.params):
            return None
        bindings = dict(initial_mapping or {})
        score = 0
        for arg_type, param in zip(arg_types, func.params, strict=False):
            expected = substitute_type(param.type_annotation, bindings)
            if not self._match_type_pattern(expected, arg_type, func.type_params, bindings):
                return None
            expected_after = substitute_type(param.type_annotation, bindings)
            if expected_after == arg_type:
                score += 4
            elif erase_type(expected_after) == erase_type(arg_type):
                score += 3
            elif self._is_assignable(expected_after, arg_type):
                score += 2
            else:
                score += 1
        return score, bindings

    def _resolve_overload(
        self,
        name: str,
        funcs: Sequence[FunctionDecl],
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> tuple[FunctionDecl | None, dict[str, str | None], list[str | None]]:
        arg_types = [self._infer_expr(arg) for arg in expr.args]
        matches: list[tuple[int, FunctionDecl, dict[str, str | None]]] = []
        for func in funcs:
            scored = self._overload_score(func, arg_types, initial_mapping)
            if scored is not None:
                score, bindings = scored
                matches.append((score, func, bindings))
        if not matches:
            self._error(f"No overload of '{name}' matches argument types {arg_types}", expr.info)
            return None, {}, arg_types
        matches.sort(key=lambda item: item[0], reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            self._error(f"Ambiguous overload of '{name}' for argument types {arg_types}", expr.info)
            return None, {}, arg_types
        return matches[0][1], matches[0][2], arg_types

    def _infer_function_call(
        self,
        name: str,
        funcs: Sequence[FunctionDecl],
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> str | None:
        if len(funcs) > 1:
            selected, bindings, _ = self._resolve_overload(name, funcs, expr, initial_mapping)
            if selected is None:
                return None
            return substitute_type(selected.return_type, bindings)
        bindings = self._check_function_call(funcs[0], expr, initial_mapping)
        return substitute_type(funcs[0].return_type, bindings)

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
            self._analyze_decorators(decl.decorators)
            self._analyze_function(decl)
        elif isinstance(decl, ClassDecl):
            self._analyze_decorators(decl.decorators)
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
                    f"Accessor '{member.name}' conflicts with field '{member.name}'",
                    member.info,
                )
            if member.name in methods:
                self._error(
                    f"Accessor '{member.name}' conflicts with method '{member.name}'",
                    member.info,
                )
            if internal_name in methods:
                self._error(
                    f"Accessor '{member.name}' conflicts with method '{internal_name}'",
                    member.info,
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
                self._analyze_decorators(member.decorators)
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

    def _analyze_decorators(self, decorators: Sequence[Decorator]) -> None:
        for decorator in decorators:
            decorator_type = self._infer_expr(decorator.expr)
            if decorator_type not in (None, "Function", "PyObject", "PyCallable"):
                self._error(
                    f"Decorator expression must be callable, got {decorator_type}",
                    decorator.info,
                )

    def _analyze_function(self, func: FunctionDecl, is_method: bool = False) -> None:
        prev_func = self.current_function
        self.current_function = func
        scope = self._push_scope("function")

        self._validate_params(func)

        # 'this'
        if is_method:
            sym = Symbol(name="this", type_name=self.current_class, kind="param")
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
        seen_optional = False
        for param in func.params:
            is_optional = param.is_optional or param.default is not None
            if seen_optional and not is_optional:
                self._error(
                    f"Required parameter '{param.name}' cannot follow an optional parameter",
                    func.info,
                )
            if param.is_optional and param.default is None:
                self._error(
                    f"Optional parameter '{param.name}' must provide a default value",
                    func.info,
                )
            if is_optional:
                seen_optional = True

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
            self._analyze_block(stmt.then_branch)
            for elif_cond, elif_body in stmt.elif_branches:
                elif_type = self._infer_expr(elif_cond)
                self._expect_type(elif_type, "Bool", elif_cond.info, "elif condition must be Bool")
                self._analyze_block(elif_body)
            if stmt.else_branch:
                self._analyze_block(stmt.else_branch)
        elif isinstance(stmt, LoopStmt):
            self._loop_depth += 1
            self._analyze_block(stmt.body)
            self._loop_depth -= 1
        elif isinstance(stmt, WhileStmt):
            cond_type = self._infer_expr(stmt.condition)
            self._expect_type(
                cond_type, "Bool", stmt.condition.info, "while condition must be Bool"
            )
            self._loop_depth += 1
            self._analyze_block(stmt.body)
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
            item_type = self._iter_item_type(value_type)
            for target in stmt.targets:
                sym = self.current_scope.resolve(target)
                if sym is None:
                    self.current_scope.define(Symbol(name=target, type_name=item_type, kind="var"))
                else:
                    self._check_assignable(
                        sym.type_name,
                        item_type,
                        stmt.info,
                        f"Cannot assign destructured {item_type} to {sym.type_name}",
                    )

    def _analyze_block(self, block: BlockStmt) -> None:
        self._push_scope()
        for stmt in block.statements:
            self._analyze_stmt(stmt)
        self._pop_scope()

    def _analyze_expr(self, expr: Expr) -> None:
        self._infer_expr(expr)

    def _infer_expr(self, expr: Expr) -> str | None:
        if isinstance(expr, (IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, NullLiteral)):
            return self._literal_type(expr)
        elif isinstance(expr, Identifier):
            sym = self.current_scope.resolve(expr.name)
            if not sym:
                # builtins
                if expr.name not in self.BUILTINS:
                    self._error(f"Undefined name '{expr.name}'", expr.info)
                return self.BUILTINS.get(expr.name, (None, None, None))[1]
            return sym.type_name
        if isinstance(expr, ThisExpr):
            if not self.current_class:
                self._error("'this' used outside of a class", expr.info)
            return self.current_class
        if isinstance(expr, ItExpr):
            # 'it' is context-dependent (match arms), hard to check statically
            sym = self.current_scope.resolve("it")
            return sym.type_name if sym else None
        if isinstance(expr, UnaryExpr):
            operand_type = self._infer_expr(expr.operand)
            unary_methods = {"-": "op_neg", "~": "op_bit_not", "!": "op_not"}
            method_name = unary_methods.get(expr.op)
            candidates = self._class_method_candidates(operand_type, method_name or "")
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, method_name or "", operand_type, expr.info
                    )
                fake_call = CallExpr(
                    callee=MemberExpr(obj=expr.operand, member=method_name or "", info=expr.info),
                    args=(),
                    info=expr.info,
                )
                return self._infer_function_call(
                    f"{base_type(operand_type)}.{method_name}",
                    [method for _, method in candidates],
                    fake_call,
                )
            if expr.op == "!":
                self._expect_type(operand_type, "Bool", expr.info, "'!' operand must be Bool")
                return "Bool"
            if expr.op in ("-", "~"):
                self._expect_numeric(
                    operand_type, expr.info, f"'{expr.op}' operand must be numeric"
                )
                return operand_type
        if isinstance(expr, BinaryExpr):
            return self._infer_binary(expr)
        if isinstance(expr, AssignExpr):
            value_type = self._infer_expr(expr.value)
            if isinstance(expr.target, Identifier):
                sym = self.current_scope.resolve(expr.target.name)
                if not sym:
                    sym = Symbol(name=expr.target.name, type_name=value_type, kind="var")
                    err = self.current_scope.define(sym)
                    if err:
                        self._error(err, expr.target.info)
                    return value_type
                if sym.type_name == "Any":
                    sym.type_name = value_type
            target_type = self._infer_assignment_target(expr.target)
            self._check_assignable(
                target_type, value_type, expr.info, f"Cannot assign {value_type} to {target_type}"
            )
            return value_type
        if isinstance(expr, CompoundAssignExpr):
            target_type = self._infer_assignment_target(expr.target)
            value_type = self._infer_expr(expr.value)
            self._check_binary_operands(expr.op.rstrip("="), target_type, value_type, expr.info)
            return target_type
        if isinstance(expr, IncrementExpr):
            target_type = self._infer_assignment_target(expr.target)
            self._expect_numeric(target_type, expr.info, "'++/--' target must be numeric")
            return target_type
        if isinstance(expr, CallExpr):
            return self._infer_call(expr)
        if isinstance(expr, MemberExpr):
            obj_type = self._infer_expr(expr.obj)
            return self._member_type(obj_type, expr.member, expr.info)
        if isinstance(expr, IndexExpr):
            obj_type = self._infer_expr(expr.obj)
            index_type = self._infer_expr(expr.index)
            self._expect_type(index_type, "Int", expr.index.info, "index must be Int")
            if obj_type == "Str":
                return "Str"
            if obj_type == "List":
                return None
            if obj_type == "Range":
                return "Int"
            if obj_type is not None:
                self._error(f"Cannot index {obj_type}", expr.info)
            return None
        if isinstance(expr, SliceExpr):
            obj_type = self._infer_expr(expr.obj)
            if expr.start:
                start_type = self._infer_expr(expr.start)
                self._expect_type(start_type, "Int", expr.start.info, "slice start must be Int")
            if expr.end:
                end_type = self._infer_expr(expr.end)
                self._expect_type(end_type, "Int", expr.end.info, "slice end must be Int")
            if obj_type in ("List", "Str"):
                return obj_type
            if obj_type is not None:
                self._error(f"Cannot slice {obj_type}", expr.info)
            return None
        if isinstance(expr, ListExpr):
            elem_type = None
            for elem in expr.elements:
                elem_type = self._common_type(elem_type, self._infer_expr(elem))
            return f"List<{elem_type}>" if elem_type else "List"
        if isinstance(expr, OkExpr):
            value_type = self._infer_expr(expr.value)
            return f"Ok<{value_type}>" if value_type else "Ok"
        if isinstance(expr, ErrExpr):
            value_type = self._infer_expr(expr.value)
            return f"Err<{value_type}>" if value_type else "Err"
        if isinstance(expr, LambdaExpr):
            scope = self._push_scope("function")
            prev_func = self.current_function
            lambda_params = [
                Param(
                    name=pname,
                    type_annotation=ptype,
                    default=None,
                    is_optional=False,
                )
                for pname, ptype in expr.params
            ]
            lambda_body = (
                expr.body
                if isinstance(expr.body, BlockStmt)
                else BlockStmt(
                    statements=(ReturnStmt(value=expr.body, info=expr.info),),
                    info=expr.info,
                )
            )
            self.current_function = FunctionDecl(
                name="<lambda>",
                params=lambda_params,
                return_type=expr.return_type,
                body=lambda_body,
                is_pub=False,
                is_static=False,
                info=expr.info,
            )
            for param in lambda_params:
                sym = Symbol(name=param.name, type_name=param.type_annotation, kind="param")
                scope.define(sym)
            if isinstance(expr.body, BlockStmt):
                self._analyze_block(expr.body)
                result_type = expr.return_type
            else:
                result_type = self._infer_expr(expr.body)
            self.current_function = prev_func
            self._pop_scope()
            self._check_assignable(
                expr.return_type, result_type, expr.info, f"Lambda returns {result_type}"
            )
            return lambda_type(lambda_params, expr.return_type, result_type)
        if isinstance(expr, ElvExpr):
            left_type = self._infer_expr(expr.left)
            right_type = self._infer_expr(expr.right)
            if base_type(left_type) not in (None, "R", "Ok", "Err"):
                self._error("'?:' operator requires a Result value", expr.info)
            return self._common_type(result_ok_type(left_type), right_type)
        if isinstance(expr, NullCoalesceExpr):
            left_type = self._infer_expr(expr.left)
            right_type = self._infer_expr(expr.right)
            if left_type == "Null":
                return right_type
            return self._common_type(left_type, right_type)
        if isinstance(expr, PropagateExpr):
            value_type = self._infer_expr(expr.value)
            if base_type(value_type) not in (None, "R", "Ok", "Err"):
                self._error("'?' operator requires a Result value", expr.info)
            if self.current_function and not self._is_assignable(
                self.current_function.return_type, "R"
            ):
                self._error("'?' operator requires the current function to return R", expr.info)
            return result_ok_type(value_type)
        if isinstance(expr, SafeCallExpr):
            obj_type = self._infer_expr(expr.obj)
            receiver_type = self._safe_receiver_type(obj_type)
            candidates = self._class_method_candidates(receiver_type, expr.member)
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, expr.member, receiver_type, expr.info
                    )
                fake_call = CallExpr(
                    callee=MemberExpr(obj=expr.obj, member=expr.member, info=expr.info),
                    args=expr.args,
                    info=expr.info,
                )
                return self._infer_function_call(
                    f"{base_type(receiver_type)}.{expr.member}",
                    [method for _, method in candidates],
                    fake_call,
                )
            for arg in expr.args:
                self._infer_expr(arg)
            if base_type(receiver_type) in (None, "R", "Ok", "Err", "PyObject", "PyCallable"):
                return None
            member_type = self._member_type(receiver_type, expr.member, expr.info)
            return (
                member_type if member_type not in ("Function", "PyObject", "PyCallable") else None
            )
        if isinstance(expr, SafeMemberExpr):
            obj_type = self._infer_expr(expr.obj)
            receiver_type = self._safe_receiver_type(obj_type)
            if base_type(receiver_type) in (
                None,
                "R",
                "Ok",
                "Err",
                "PyObject",
                "PyCallable",
            ):
                return None
            member_type = self._member_type(receiver_type, expr.member, expr.info)
            return (
                member_type if member_type not in ("Function", "PyObject", "PyCallable") else None
            )
        if isinstance(expr, IfExpr):
            return self._infer_if_expr(expr)
        if isinstance(expr, RangeExpr):
            start_type = self._infer_expr(expr.start)
            end_type = self._infer_expr(expr.end)
            self._expect_type(start_type, "Int", expr.start.info, "range start must be Int")
            self._expect_type(end_type, "Int", expr.end.info, "range end must be Int")
            return "Range"
        if isinstance(expr, PatternMatchExpr):
            scrutinee_type = self._infer_expr(expr.scrutinee)
            result_type = None
            for arm in expr.arms:
                if arm.pattern.kind == "literal" and not isinstance(arm.pattern.value, Identifier):
                    self._infer_expr(arm.pattern.value)  # type: ignore[arg-type]
                it_type = self._match_it_type(scrutinee_type, arm.pattern)
                if isinstance(arm.body, BlockStmt):
                    arm_type = self._infer_value_block(
                        arm.body, (Symbol(name="it", type_name=it_type, kind="var"),)
                    )
                else:
                    self._push_scope()
                    self.current_scope.define(Symbol(name="it", type_name=it_type, kind="var"))
                    arm_type = self._infer_expr(arm.body)
                    self._pop_scope()
                result_type = self._merge_branch_type(
                    result_type, arm_type, arm.info, "match expression arm types must match"
                )
            return result_type
        return None

    def _match_it_type(self, scrutinee_type: str | None, pattern: MatchPattern) -> str | None:
        if pattern.kind == "result":
            if pattern.value == "Ok":
                return result_ok_type(scrutinee_type)
            if pattern.value == "Err":
                return result_err_type(scrutinee_type)
        if pattern.kind == "type" and isinstance(pattern.value, str):
            return pattern.value
        return scrutinee_type

    def _safe_receiver_type(self, obj_type: str | None) -> str | None:
        base = base_type(obj_type)
        if base in ("R", "Ok"):
            return result_ok_type(obj_type)
        return obj_type

    def _infer_if_expr(self, expr: IfExpr) -> str | None:
        cond_type = self._infer_expr(expr.condition)
        self._expect_type(cond_type, "Bool", expr.condition.info, "if condition must be Bool")
        result_type = self._infer_value_block(expr.then_branch)
        for elif_cond, elif_body in expr.elif_branches:
            elif_type = self._infer_expr(elif_cond)
            self._expect_type(elif_type, "Bool", elif_cond.info, "elif condition must be Bool")
            arm_type = self._infer_value_block(elif_body)
            result_type = self._merge_branch_type(
                result_type, arm_type, elif_body.info, "if expression branch types must match"
            )
        if expr.else_branch is None:
            self._error("if expression must have an else branch", expr.info)
            return result_type
        else_type = self._infer_value_block(expr.else_branch)
        return self._merge_branch_type(
            result_type, else_type, expr.else_branch.info, "if expression branch types must match"
        )

    def _infer_value_block(
        self, block: BlockStmt, extra_symbols: Sequence[Symbol] = ()
    ) -> str | None:
        self._push_scope()
        for sym in extra_symbols:
            self.current_scope.define(sym)
        statements = list(block.statements)
        result_type: str | None = "Null"
        if statements and isinstance(statements[-1], ExprStmt):
            for stmt in statements[:-1]:
                self._analyze_stmt(stmt)
            result_type = self._infer_expr(statements[-1].expr)
        else:
            for stmt in statements:
                self._analyze_stmt(stmt)
        self._pop_scope()
        return result_type

    def _merge_branch_type(
        self,
        current: str | None,
        candidate: str | None,
        info: TokenInfo,
        message: str,
    ) -> str | None:
        if (
            current is not None
            and candidate is not None
            and self._common_type(current, candidate) is None
        ):
            self._error(f"{message}; expected {current}, got {candidate}", info)
            return current
        return self._common_type(current, candidate)

    def _iter_item_type(self, iterable_type: str | None) -> str | None:
        base = base_type(iterable_type)
        if base == "Range":
            return "Int"
        if base == "Str":
            return "Str"
        if base == "List":
            args = split_type_args(iterable_type)
            return args[0] if args else None
        if iterable_type not in (None, "PyObject", "PyCallable"):
            self._error(f"Cannot iterate over {iterable_type}")
        return None

    def _literal_type(self, expr: Expr) -> str:
        if isinstance(expr, IntLiteral):
            return "Int"
        if isinstance(expr, FloatLiteral):
            return "Float"
        if isinstance(expr, StrLiteral):
            return "Str"
        if isinstance(expr, BoolLiteral):
            return "Bool"
        return "Null"

    def _resolve_decl_type(self, declared: str | None, inferred: str | None) -> str | None:
        if declared == "Any" and inferred is not None:
            return inferred
        return declared or inferred

    def _infer_assignment_target(self, target: Expr) -> str | None:
        if isinstance(target, Identifier):
            sym = self.current_scope.resolve(target.name)
            if not sym:
                self._error(f"Undefined name '{target.name}'", target.info)
                return None
            return sym.type_name
        if isinstance(target, MemberExpr):
            obj_type = self._infer_expr(target.obj)
            return self._assignment_member_type(obj_type, target.member, target.info)
        if isinstance(target, IndexExpr):
            self._infer_expr(target.obj)
            index_type = self._infer_expr(target.index)
            self._expect_type(index_type, "Int", target.index.info, "index must be Int")
            return None
        self._error("Invalid assignment target", target.info)
        return None

    def _infer_binary(self, expr: BinaryExpr) -> str | None:
        left_type = self._infer_expr(expr.left)
        if expr.op == "is":
            if not isinstance(expr.right, Identifier):
                self._error("right operand of 'is' must be a type name", expr.right.info)
            return "Bool"
        right_type = self._infer_expr(expr.right)
        operator_methods = {
            "+": "op_add",
            "-": "op_sub",
            "*": "op_mul",
            "/": "op_div",
            "%": "op_mod",
            "&": "op_bit_and",
            "|": "op_bit_or",
            "^": "op_bit_xor",
            "<<": "op_shl",
            ">>": "op_shr",
            "==": "op_eq",
            "!=": "op_ne",
            ">": "op_gt",
            "<": "op_lt",
            ">=": "op_ge",
            "<=": "op_le",
        }
        method_name = operator_methods.get(expr.op)
        candidates = self._class_method_candidates(left_type, method_name or "")
        if candidates:
            for owner_class, method in candidates:
                self._check_member_access(
                    owner_class, method.is_pub, method_name or "", left_type, expr.info
                )
            fake_call = CallExpr(
                callee=MemberExpr(obj=expr.left, member=method_name or "", info=expr.info),
                args=(expr.right,),
                info=expr.info,
            )
            return self._infer_function_call(
                f"{base_type(left_type)}.{method_name}",
                [method for _, method in candidates],
                fake_call,
            )
        if expr.op in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"):
            self._check_binary_operands(expr.op, left_type, right_type, expr.info)
            if expr.op == "+" and (left_type == "Str" or right_type == "Str"):
                return "Str"
            if left_type == "Float" or right_type == "Float":
                return "Float"
            return left_type or right_type
        if expr.op in ("==", "!="):
            return "Bool"
        if expr.op in (">", "<", ">=", "<="):
            self._expect_numeric(left_type, expr.info, f"'{expr.op}' left operand must be numeric")
            self._expect_numeric(
                right_type, expr.info, f"'{expr.op}' right operand must be numeric"
            )
            return "Bool"
        if expr.op in ("&&", "||"):
            self._expect_type(
                left_type, "Bool", expr.info, f"'{expr.op}' left operand must be Bool"
            )
            self._expect_type(
                right_type, "Bool", expr.info, f"'{expr.op}' right operand must be Bool"
            )
            return "Bool"
        return None

    def _infer_call(self, expr: CallExpr) -> str | None:
        if isinstance(expr.callee, MemberExpr):
            obj_type = self._infer_expr(expr.callee.obj)
            candidates = self._class_method_candidates(obj_type, expr.callee.member)
            if candidates:
                for owner_class, method in candidates:
                    self._check_member_access(
                        owner_class, method.is_pub, expr.callee.member, obj_type, expr.info
                    )
                return self._infer_function_call(
                    f"{base_type(obj_type)}.{expr.callee.member}",
                    [method for _, method in candidates],
                    expr,
                )
            member_type = self._member_type(obj_type, expr.callee.member, expr.callee.info)
            for arg in expr.args:
                self._infer_expr(arg)
            if member_type not in (None, "Function", "PyObject", "PyCallable"):
                self._error(
                    f"Cannot call member '{expr.callee.member}' of type {member_type}", expr.info
                )
            return None
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            if name == "List":
                elem_type = None
                for arg in expr.args:
                    elem_type = self._common_type(elem_type, self._infer_expr(arg))
                return f"List<{elem_type}>" if elem_type else "List"
            if name in self.BUILTINS:
                _, return_type, arity = self.BUILTINS[name]
                self._check_arity(name, len(expr.args), arity, expr.info)
                arg_types = [self._infer_expr(arg) for arg in expr.args]
                if name == "Ok":
                    ok_type = arg_types[0] if arg_types else None
                    return f"Ok<{ok_type}>" if ok_type else "Ok"
                if name == "Err":
                    err_type = arg_types[0] if arg_types else None
                    return f"Err<{err_type}>" if err_type else "Err"
                if name == "unwrap":
                    if arg_types and base_type(arg_types[0]) not in (None, "R", "Ok", "Err"):
                        self._error("'unwrap' expects a Result value", expr.args[0].info)
                    return result_ok_type(arg_types[0] if arg_types else None)
                if name == "unwrap_or":
                    result_type = arg_types[0] if arg_types else None
                    default_type = arg_types[1] if len(arg_types) > 1 else None
                    if base_type(result_type) not in (None, "R", "Ok", "Err"):
                        self._error("'unwrap_or' expects a Result value", expr.args[0].info)
                    ok_type = result_ok_type(result_type)
                    if ok_type is not None and default_type is not None:
                        self._check_assignable(
                            ok_type,
                            default_type,
                            expr.args[1].info,
                            f"'unwrap_or' default expects {ok_type}, got {default_type}",
                        )
                    return self._common_type(ok_type, default_type)
                return return_type
            sym = self.current_scope.resolve(name)
            if not sym:
                self._error(f"Undefined name '{name}'", expr.info)
                for arg in expr.args:
                    self._infer_expr(arg)
                return None
            if sym.kind == "py_module":
                for arg in expr.args:
                    self._infer_expr(arg)
                return "PyObject"
            if sym.kind == "class":
                return self._infer_constructor_call(name, expr)
            if sym.kind == "func":
                overloads = self._function_overloads.get(name)
                if overloads:
                    return self._infer_function_call(name, overloads, expr)
                if isinstance(sym.decl, FunctionDecl):
                    return self._infer_function_call(name, [sym.decl], expr)
        callee_type = self._infer_expr(expr.callee)
        arg_types = [self._infer_expr(arg) for arg in expr.args]
        if base_type(callee_type) == "Function":
            return self._infer_function_value_call(callee_type, arg_types, expr)
        if callee_type not in (None, "Function", "PyObject", "PyCallable"):
            self._error(f"Cannot call value of type {callee_type}", expr.info)
        return None

    def _infer_function_value_call(
        self, callee_type: str | None, arg_types: Sequence[str | None], expr: CallExpr
    ) -> str | None:
        expected_arg_types = function_arg_types(callee_type)
        return_type = function_return_type(callee_type)
        if not expected_arg_types and return_type is None:
            return None
        if len(arg_types) != len(expected_arg_types):
            self._error(
                f"Function value expects {len(expected_arg_types)} args, got {len(arg_types)}",
                expr.info,
            )
            return return_type
        for arg, expected, actual in zip(expr.args, expected_arg_types, arg_types, strict=False):
            self._check_assignable(
                expected,
                actual,
                arg.info,
                f"Function value argument expects {expected}, got {actual}",
            )
        return return_type

    def _check_function_call(
        self,
        func: FunctionDecl,
        expr: CallExpr,
        initial_mapping: dict[str, str | None] | None = None,
    ) -> dict[str, str | None]:
        bindings = dict(initial_mapping or {})
        required = sum(
            1 for param in func.params if not param.is_optional and param.default is None
        )
        if len(expr.args) < required or len(expr.args) > len(func.params):
            self._error(
                f"Function '{func.name}' expects {required}-{len(func.params)} args, got {len(expr.args)}",
                expr.info,
            )
        for arg, param in zip(expr.args, func.params, strict=False):
            arg_type = self._infer_expr(arg)
            expected = substitute_type(param.type_annotation, bindings)
            if not self._match_type_pattern(expected, arg_type, func.type_params, bindings):
                self._error(
                    f"Argument '{param.name}' expects {expected}, got {arg_type}",
                    arg.info,
                )
                continue
            expected = substitute_type(param.type_annotation, bindings)
            if expected != "Any":
                self._check_assignable(
                    expected,
                    arg_type,
                    arg.info,
                    f"Argument '{param.name}' expects {expected}, got {arg_type}",
                )
        return bindings

    def _infer_constructor_call(self, class_name: str, expr: CallExpr) -> str | None:
        cls = self._class_decls.get(class_name)
        init_overloads = self._class_method_overloads.get(class_name, {}).get("init")
        if init_overloads and cls and cls.type_params:
            init_overloads = [
                replace(
                    init,
                    type_params=tuple(cls.type_params) + tuple(init.type_params),
                )
                for init in init_overloads
            ]
        mapping: dict[str, str | None] = {}
        selected = None
        if init_overloads:
            selected, mapping, _ = self._resolve_overload(
                f"{class_name}.init", init_overloads, expr
            )
        else:
            if expr.args:
                self._error(
                    f"Class '{class_name}' constructor expects 0 args, got {len(expr.args)}",
                    expr.info,
                )
            for arg in expr.args:
                self._infer_expr(arg)
        if selected is not None:
            for type_param in cls.type_params if cls else ():
                mapping.setdefault(type_param, None)
        if cls and cls.type_params:
            args = [mapping.get(type_param) or "Any" for type_param in cls.type_params]
            return f"{class_name}<{','.join(args)}>"
        return class_name

    def _check_arity(self, name: str, got: int, arity: int, info: TokenInfo) -> None:
        if arity >= 0 and got != arity:
            self._error(f"Function '{name}' expects {arity} args, got {got}", info)

    def _member_type(self, obj_type: str | None, member: str, info: TokenInfo) -> str | None:
        if obj_type is None:
            return None
        base = base_type(obj_type)
        if base in ("PyModule", "PyObject", "PyCallable"):
            return "PyObject"
        if base == "Str":
            if member == "size":
                return "Int"
            self._error(f"No member '{member}' on Str", info)
            return None
        if base == "List":
            if member == "size":
                return "Int"
            if member == "add":
                return "Function"
            self._error(f"No member '{member}' on List", info)
            return None
        if base == "Range":
            if member in ("size", "start", "end"):
                return "Int"
            if member == "inclusive":
                return "Bool"
            self._error(f"No member '{member}' on Range", info)
            return None
        if base == "R":
            if member == "value":
                return None
            return None
        getter_candidate = self._class_getter_candidate(obj_type, member)
        if getter_candidate is not None:
            owner_class, getter = getter_candidate
            self._check_member_access(owner_class, getter.is_pub, member, obj_type, info)
            return getter.return_type
        field_candidate = self._class_field_candidate(obj_type, member)
        if field_candidate is not None:
            owner_class, field = field_candidate
            self._check_member_access(owner_class, field.is_pub, member, obj_type, info)
            return substitute_type(
                self._class_field_types.get(owner_class, {}).get(member),
                self._class_type_mapping_for(obj_type, owner_class),
            )
        method_candidates = self._class_method_candidates(obj_type, member)
        if method_candidates:
            for owner_class, method in method_candidates:
                self._check_member_access(owner_class, method.is_pub, member, obj_type, info)
            return "Function"
        if base in self._class_decls:
            self._error(f"No member '{member}' on {obj_type}", info)
        return None

    def _assignment_member_type(
        self, obj_type: str | None, member: str, info: TokenInfo
    ) -> str | None:
        setter_candidate = self._class_setter_candidate(obj_type, member)
        if setter_candidate is not None:
            owner_class, setter = setter_candidate
            self._check_member_access(owner_class, setter.is_pub, member, obj_type, info)
            if setter.params:
                return setter.params[0].type_annotation
            return None
        return self._member_type(obj_type, member, info)

    def _can_access_member(self, class_name: str, is_pub: bool) -> bool:
        return is_pub or self.current_class == class_name

    def _check_member_access(
        self, class_name: str, is_pub: bool, member: str, obj_type: str | None, info: TokenInfo
    ) -> None:
        if not self._can_access_member(class_name, is_pub):
            self._error(f"Cannot access private member '{member}' on {obj_type}", info)

    def _check_binary_operands(
        self, op: str, left: str | None, right: str | None, info: TokenInfo
    ) -> None:
        if op == "+" and (left == "Str" or right == "Str"):
            return
        if op in ("&", "|", "^", "<<", ">>"):
            self._expect_type(left, "Int", info, f"'{op}' left operand must be Int")
            self._expect_type(right, "Int", info, f"'{op}' right operand must be Int")
            return
        if op in ("+", "-", "*", "/", "%"):
            self._expect_numeric(left, info, f"'{op}' left operand must be numeric")
            self._expect_numeric(right, info, f"'{op}' right operand must be numeric")

    def _expect_numeric(self, actual: str | None, info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable", "Int", "Float"):
            return
        self._error(f"{msg}, got {actual}", info)

    def _expect_type(self, actual: str | None, expected: str, info: TokenInfo, msg: str) -> None:
        if actual in (None, "PyObject", "PyCallable") or expected is None:
            return
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}, got {actual}", info)

    def _check_assignable(
        self, expected: str | None, actual: str | None, info: TokenInfo, msg: str
    ) -> None:
        if not self._is_assignable(expected, actual):
            self._error(f"{msg}; expected {expected}", info)

    def _is_assignable(self, expected: str | None, actual: str | None) -> bool:
        if expected is None or actual is None:
            return True
        if expected == "Any" or actual in ("PyObject", "PyCallable"):
            return True
        if expected == actual:
            return True
        if expected == "Float" and actual == "Int":
            return True
        expected_base = base_type(expected)
        actual_base = base_type(actual)
        if expected_base == "Function" and actual_base == "Function":
            expected_args = split_type_args(expected)
            actual_args = split_type_args(actual)
            if not expected_args or not actual_args:
                return True
            if len(expected_args) != len(actual_args):
                return False
            return all(
                self._is_assignable(exp, act)
                for exp, act in zip(expected_args, actual_args, strict=False)
            )
        if expected_base == "R":
            expected_args = split_type_args(expected)
            if actual_base == "R":
                actual_args = split_type_args(actual)
                if not expected_args or not actual_args:
                    return True
                if len(expected_args) != len(actual_args):
                    return False
                return all(
                    self._is_assignable(exp, act)
                    for exp, act in zip(expected_args, actual_args, strict=False)
                )
            if actual_base == "Ok":
                ok_type = result_ok_type(actual)
                if not expected_args:
                    return True
                if len(expected_args) == 1:
                    return self._is_assignable(expected_args[0], ok_type)
                if len(expected_args) >= 2:
                    return self._is_assignable(expected_args[0], ok_type)
            if actual_base == "Err":
                err_type = result_err_type(actual)
                if not expected_args:
                    return True
                if len(expected_args) == 1:
                    return self._is_assignable(expected_args[0], err_type)
                if len(expected_args) >= 2:
                    return self._is_assignable(expected_args[1], err_type)
            return False
        if expected_base == actual_base:
            expected_args = split_type_args(expected)
            actual_args = split_type_args(actual)
            if not expected_args or not actual_args:
                return True
            return expected_args == actual_args
        projected_actual = self._project_type_to_base(actual, expected_base)
        if projected_actual is not None:
            expected_args = split_type_args(expected)
            actual_args = split_type_args(projected_actual)
            if not expected_args or not actual_args:
                return True
            return expected_args == actual_args
        return False

    def _common_type(self, left: str | None, right: str | None) -> str | None:
        if left is None:
            return right
        if right is None:
            return left
        if self._is_assignable(left, right):
            return left
        if self._is_assignable(right, left):
            return right
        return None
