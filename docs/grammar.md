# Suma-lang Grammar

A reference EBNF for the surface syntax accepted by
`src/suma_lang/frontend/parser/parser.py` (+ `_expressions.py`). The grammar
here matches the recursive-descent parser, not a formal LR/LL specification —
ambiguities are resolved by reading top-to-bottom, longest-prefix-wins, and the
explicit precedence table at the end.

Conventions:

- `UPPERCASE` names are token kinds from `frontend/lexer/token_types.py`.
- `lowercase` names are non-terminals defined in this file.
- `|` separates alternatives, `( … )` groups, `[ … ]` is optional, `{ … }` is
  zero-or-more. Literal terminals are written `"like this"`.
- Semicolons (`SEM`) are optional after most statements; the grammar omits
  trailing `[ ";" ]` for readability.

## Top level

```ebnf
program          ::= { top_level } EOF
top_level        ::= { decorator } [ "pub" | "pri" ] (
                       import_decl
                     | [ "const" ] enum_decl
                     | class_decl
                     | function_decl
                     | var_decl
                     )

decorator        ::= "@" expression
import_decl      ::= "import" STRING
```

## Declarations

```ebnf
enum_decl        ::= "enum" IDENT "{" enum_variant { ( "," | ";" ) enum_variant } "}"
enum_variant     ::= IDENT [ "(" type_name ")" ]

class_decl       ::= IDENT [ type_params ] [ ":" type_name ] "{" { class_member } "}"
class_member     ::= { decorator }
                     [ "pub" | "pri" ]
                     [ "static" ]
                     ( init_decl | getter_decl | setter_decl | var_decl | function_decl )
init_decl        ::= "init" params block
getter_decl      ::= "get" IDENT block
setter_decl      ::= "set" IDENT "(" IDENT ")" block

function_decl    ::= IDENT [ type_params ] params [ ":" type_name ] block
var_decl         ::= IDENT [ ":" type_name ] [ "=" expression ]

type_params      ::= "<" IDENT { "," IDENT } ">"
params           ::= "(" [ param { "," param } ] ")"
param            ::= IDENT [ ":" type_name ] [ "=" expression ]
```

## Type names

```ebnf
type_name        ::= IDENT [ "<" type_name { "," type_name } ">" ]
                   | "(" type_name { "," type_name } ")"        (* tuple type *)
```

Built-in base names recognized by the analyzer: `Int`, `Float`, `Str`, `Bool`,
`List`, `Tuple`, `R` (alias for `R<value, error>`), `Function`, `Any`, plus any
user-declared class or enum.

## Statements

```ebnf
block            ::= "{" { statement } "}"

statement        ::= return_stmt
                   | if_stmt
                   | while_stmt
                   | for_in_stmt
                   | loop_stmt
                   | break_stmt
                   | continue_stmt
                   | throw_stmt
                   | try_catch_stmt
                   | block                                      (* nested block *)
                   | destructure_assign_stmt
                   | local_var_decl
                   | expression_stmt

return_stmt      ::= "return" [ expression ]
if_stmt          ::= "if" condition block
                     { "elif" condition block }
                     [ "else" block ]
while_stmt       ::= "while" condition block
for_in_stmt      ::= "for" IDENT "in" expression block
loop_stmt        ::= "loop" block
break_stmt       ::= "break"
continue_stmt    ::= "continue"
throw_stmt       ::= "throw" expression
try_catch_stmt   ::= "try" block
                     [ "catch" "(" IDENT ")" block ]
                     [ "finally" block ]

condition        ::= "(" expression ")" | expression

destructure_assign_stmt ::= "(" IDENT { "," IDENT } ")" "=" expression
local_var_decl   ::= IDENT ":" type_name [ "=" expression ]     (* must have initializer in local scope *)
expression_stmt  ::= expression
```

Notes:

- `local_var_decl` is selected by the parser when it sees `ID :` at statement
  start. The "must have initializer" rule is enforced after parsing.
