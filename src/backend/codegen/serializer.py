"""Serializer for .sumac bytecode files."""

from __future__ import annotations

import json
import struct

from src.backend.codegen.opcodes import Function, ProgramBytecode

MAGIC = b"SUMA"
VERSION = 6


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

    # Functions
    parts.append(struct.pack("<I", len(prog.functions)))
    for fn in prog.functions:
        fn_data = _encode_function(fn)
        parts.append(struct.pack("<I", len(fn_data)))
        parts.append(fn_data)

    return b"".join(parts)


def deserialize(data: bytes) -> ProgramBytecode:
    """Deserialize bytes to a ProgramBytecode."""
    offset = 0

    def read(n: int) -> bytes:
        nonlocal offset
        chunk = data[offset : offset + n]
        offset += n
        return chunk

    def read_u32() -> int:
        return struct.unpack("<I", read(4))[0]

    magic = read(4)
    if magic != MAGIC:
        raise ValueError("Invalid .sumac file: bad magic")

    version = read_u32()
    if version not in (1, 2, 3, 4, 5, VERSION):
        raise ValueError(f"Unsupported .sumac version: {version}")

    entry = read_u32()

    # Global constants
    const_len = read_u32()
    constants = _decode_constants(read(const_len))

    # Classes
    class_len = read_u32()
    classes = json.loads(read(class_len).decode("utf-8"))

    # Python imports
    py_imports = {}
    if version >= 2:
        py_import_len = read_u32()
        py_imports = json.loads(read(py_import_len).decode("utf-8"))

    # Decorator init functions
    decorators = {}
    if version >= 3:
        decorator_len = read_u32()
        decorators = json.loads(read(decorator_len).decode("utf-8"))

    # Functions
    func_count = read_u32()
    functions = []
    for _ in range(func_count):
        fn_len = read_u32()
        fn = _decode_function(read(fn_len))
        functions.append(fn)

    return ProgramBytecode(
        functions=functions,
        constants=constants,
        classes=classes,
        py_imports=py_imports,
        decorators=decorators,
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
            raise ValueError(f"Cannot serialize constant: {c!r}")
    return b"".join(parts)


def _decode_constants(data: bytes) -> list:
    offset = 0

    def read(n: int) -> bytes:
        nonlocal offset
        chunk = data[offset : offset + n]
        offset += n
        return chunk

    def read_u32() -> int:
        return struct.unpack("<I", read(4))[0]

    count = read_u32()
    constants = []
    for _ in range(count):
        tag = struct.unpack("<B", read(1))[0]
        if tag == 0:
            constants.append(struct.unpack("<q", read(8))[0])
        elif tag == 1:
            constants.append(struct.unpack("<d", read(8))[0])
        elif tag == 2:
            slen = read_u32()
            constants.append(read(slen).decode("utf-8"))
        elif tag == 3:
            constants.append(bool(struct.unpack("<B", read(1))[0]))
        elif tag == 4:
            constants.append(None)
    return constants


def _encode_function(fn: Function) -> bytes:
    parts = []
    name_bytes = fn.name.encode("utf-8")
    parts.append(struct.pack("<I", len(name_bytes)))
    parts.append(name_bytes)
    parts.append(struct.pack("<I", fn.arity))
    parts.append(struct.pack("<I", fn.locals_count))
    parts.append(struct.pack("<B", 1 if fn.is_method else 0))

    class_name = fn.class_name or ""
    cn_bytes = class_name.encode("utf-8")
    parts.append(struct.pack("<I", len(cn_bytes)))
    parts.append(cn_bytes)

    # Code (signed int to support -1 sentinel for LOAD_VAR global)
    code_data = struct.pack(f"<{len(fn.code)}i", *fn.code)
    parts.append(struct.pack("<I", len(fn.code)))
    parts.append(code_data)

    # Constants
    const_data = _encode_constants(fn.constants)
    parts.append(const_data)

    return b"".join(parts)


def _decode_function(data: bytes) -> Function:
    offset = 0

    def read(n: int) -> bytes:
        nonlocal offset
        chunk = data[offset : offset + n]
        offset += n
        return chunk

    def read_u32() -> int:
        return struct.unpack("<I", read(4))[0]

    name_len = read_u32()
    name = read(name_len).decode("utf-8")
    arity = read_u32()
    locals_count = read_u32()
    is_method = bool(struct.unpack("<B", read(1))[0])

    cn_len = read_u32()
    class_name = read(cn_len).decode("utf-8") or None

    code_count = read_u32()
    code = list(struct.unpack(f"<{code_count}i", read(code_count * 4)))

    constants = _decode_constants(data[offset:])

    return Function(
        name=name,
        arity=arity,
        code=code,
        constants=constants,
        locals_count=locals_count,
        is_method=is_method,
        class_name=class_name,
    )
