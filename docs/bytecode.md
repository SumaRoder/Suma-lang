# `.sumac` Bytecode Format

The Suma compiler emits compiled programs into `.sumac` files. This document
specifies the wire format so external tools (debuggers, viewers, alternative
runtimes) can read it without depending on the Python implementation.

All multi-byte integers are **little-endian**. Strings are UTF-8 with a u32
length prefix.

## File Layout

```
+--------------------+-----------------------------+
| Offset / Size      | Field                       |
+--------------------+-----------------------------+
| 4 bytes            | Magic: ASCII "SUMA"         |
| 4 bytes (u32)      | Version (current: 11)       |
| 4 bytes (u32)      | Entry function index        |
| u32 + bytes        | Global constants section    |
| u32 + bytes        | Classes JSON                |
| u32 + bytes        | Enums JSON          (v≥10)  |
| u32 + bytes        | Python imports JSON (v≥2)   |
| u32 + bytes        | Decorators JSON     (v≥3)   |
| u32 + bytes        | Method decorators JSON (v≥7)|
| u32 + bytes        | Overload sets JSON  (v≥8)   |
| u32 + records      | Functions table             |
+--------------------+-----------------------------+
```

Each variable-length section is preceded by a `u32` byte length. The reader
must consume exactly that many bytes before advancing.

### Header

- **Magic:** `b"SUMA"`. A mismatch raises `BytecodeFormatError("Invalid .sumac
  file: bad magic")`.
- **Version:** a `u32`. The current writer emits `11`. Readers accept only
  version `11`; recompile older `.sumac` files with the current compiler.
- **Entry:** `u32` index into the function table. The VM starts execution
  here.

### Constants section

Encodes a `list[Any]` of constants. Tagged-union encoding:

```
+--------+----------------------+
| u32    | constant count       |
+--------+----------------------+
| u8 tag | payload (per tag)    |  × count
+--------+----------------------+
```

Tags:

| Tag | Type   | Payload                          |
|-----|--------|----------------------------------|
| 0   | Int    | `i64`                            |
| 1   | Float  | `f64`                            |
| 2   | Str    | `u32` length + UTF-8 bytes       |
| 3   | Bool   | `u8` (1 = true, 0 = false)       |
| 4   | Null   | (no payload)                     |

Unknown tag → `BytecodeFormatError`.

### JSON sections

The `classes`, `enums`, `py_imports`, `decorators`, `method_decorators`, and
`overloads` sections are encoded as `u32` length followed by a UTF-8 JSON
document. Their schemas mirror the corresponding fields on
`ProgramBytecode` (see `src/suma_lang/backend/codegen/opcodes.py`).

### Functions table

```
+--------+----------------------+
| u32    | function count       |
+--------+----------------------+
| u32    | record byte length   |  × count
| bytes  | function record      |
+--------+----------------------+
```

Each function record contains, in order:

| Field                | Encoding                                    |
|----------------------|---------------------------------------------|
| `name`               | `u32` length + UTF-8 bytes                  |
| `arity`              | `u32`                                       |
| `locals_count`       | `u32`                                       |
| `is_method`          | `u8` (1 / 0)                                |
| `capture_count`      | `u32` (v ≥ 7; absent in older files → 0)    |
| `class_name`         | `u32` length + UTF-8 bytes (empty → `None`) |
| `signature`          | `u32` length + UTF-8 JSON (v ≥ 8); document has `param_types`, `type_params`, and `capture_slots` (v ≥ 9) |
| `code_count`         | `u32`                                       |
| `code`               | `code_count` × `i32` little-endian          |
| `local constants`    | Constants section (recursive, same format)  |

Code is a flat array of signed 32-bit integers: the first integer of each
instruction is the opcode, followed by zero or more argument integers
(see *Opcode reference*).

## Version history

