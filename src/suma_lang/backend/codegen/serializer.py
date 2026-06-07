"""Serializer for .sumac bytecode files."""

from __future__ import annotations

import json
import struct
from typing import Any

from suma_lang.backend.codegen.opcodes import Function, Op, ProgramBytecode

MAGIC = b"SUMA"
VERSION = 11


class BytecodeFormatError(ValueError):
    """Raised when a .sumac file is malformed or uses an unsupported version."""


class _ByteReader:
    def __init__(self, data: bytes, context: str = ".sumac file") -> None:
        self.data = data
        self.offset = 0
        self.context = context

    def read(self, n: int) -> bytes:
        if n < 0:
            raise BytecodeFormatError(f"Invalid {self.context}: negative read length")
        end = self.offset + n
        if end > len(self.data):
            raise BytecodeFormatError(f"Invalid {self.context}: truncated data")
        chunk = self.data[self.offset : end]
        self.offset = end
        return chunk

    def read_u8(self) -> int:
        return struct.unpack("<B", self.read(1))[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def read_i64(self) -> int:
        return struct.unpack("<q", self.read(8))[0]

    def read_f64(self) -> float:
        return struct.unpack("<d", self.read(8))[0]

    def remaining(self) -> bytes:
        chunk = self.data[self.offset :]
        self.offset = len(self.data)
        return chunk

    def ensure_finished(self) -> None:
        if self.offset != len(self.data):
            raise BytecodeFormatError(f"Invalid {self.context}: trailing data")


_CODE_ARG_COUNTS = {
    Op.LOAD_CONST: 1,
    Op.LOAD_VAR: 1,
    Op.STORE_VAR: 1,
    Op.LOAD_GLOBAL: 1,
    Op.STORE_GLOBAL: 1,
    Op.CALL_GLOBAL: 1,
    Op.LOAD_FUNC: 1,
    Op.JUMP: 1,
    Op.JUMP_IF_FALSE: 1,
    Op.JUMP_IF_TRUE: 1,
    Op.CALL: 1,
    Op.MAKE_LIST: 1,
    Op.MAKE_TUPLE: 1,
    Op.MAKE_RANGE: 1,
    Op.MAKE_OBJECT: 2,
    Op.MAKE_LAMBDA: 1,
    Op.MAKE_ENUM: 2,
    Op.IS_ENUM_VARIANT: 1,
    Op.MEMBER: 1,
    Op.SET_MEMBER: 1,
    Op.SLICE: 1,
    Op.TAIL_CALL_GLOBAL: 1,
    Op.JUMP_IF_VAR_CMP: 4,
    Op.JUMP_IF_VAR_CONST_CMP: 4,
    Op.INPLACE_VAR_VAR: 3,
    Op.INPLACE_VAR_CONST: 3,
}


def _json_bytes(value: object, section: str) -> bytes:
    try:
        return json.dumps(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BytecodeFormatError(f"Cannot serialize {section}: {exc}") from exc


def _read_json_section(reader: _ByteReader, section: str) -> dict[str, Any]:
    length = reader.read_u32()
    raw = reader.read(length)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BytecodeFormatError(f"Invalid {section}: malformed JSON") from exc
    if not isinstance(value, dict):
        raise BytecodeFormatError(f"Invalid {section}: expected JSON object")
    return value


def _decode_text(raw: bytes, context: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BytecodeFormatError(f"Invalid {context}: malformed UTF-8") from exc


def _require_index(index: int, size: int, what: str, context: str) -> None:
    if index < 0 or index >= size:
        raise BytecodeFormatError(f"Invalid {context}: {what} index {index} out of range")


def _validate_const_index(index: int, fn: Function, prog: ProgramBytecode, context: str) -> None:
    if index < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative constant index {index}")
    if index < len(fn.constants) or index < len(prog.constants):
        return
    raise BytecodeFormatError(f"Invalid {context}: constant index {index} out of range")


def _validate_program_const_index(index: int, prog: ProgramBytecode, context: str) -> None:
    if index < 0 or index >= len(prog.constants):
        raise BytecodeFormatError(f"Invalid {context}: program constant index {index} out of range")


def _program_string_constant(index: int, prog: ProgramBytecode, context: str) -> str:
    _validate_program_const_index(index, prog, context)
    value = prog.constants[index]
    if not isinstance(value, str):
        raise BytecodeFormatError(f"Invalid {context}: expected string constant at index {index}")
    return value


def _validate_slot(index: int, fn: Function, context: str) -> None:
    if index < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative local slot {index}")
    if index >= max(fn.locals_count, 1):
        raise BytecodeFormatError(f"Invalid {context}: local slot {index} out of range")


def _validate_jump(target: int, code_len: int, context: str) -> None:
    if target < 0 or target > code_len:
        raise BytecodeFormatError(f"Invalid {context}: jump target {target} out of range")


def _validate_cmp_code(cmp_code: int, context: str) -> None:
    if cmp_code < 0 or cmp_code > 5:
        raise BytecodeFormatError(f"Invalid {context}: comparison code {cmp_code} out of range")


def _validate_function_shape(fn: Function, context: str) -> None:
    if not isinstance(fn.name, str) or not fn.name:
        raise BytecodeFormatError(f"Invalid {context}: function name must be a non-empty string")
    if fn.arity < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative arity")
    if fn.locals_count < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative locals count")
    if fn.capture_count < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative capture count")
    if not all(isinstance(slot, int) and slot >= 0 for slot in fn.capture_slots):
        raise BytecodeFormatError(f"Invalid {context}: capture slots must be non-negative ints")


def _validate_call_global_arg(arg: int, prog: ProgramBytecode, context: str) -> None:
    if arg < 0:
        raise BytecodeFormatError(f"Invalid {context}: negative encoded function call")
    func_idx = arg & 0xFFFF
    nargs = arg >> 16
    _require_index(func_idx, len(prog.functions), "function", context)
    arity = prog.functions[func_idx].arity
    if nargs != arity:
        raise BytecodeFormatError(
            f"Invalid {context}: function[{func_idx}] call arity {nargs} does not match {arity}"
        )


def _validate_code(fn: Function, prog: ProgramBytecode, context: str) -> None:
    code = fn.code
    i = 0
    while i < len(code):
        try:
            op = Op(code[i])
        except ValueError as exc:
            raise BytecodeFormatError(f"Invalid {context}: unknown opcode {code[i]}") from exc
        if op == Op.LOOP_GENERIC:
            if i + 1 >= len(code):
                raise BytecodeFormatError(f"Invalid {context}: truncated LOOP_GENERIC")
            arg_count = code[i + 1]
            if arg_count < 0:
                raise BytecodeFormatError(f"Invalid {context}: negative LOOP_GENERIC arg count")
            next_i = i + 2 + arg_count
            if next_i > len(code):
                raise BytecodeFormatError(f"Invalid {context}: truncated LOOP_GENERIC arguments")
            if arg_count < 4:
                raise BytecodeFormatError(f"Invalid {context}: LOOP_GENERIC missing header")
            left_slot, right_slot, cmp_code, op_count = code[i + 2 : i + 6]
            expected_arg_count = 4 + op_count * 3
            if op_count < 0 or arg_count != expected_arg_count:
                raise BytecodeFormatError(f"Invalid {context}: inconsistent LOOP_GENERIC layout")
            _validate_slot(left_slot, fn, context)
            _validate_slot(right_slot, fn, context)
            _validate_cmp_code(cmp_code, context)
            pos = i + 6
            for _ in range(op_count):
                target_slot, rhs_ref, op_code = code[pos : pos + 3]
                _validate_slot(target_slot, fn, context)
                if rhs_ref < 0:
                    _validate_const_index(~rhs_ref, fn, prog, context)
                else:
                    _validate_slot(rhs_ref, fn, context)
                try:
                    binop = Op(op_code)
                except ValueError as exc:
                    raise BytecodeFormatError(
                        f"Invalid {context}: LOOP_GENERIC operation opcode {op_code}"
                    ) from exc
                if binop not in (Op.ADD, Op.SUB, Op.MUL, Op.DIV, Op.MOD):
                    raise BytecodeFormatError(
                        f"Invalid {context}: unsupported LOOP_GENERIC operation {binop.name}"
                    )
                pos += 3
            i = next_i
            continue
        arg_count = _CODE_ARG_COUNTS.get(op, 0)
        next_i = i + 1 + arg_count
        if next_i > len(code):
            raise BytecodeFormatError(f"Invalid {context}: truncated {op.name} arguments")
        args = code[i + 1 : next_i]
        if op in (Op.LOAD_CONST, Op.INPLACE_VAR_CONST, Op.JUMP_IF_VAR_CONST_CMP):
            const_arg = args[0] if op == Op.LOAD_CONST else args[1]
            _validate_const_index(const_arg, fn, prog, context)
        elif op in (
            Op.LOAD_GLOBAL,
            Op.STORE_GLOBAL,
            Op.IS_ENUM_VARIANT,
            Op.MEMBER,
            Op.SET_MEMBER,
            Op.MAKE_OBJECT,
            Op.MAKE_ENUM,
        ):
            _program_string_constant(args[0], prog, context)
        if op in (Op.LOAD_VAR, Op.STORE_VAR):
            _validate_slot(args[0], fn, context)
        elif op in (Op.INPLACE_VAR_VAR, Op.INPLACE_VAR_CONST):
            _validate_slot(args[0], fn, context)
            if op == Op.INPLACE_VAR_VAR:
                _validate_slot(args[1], fn, context)
            try:
                binop = Op(args[2])
            except ValueError as exc:
                raise BytecodeFormatError(
                    f"Invalid {context}: unknown inplace opcode {args[2]}"
                ) from exc
            if binop not in (Op.ADD, Op.SUB, Op.MUL, Op.DIV, Op.MOD):
                raise BytecodeFormatError(
                    f"Invalid {context}: unsupported inplace opcode {binop.name}"
                )
        elif op == Op.JUMP_IF_VAR_CMP:
            _validate_slot(args[0], fn, context)
            _validate_slot(args[1], fn, context)
            _validate_cmp_code(args[2], context)
            _validate_jump(args[3], len(code), context)
        elif op == Op.JUMP_IF_VAR_CONST_CMP:
            _validate_slot(args[0], fn, context)
            _validate_cmp_code(args[2], context)
            _validate_jump(args[3], len(code), context)
        elif op in (Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_TRUE):
            _validate_jump(args[0], len(code), context)
        elif op in (Op.LOAD_FUNC, Op.MAKE_LAMBDA):
            _require_index(args[0], len(prog.functions), "function", context)
        elif op in (Op.CALL_GLOBAL, Op.TAIL_CALL_GLOBAL):
            _validate_call_global_arg(args[0], prog, context)
        elif op == Op.CALL and args[0] < 0:
            raise BytecodeFormatError(f"Invalid {context}: negative call arity")
        elif op in (Op.MAKE_LIST, Op.MAKE_TUPLE) and args[0] < 0:
            raise BytecodeFormatError(f"Invalid {context}: negative element count")
        elif op == Op.MAKE_OBJECT and args[1] < 0:
            raise BytecodeFormatError(f"Invalid {context}: negative object argument count")
        elif op == Op.MAKE_ENUM and args[1] < 0:
            raise BytecodeFormatError(f"Invalid {context}: negative enum payload count")
        elif op == Op.MAKE_RANGE and args[0] not in (0, 1):
            raise BytecodeFormatError(f"Invalid {context}: range inclusivity flag out of range")
        elif op == Op.SLICE and (args[0] < 0 or args[0] > 3):
            raise BytecodeFormatError(f"Invalid {context}: slice mask out of range")
        i = next_i


def _validate_index_map(value: object, section: str, prog: ProgramBytecode) -> None:
    if not isinstance(value, dict):
        raise BytecodeFormatError(f"Invalid {section}: expected object")
    for name, index in value.items():
        if not isinstance(name, str) or not isinstance(index, int):
            raise BytecodeFormatError(f"Invalid {section}: expected string -> function index")
        _require_index(index, len(prog.functions), "function", section)


def _validate_index_list_map(value: object, section: str, prog: ProgramBytecode) -> None:
    if not isinstance(value, dict):
        raise BytecodeFormatError(f"Invalid {section}: expected object")
    for name, indices in value.items():
        if not isinstance(name, str) or not isinstance(indices, list):
            raise BytecodeFormatError(f"Invalid {section}: expected string -> function index list")
        for index in indices:
            if not isinstance(index, int):
                raise BytecodeFormatError(f"Invalid {section}: function index must be an int")
            _require_index(index, len(prog.functions), "function", section)


def _validate_enums(prog: ProgramBytecode) -> None:
    if not isinstance(prog.enums, dict):
        raise BytecodeFormatError("Invalid enums: expected object")
    for enum_name, variants in prog.enums.items():
        if not isinstance(enum_name, str) or not isinstance(variants, dict):
            raise BytecodeFormatError("Invalid enums: expected enum object")
        for variant_name, payload_type in variants.items():
            if not isinstance(variant_name, str) or not (
                payload_type is None or isinstance(payload_type, str)
            ):
                raise BytecodeFormatError("Invalid enums: expected variant payload type")


def _validate_classes(prog: ProgramBytecode) -> None:
    if not isinstance(prog.classes, dict):
        raise BytecodeFormatError("Invalid classes: expected object")
    for class_name, info in prog.classes.items():
        if not isinstance(class_name, str) or not isinstance(info, dict):
            raise BytecodeFormatError("Invalid classes: expected class object")
        fields = info.get("fields", [])
        if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields):
            raise BytecodeFormatError(f"Invalid classes.{class_name}: fields must be strings")
        for section in ("methods", "getters", "setters"):
            _validate_index_map(info.get(section, {}), f"classes.{class_name}.{section}", prog)
        _validate_index_list_map(
            info.get("method_overloads", {}),
            f"classes.{class_name}.method_overloads",
            prog,
        )


def _validate_py_imports(prog: ProgramBytecode) -> None:
    if not isinstance(prog.py_imports, dict):
        raise BytecodeFormatError("Invalid Python imports: expected object")
    for alias, module_name in prog.py_imports.items():
        if not isinstance(alias, str) or not isinstance(module_name, str):
            raise BytecodeFormatError("Invalid Python imports: expected string -> string")


def _validate_metadata(prog: ProgramBytecode) -> None:
    _validate_classes(prog)
    _validate_enums(prog)
    _validate_py_imports(prog)
    _validate_index_map(prog.decorators, "decorators", prog)
    _validate_index_map(prog.method_decorators, "method decorators", prog)
    _validate_index_list_map(prog.overloads, "overloads", prog)


def _validate_program(prog: ProgramBytecode) -> None:
    if not prog.functions:
        raise BytecodeFormatError("Invalid .sumac file: no functions")
    if prog.entry < 0 or prog.entry >= len(prog.functions):
        raise BytecodeFormatError(
            f"Invalid .sumac file: entry index {prog.entry} outside function table"
        )
    _validate_metadata(prog)
    for index, fn in enumerate(prog.functions):
        context = f"function[{index}] {fn.name}"
        _validate_function_shape(fn, context)
        _validate_code(fn, prog, context)


def serialize(prog: ProgramBytecode) -> bytes:
    """Serialize a ProgramBytecode to bytes."""
    parts = []

    # Header
    parts.append(MAGIC)
    parts.append(struct.pack("<I", VERSION))
    parts.append(struct.pack("<I", prog.entry))

    # Global constants
    const_data = _encode_constants(prog.constants)
    parts.append(struct.pack("<I", len(const_data)))
    parts.append(const_data)

    # Classes info (JSON)
    class_json = _json_bytes(prog.classes, "classes")
    parts.append(struct.pack("<I", len(class_json)))
    parts.append(class_json)

    # Enums info (JSON)
    enum_json = _json_bytes(prog.enums, "enums")
    parts.append(struct.pack("<I", len(enum_json)))
    parts.append(enum_json)

    # Python imports info (JSON)
    py_import_json = _json_bytes(prog.py_imports, "Python imports")
    parts.append(struct.pack("<I", len(py_import_json)))
    parts.append(py_import_json)

    # Decorator init functions info (JSON)
    decorator_json = _json_bytes(prog.decorators, "decorators")
    parts.append(struct.pack("<I", len(decorator_json)))
    parts.append(decorator_json)

    # Method decorator init functions info (JSON)
    method_decorator_json = _json_bytes(prog.method_decorators, "method decorators")
    parts.append(struct.pack("<I", len(method_decorator_json)))
    parts.append(method_decorator_json)

    # Overload sets info (JSON)
    overload_json = _json_bytes(prog.overloads, "overloads")
    parts.append(struct.pack("<I", len(overload_json)))
    parts.append(overload_json)

    # Functions
    parts.append(struct.pack("<I", len(prog.functions)))
    for fn in prog.functions:
        fn_data = _encode_function(fn)
        parts.append(struct.pack("<I", len(fn_data)))
        parts.append(fn_data)

    return b"".join(parts)


def deserialize(data: bytes) -> ProgramBytecode:
    """Deserialize bytes to a ProgramBytecode."""
    reader = _ByteReader(data)

    magic = reader.read(4)
    if magic != MAGIC:
        raise BytecodeFormatError("Invalid .sumac file: bad magic")

    version = reader.read_u32()
    if version != VERSION:
        raise BytecodeFormatError(
            f"Unsupported .sumac version: {version}; expected {VERSION}. Recompile the source."
        )

    entry = reader.read_u32()

    # Global constants
    const_len = reader.read_u32()
    constants = _decode_constants(reader.read(const_len))

    # Classes
    classes = _read_json_section(reader, "classes")

    enums = {}
    if version >= 10:
        enums = _read_json_section(reader, "enums")

    # Python imports
    py_imports = {}
    if version >= 2:
        py_imports = _read_json_section(reader, "Python imports")

    # Decorator init functions
    decorators = {}
    if version >= 3:
        decorators = _read_json_section(reader, "decorators")

    method_decorators = {}
    if version >= 7:
        method_decorators = _read_json_section(reader, "method decorators")

    overloads = {}
    if version >= 8:
        overloads = _read_json_section(reader, "overloads")

    # Functions
    func_count = reader.read_u32()
    functions = []
    for _ in range(func_count):
        fn_len = reader.read_u32()
        fn = _decode_function(reader.read(fn_len), version)
        functions.append(fn)
    reader.ensure_finished()

    program = ProgramBytecode(
        functions=functions,
        constants=constants,
        classes=classes,
        enums=enums,
        py_imports=py_imports,
        decorators=decorators,
        method_decorators=method_decorators,
        overloads=overloads,
        entry=entry,
    )
    _validate_program(program)
    return program


def _encode_constants(constants: list) -> bytes:
    parts = []
    parts.append(struct.pack("<I", len(constants)))
    for c in constants:
        if isinstance(c, bool):
            parts.append(struct.pack("<B", 3))
            parts.append(struct.pack("<B", 1 if c else 0))
        elif isinstance(c, int):
            parts.append(struct.pack("<B", 0))
            parts.append(struct.pack("<q", c))  # int64
        elif isinstance(c, float):
            parts.append(struct.pack("<B", 1))
            parts.append(struct.pack("<d", c))  # float64
        elif isinstance(c, str):
            encoded = c.encode("utf-8")
            parts.append(struct.pack("<B", 2))
            parts.append(struct.pack("<I", len(encoded)))
            parts.append(encoded)
        elif c is None:
            parts.append(struct.pack("<B", 4))
        else:
            raise BytecodeFormatError(f"Cannot serialize constant: {c!r}")
    return b"".join(parts)


def _decode_constants(data: bytes) -> list:
    reader = _ByteReader(data, "constant table")

    count = reader.read_u32()
    constants = []
    for _ in range(count):
        tag = reader.read_u8()
        if tag == 0:
            constants.append(reader.read_i64())
        elif tag == 1:
            constants.append(reader.read_f64())
        elif tag == 2:
            slen = reader.read_u32()
            constants.append(_decode_text(reader.read(slen), "constant table string"))
        elif tag == 3:
            constants.append(bool(reader.read_u8()))
        elif tag == 4:
            constants.append(None)
        else:
            raise BytecodeFormatError(f"Invalid constant table: unknown constant tag {tag}")
    reader.ensure_finished()
    return constants


def _encode_function(fn: Function) -> bytes:
    parts = []
    name_bytes = fn.name.encode("utf-8")
    parts.append(struct.pack("<I", len(name_bytes)))
    parts.append(name_bytes)
    parts.append(struct.pack("<I", fn.arity))
    parts.append(struct.pack("<I", fn.locals_count))
    parts.append(struct.pack("<B", 1 if fn.is_method else 0))
    parts.append(struct.pack("<I", fn.capture_count))

    class_name = fn.class_name or ""
    cn_bytes = class_name.encode("utf-8")
    parts.append(struct.pack("<I", len(cn_bytes)))
    parts.append(cn_bytes)

    signature_json = _json_bytes(
        {
            "param_types": fn.param_types,
            "type_params": fn.type_params,
            "capture_slots": fn.capture_slots,
        },
        "function signature",
    )
    parts.append(struct.pack("<I", len(signature_json)))
    parts.append(signature_json)

    # Code uses signed ints for historical bytecode compatibility.
    code_data = struct.pack(f"<{len(fn.code)}i", *fn.code)
    parts.append(struct.pack("<I", len(fn.code)))
    parts.append(code_data)

    # Constants
    const_data = _encode_constants(fn.constants)
    parts.append(const_data)

    return b"".join(parts)


def _decode_function(data: bytes, version: int = VERSION) -> Function:
    reader = _ByteReader(data, "function record")

    name_len = reader.read_u32()
    name = _decode_text(reader.read(name_len), "function name")
    arity = reader.read_u32()
    locals_count = reader.read_u32()
    is_method = bool(reader.read_u8())
    capture_count = reader.read_u32() if version >= 7 else 0

    cn_len = reader.read_u32()
    class_name = _decode_text(reader.read(cn_len), "function class name") or None

    param_types = []
    type_params = []
    capture_slots = list(range(capture_count))
    if version >= 8:
        signature = _read_json_section(reader, "function signature")
        param_types = signature.get("param_types", [])
        type_params = signature.get("type_params", [])
        if version >= 9:
            capture_slots = signature.get("capture_slots", capture_slots)
        if not isinstance(param_types, list) or not all(
            item is None or isinstance(item, str) for item in param_types
        ):
            raise BytecodeFormatError("Invalid function signature: param_types must be a list")
        if not isinstance(type_params, list) or not all(
            isinstance(item, str) for item in type_params
        ):
            raise BytecodeFormatError("Invalid function signature: type_params must be a list")
        if not isinstance(capture_slots, list) or not all(
            isinstance(item, int) and item >= 0 for item in capture_slots
        ):
            raise BytecodeFormatError("Invalid function signature: capture_slots must be a list")

    code_count = reader.read_u32()
    code = list(struct.unpack(f"<{code_count}i", reader.read(code_count * 4)))

    constants = _decode_constants(reader.remaining())

    return Function(
        name=name,
        arity=arity,
        code=code,
        constants=constants,
        locals_count=locals_count,
        is_method=is_method,
        class_name=class_name,
        capture_count=capture_count,
        capture_slots=capture_slots,
        param_types=param_types,
        type_params=type_params,
    )