- A bare `expression_stmt` whose expression is `IDENT "=" expression` is **not**
  a re-assignment to an outer binding — it declares a new local in the current
  block. Use `@IDENT = expression` to update an outer binding. See
  [`docs/language.md`](language.md#variables).

## Expressions

The expression grammar is a Pratt-style precedence cascade. Each row calls down
into the next; the topmost is loosest, the bottom-most is tightest:

```ebnf
expression       ::= assignment
assignment       ::= range [ assign_op assignment ]
assign_op        ::= "=" | "+=" | "-=" | "*=" | "/=" | "%="
range            ::= elvis [ ( ".." | "..=" ) elvis ]
elvis            ::= or [ ( "else" | "??" ) elvis ]             (* "else" requires allow_result_else *)
or               ::= and       { "||" and }
and              ::= bit_or    { "&&" bit_or }
bit_or           ::= bit_xor   { "|"  bit_xor }
bit_xor          ::= bit_and   { "^"  bit_and }
bit_and          ::= equality  { "&"  equality }
equality         ::= comparison { ( "==" | "!=" ) comparison }
comparison       ::= shift     { ( "<" | "<=" | ">" | ">=" | "is" ) shift }
shift            ::= additive  { ( "<<" | ">>" ) additive }
additive         ::= multiplicative { ( "+" | "-" ) multiplicative }
multiplicative   ::= unary     { ( "*" | "/" | "%" ) unary }

unary            ::= ( "++" | "--" ) unary
                   | ( "!" | "-" | "~" ) unary
                   | postfix
postfix          ::= primary { postfix_op }
postfix_op       ::= "(" [ expression { "," expression } ] ")"  (* call *)
                   | "[" index_or_slice "]"
                   | "." IDENT
                   | "?" "." IDENT [ "(" [ expression { "," expression } ] ")" ]   (* safe member / call *)
                   | "?"                                          (* Result propagate *)
                   | "++" | "--"
index_or_slice   ::= expression                                  (* index *)
                   | [ expression ] ":" [ expression ]            (* slice *)

primary          ::= if_expr
                   | match_expr
                   | "@" IDENT                                   (* outer-binding reference *)
                   | INT | FLOAT | STRING | RAW_STRING
                   | "true" | "false" | "null"
                   | "this" | "it"
                   | "Ok" "(" expression ")"
                   | "Err" "(" expression ")"
                   | "List" "(" [ expression { "," expression } ] ")"
                   | lambda_expr
                   | tuple_literal
                   | IDENT
                   | "(" expression ")"
```

### Control-flow and pattern expressions

```ebnf
if_expr          ::= "if" condition block
                     { "elif" condition block }
                     [ "else" block ]

match_expr       ::= "match" expression "{" { match_arm } "}"
match_arm        ::= match_pattern [ match_binding ] "=>" arm_body
arm_body         ::= block | expression
match_binding    ::= "(" IDENT ")"
match_pattern    ::= "is" type_name                              (* type test *)
                   | literal                                     (* literal value *)
                   | IDENT "." IDENT                             (* enum variant *)
                   | "Ok" | "Err"                                (* Result tag, binds `it` *)
                   | "_"                                         (* wildcard *)
                   | IDENT                                       (* literal-identifier match *)

lambda_expr      ::= lambda_params [ ":" type_name ] "->" lambda_body
lambda_params    ::= "(" [ lambda_param { "," lambda_param } ] ")"
lambda_param     ::= IDENT [ ":" type_name ]
lambda_body      ::= block
                   | "return" expression | if_expr | loop_stmt
                   | "break" | "continue" | "throw" expression | try_catch_stmt
                   | expression

tuple_literal    ::= "(" expression "," expression { "," expression } ")"
```

### String literals & interpolation

`STRING` tokens (double-quoted) participate in interpolation: any `{expression}`
embedded in the literal is parsed as an `InterpolatedStringExpr` containing
arbitrary expressions. `RAW_STRING` tokens (`r"..."` / single-quoted backtick
strings, see the lexer) are passed through verbatim.

## Precedence summary (highest first)

| Level | Operators                                                  | Associativity |
|-------|------------------------------------------------------------|---------------|
| 1     | Postfix: call `f(...)`, index `a[i]`, member `a.b`,         | Left          |
|       | safe `?.`, propagate `?`, postfix `++` / `--`              |               |
| 2     | Prefix: `++x`, `--x`, `!x`, `-x`, `~x`                     | Right         |
| 3     | `*` `/` `%`                                                | Left          |
| 4     | `+` `-`                                                    | Left          |
| 5     | `<<` `>>`                                                  | Left          |
| 6     | `<` `<=` `>` `>=` `is`                                     | Left          |
| 7     | `==` `!=`                                                  | Left          |
| 8     | `&`                                                        | Left          |
| 9     | `^`                                                        | Left          |
| 10    | `\|`                                                       | Left          |
| 11    | `&&`                                                       | Left          |
| 12    | `\|\|`                                                     | Left          |
| 13    | `else` (Elvis-on-Result), `??` (null-coalesce)             | Right         |
| 14    | `..` `..=` (range)                                         | Non-assoc     |
| 15    | `=` `+=` `-=` `*=` `/=` `%=` (assignment family)           | Right         |

`else` only participates in expression position when the parser allows
`allow_result_else=True` — `if`/`while`/`elif` conditions disable it so the
trailing `else` lexically binds to the surrounding statement.

## Lexical notes

- Comments: `// …` to end of line; `/* … */` block comments (see `tokenizer.py`).
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`. Names `Ok`, `Err`, `List`, `it`, `this`
  are syntactically primaries when they appear at expression head; they are not
  reserved as identifiers in other positions.
- Keywords (reserved): `pub pri const import enum class init static get set
  if elif else while for in loop break continue return throw try catch finally
  match true false null is this @ static`. The lexer also recognizes `static`
  as a hard keyword inside class bodies.
- Numeric literals: `INT` accepts `0`, `123`, `0x...`, `0o...`, `0b...` per
  `int(..., 0)` semantics; `FLOAT` uses `float(...)`.

## Maintaining this file

When you change the parser, search for the new method name in this document and
update the corresponding production. The recursive-descent methods that drive
each production (in file order) are:

- `parser._parse_top_level`, `_parse_class`, `_parse_function_decl`,
  `_parse_var_decl`, `_parse_block`, `_parse_statement`, `_parse_while`,
  `_parse_for_in`, `_parse_loop`, `_parse_match_expr`, `_parse_primary`,
  `_parse_lambda`.
- `_expressions._parse_assignment` through `_parse_postfix` (the precedence
  cascade in the table above).