| Version | Added                                       |
|---------|---------------------------------------------|
| 1       | Original format                             |
| 2       | Python imports JSON                         |
| 3       | Decorator init functions JSON               |
| 4–6     | Internal additions to existing sections     |
| 7       | Method decorators JSON; per-function `capture_count` |
| 8       | Overload sets JSON; per-function signature JSON |
| 9       | Per-function explicit `capture_slots` in signature JSON |
| 10      | Enums JSON section; enum construction and variant tests |
| 11      | Tuple construction opcode and tuple bytecode support |

## Errors

The reader raises `suma_lang.BytecodeFormatError` (a subclass of `ValueError`)
on every structural problem: bad magic, unsupported or stale version, truncated
data, trailing data, unknown constant tags, or values that can't be encoded.

The CLI prints these as `[Bytecode] {message}` and exits non-zero.

## Opcode reference

Opcodes are defined as a Python `IntEnum` in `opcodes.py` and assigned via
`auto()`, so numeric values reflect declaration order rather than a frozen
contract. **Don't hard-code numeric opcode values across versions.** Read
them from `Op` at the version you care about. The table below is the
declaration order at version 11.

| Group          | Opcode                       | Arguments                                              |
|----------------|------------------------------|--------------------------------------------------------|
| Stack          | `LOAD_CONST`                 | const index                                            |
|                | `LOAD_VAR` / `STORE_VAR`     | variable slot                                          |
|                | `LOAD_GLOBAL` / `STORE_GLOBAL` | const index (name)                                  |
|                | `CALL_GLOBAL`                | `(nargs << 16) \| func_idx`                            |
|                | `LOAD_TRUE` / `LOAD_FALSE` / `LOAD_NULL` | —                                          |
|                | `LOAD_THIS` / `LOAD_IT` / `SET_IT` | —                                                |
|                | `POP` / `DUP`                | —                                                      |
| Arithmetic     | `ADD` `SUB` `MUL` `DIV` `MOD` `NEG` | —                                               |
| Bitwise        | `BIT_AND` `BIT_OR` `BIT_XOR` `BIT_NOT` `SHL` `SHR` | —                                |
| Logic          | `NOT` `AND` `OR`             | —                                                      |
| Comparison     | `EQ` `NE` `GT` `LT` `GE` `LE`| —                                                      |
| Control flow   | `JUMP` / `JUMP_IF_FALSE` / `JUMP_IF_TRUE` | absolute code offset                      |
| Functions      | `CALL`                       | nargs                                                  |
|                | `RETURN`                     | —                                                      |
|                | `LOAD_FUNC`                  | function index                                         |
| Data           | `MAKE_LIST`                  | element count                                          |
|                | `MAKE_OK` / `MAKE_ERR`       | —                                                      |
|                | `MAKE_ENUM`                  | const index (`"Enum.Variant"`), payload count          |
|                | `MAKE_RANGE`                 | 1 if inclusive, else 0                                 |
|                | `MAKE_TUPLE`                 | element count                                          |
|                | `INDEX` / `SET_INDEX`        | —                                                      |
|                | `SLICE`                      | bitmask: 1 = has_start, 2 = has_end                    |
|                | `MEMBER` / `SET_MEMBER`      | const index (member name)                              |
|                | `MAKE_OBJECT`                | const index (class name), constructor arg count        |
|                | `MAKE_LAMBDA`                | function index                                         |
| Matching       | `IS_OK` / `IS_ERR` / `UNWRAP_OK` | —                                                  |
|                | `IS_ENUM_VARIANT`            | const index (`"Enum.Variant"`)                        |
| I/O            | `PRINT`                      | —                                                      |
| Misc           | `NOP` / `HALT`               | —                                                      |
| Superinstructions (optimizer-emitted) | `JUMP_IF_VAR_CMP`   | left slot, right slot, cmp code, target           |
|                | `JUMP_IF_VAR_CONST_CMP`      | left slot, const index, cmp code, target               |
|                | `INPLACE_VAR_VAR`            | target slot, rhs slot, binary opcode                   |
|                | `INPLACE_VAR_CONST`          | target slot, const index, binary opcode                |
|                | `TAIL_CALL_GLOBAL`           | `(nargs << 16) \| func_idx`                            |
|                | `LOOP_GENERIC`               | variable: condition descriptor + in-place ops          |
