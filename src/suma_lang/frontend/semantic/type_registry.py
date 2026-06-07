"""Type/member registry state for the semantic analyzer.

The analyzer has two distinct responsibilities that used to be mixed in one
object: walking AST nodes and maintaining the catalog of declared classes,
enums, overloads, and member lookup caches. ``TypeRegistry`` owns that catalog.
Analyzer still performs the validation logic, but registry state no longer
lives directly on the analyzer instance.
"""

from __future__ import annotations

from dataclasses import replace

from suma_lang.frontend.parser.ast_nodes import (
    ClassDecl,
    EnumDecl,
    FunctionDecl,
    VarDecl,
)
from suma_lang.frontend.semantic.types import (
    base_type,
    erase_type,
    split_type_args,
    substitute_type,
)


class TypeRegistry:
    def __init__(self) -> None:
        self.class_decls: dict[str, ClassDecl] = {}
        self.class_fields: dict[str, dict[str, VarDecl]] = {}
        self.class_field_types: dict[str, dict[str, str | None]] = {}
        self.class_methods: dict[str, dict[str, FunctionDecl]] = {}
        self.class_getters: dict[str, dict[str, FunctionDecl]] = {}
        self.class_setters: dict[str, dict[str, FunctionDecl]] = {}
        self.enum_decls: dict[str, EnumDecl] = {}
        self.enum_variants: dict[str, dict[str, str | None]] = {}
        self.function_overloads: dict[str, list[FunctionDecl]] = {}
        self.class_method_overloads: dict[str, dict[str, list[FunctionDecl]]] = {}

        self.class_chain_cache: dict[str | None, tuple[str, ...]] = {}
        self.project_type_cache: dict[tuple[str | None, str | None], str | None] = {}
        self.method_candidate_cache: dict[
            tuple[str | None, str], tuple[tuple[str, FunctionDecl], ...]
        ] = {}
        self.field_candidate_cache: dict[tuple[str | None, str], tuple[str, VarDecl] | None] = {}
        self.getter_candidate_cache: dict[
            tuple[str | None, str], tuple[str, FunctionDecl] | None
        ] = {}
        self.setter_candidate_cache: dict[
            tuple[str | None, str], tuple[str, FunctionDecl] | None
        ] = {}
        self.assignable_cache: dict[tuple[str | None, str | None], bool] = {}

    def clear_query_caches(self) -> None:
        self.class_chain_cache.clear()
        self.project_type_cache.clear()
        self.method_candidate_cache.clear()
        self.field_candidate_cache.clear()
        self.getter_candidate_cache.clear()
        self.setter_candidate_cache.clear()
        self.assignable_cache.clear()

    def _class_type_mapping(self, obj_type: str | None) -> dict[str, str | None]:
        base = base_type(obj_type)
        if base is None:
            return {}
        cls = self.class_decls.get(base)
        if cls is None or not cls.type_params:
            return {}
        args = split_type_args(obj_type)
        return {
            name: args[index] if index < len(args) else None
            for index, name in enumerate(cls.type_params)
        }

    def _base_class_name(self, class_name: str) -> str | None:
        cls = self.class_decls.get(class_name)
        if cls is None or cls.base_type is None:
            return None
        return base_type(cls.base_type)

    def _class_chain(self, class_name: str | None) -> list[str]:
        cached = self.class_chain_cache.get(class_name)
        if cached is not None:
            return list(cached)
        chain: list[str] = []
        seen: set[str] = set()
        current = class_name
        while current is not None and current not in seen:
            chain.append(current)
            seen.add(current)
            current = self._base_class_name(current)
        self.class_chain_cache[class_name] = tuple(chain)
        return chain

    def _project_type_to_base(self, actual_type: str | None, target_base: str | None) -> str | None:
        cache_key = (actual_type, target_base)
        if cache_key in self.project_type_cache:
            return self.project_type_cache[cache_key]
        if actual_type is None or target_base is None:
            self.project_type_cache[cache_key] = None
            return None
        current_type = actual_type
        seen: set[str] = set()
        while current_type is not None:
            current_base = base_type(current_type)
            if current_base == target_base:
                self.project_type_cache[cache_key] = current_type
                return current_type
            if current_base is None or current_base in seen:
                self.project_type_cache[cache_key] = None
                return None
            seen.add(current_base)
            cls = self.class_decls.get(current_base)
            if cls is None or cls.base_type is None:
                self.project_type_cache[cache_key] = None
                return None
            current_type = substitute_type(cls.base_type, self._class_type_mapping(current_type))
        self.project_type_cache[cache_key] = None
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
            method, params=params, return_type=substitute_type(method.return_type, mapping)
        )

    def _method_signature(self, func: FunctionDecl) -> tuple[int, tuple[str | None, ...]]:
        return len(func.params), tuple(erase_type(param.type_annotation) for param in func.params)

    def _class_method_candidates(
        self, obj_type: str | None, method_name: str
    ) -> list[tuple[str, FunctionDecl]]:
        cache_key = (obj_type, method_name)
        cached = self.method_candidate_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        base = base_type(obj_type)
        candidates: list[tuple[str, FunctionDecl]] = []
        seen_signatures: set[tuple[int, tuple[str | None, ...]]] = set()
        for owner_class in self._class_chain(base):
            for method in self.class_method_overloads.get(owner_class, {}).get(method_name, []):
                bound = self._bind_method_to_object(obj_type, owner_class, method)
                signature = self._method_signature(bound)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                candidates.append((owner_class, bound))
        self.method_candidate_cache[cache_key] = tuple(candidates)
        return candidates

    def _class_field_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, VarDecl] | None:
        cache_key = (obj_type, member)
        if cache_key in self.field_candidate_cache:
            return self.field_candidate_cache[cache_key]
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            field = self.class_fields.get(owner_class, {}).get(member)
            if field is not None:
                result = (owner_class, field)
                self.field_candidate_cache[cache_key] = result
                return result
        self.field_candidate_cache[cache_key] = None
        return None

    def _class_getter_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, FunctionDecl] | None:
        cache_key = (obj_type, member)
        if cache_key in self.getter_candidate_cache:
            return self.getter_candidate_cache[cache_key]
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            getter = self.class_getters.get(owner_class, {}).get(member)
            if getter is not None:
                result = (owner_class, self._bind_method_to_object(obj_type, owner_class, getter))
                self.getter_candidate_cache[cache_key] = result
                return result
        self.getter_candidate_cache[cache_key] = None
        return None

    def _class_setter_candidate(
        self, obj_type: str | None, member: str
    ) -> tuple[str, FunctionDecl] | None:
        cache_key = (obj_type, member)
        if cache_key in self.setter_candidate_cache:
            return self.setter_candidate_cache[cache_key]
        base = base_type(obj_type)
        for owner_class in self._class_chain(base):
            setter = self.class_setters.get(owner_class, {}).get(member)
            if setter is not None:
                result = (owner_class, self._bind_method_to_object(obj_type, owner_class, setter))
                self.setter_candidate_cache[cache_key] = result
                return result
        self.setter_candidate_cache[cache_key] = None
        return None
