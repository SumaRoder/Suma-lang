"""Serializer for .sumac bytecode files."""

from __future__ import annotations

import json
import struct

from suma_lang.backend.codegen.opcodes import Function, ProgramBytecode

MAGIC = b"SUMA"
VERSION = 8


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
    class_json = json.dumps(prog.classes).encode("utf-8")
    parts.append(struct.pack("<I", len(class_json)))
    parts.append(class_json)

    # Python imports info (JSON)
    py_import_json = json.dumps(prog.py_imports).encode("utf-8")
    parts.append(struct.pack("<I", len(py_import_json)))
    parts.append(py_import_json)

    # Decorator init functions info (JSON)
    decorator_json = json.dumps(prog.decorators).encode("utf-8")
    parts.append(struct.pack("<I", len(decorator_json)))
    parts.append(decorator_json)

    # Method decorator init functions info (JSON)
    method_decorator_json = json.dumps(prog.method_decorators).encode("utf-8")
    parts.append(struct.pack("<I", len(method_decorator_json)))
    parts.append(method_decorator_json)

    # Overload sets info (JSON)
    overload_json = json.dumps(prog.overloads).encode("utf-8")
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
    if version not in (1, 2, 3, 4, 5, 6, 7, VERSION):
        raise BytecodeFormatError(f"Unsupported .sumac version: {version}")

    entry = reader.read_u32()

    # Global constants
    const_len = reader.read_u32()
    constants = _decode_constants(reader.read(const_len))

    # Classes
    class_len = reader.read_u32()
    classes = json.loads(reader.read(class_len).decode("utf-8"))

    # Python imports
    py_imports = {}
    if version >= 2:
        py_import_len = reader.read_u32()
        py_imports = json.loads(reader.read(py_import_len).decode("utf-8"))

    # Decorator init functions
    decorators = {}
    if version >= 3:
        decorator_len = reader.read_u32()
        decorators = json.loads(reader.read(decorator_len).decode("utf-8"))

    method_decorators = {}
    if version >= 7:
        method_decorator_len = reader.read_u32()
        method_decorators = json.loads(reader.read(method_decorator_len).decode("utf-8"))

    overloads = {}
    if version >= 8:
        overload_len = reader.read_u32()
        overloads = json.loads(reader.read(overload_len).decode("utf-8"))

    # Functions
    func_count = reader.read_u32()
    functions = []
    for _ in range(func_count):
        fn_len = reader.read_u32()
        fn = _decode_function(reader.read(fn_len), version)
        functions.append(fn)
    reader.ensure_finished()

    return ProgramBytecode(
        functions=functions,
        constants=constants,
        classes=classes,
        py_imports=py_imports,
        decorators=decorators,
        method_decorators=method_decorators,
        overloads=overloads,
        entry=entry,
    )


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
            constants.append(reader.read(slen).decode("utf-8"))
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

    signature_json = json.dumps(
        {"param_types": fn.param_types, "type_params": fn.type_params}
    ).encode("utf-8")
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
    name = reader.read(name_len).decode("utf-8")
    arity = reader.read_u32()
    locals_count = reader.read_u32()
    is_method = bool(reader.read_u8())
    capture_count = reader.read_u32() if version >= 7 else 0

    cn_len = reader.read_u32()
    class_name = reader.read(cn_len).decode("utf-8") or None

    param_types = []
    type_params = []
    if version >= 8:
        signature_len = reader.read_u32()
        signature = json.loads(reader.read(signature_len).decode("utf-8"))
        param_types = signature.get("param_types", [])
        type_params = signature.get("type_params", [])

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
        param_types=param_types,
        type_params=type_params,
    )
