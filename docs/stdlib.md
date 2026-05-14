# Suma-lang Standard Library

The stdlib lives in the `stdlib/` directory. Import modules with `import "module_name"`.

## Built-in Functions

These come with the compiler, no import needed.

**Type conversion:**
- `to_str(x)` — anything to string
- `to_int(x)` — string/number to Int
- `to_float(x)` — string/number to Float
- `to_bool(x)` — truthy/falsy conversion

**IO:**
- `print(msg)` — writes to stdout

**Constructors:**
- `List(...)` — create a list with elements
- `Ok(value)` — wrap success value
- `Err(error)` — wrap error value

**Result helpers:**
- `is_ok(result)` — check if Ok
- `is_err(result)` — check if Err
- `unwrap(result)` — get value, panic on Err
- `unwrap_or(result, default)` — get value or fallback
- `parse_int(s)` — parse string to Int, returns `R<Int, Str>`

**Misc:**
- `len(x)` — length of string/list
- `type_of(x)` — type name as string
- `panic(msg)` — abort with message
- `assert(cond, msg?)` — assert something is true

## core.suma

Located at `stdlib/core.suma`.

Some useful utilities for working with integers and validation.

`is_even(n: Int): Bool` — returns true if divisible by 2.

`is_odd(n: Int): Bool` — returns true if not divisible by 2.

`clamp(n: Int, low: Int, high: Int): Int` — constrains a value between bounds. If below low, returns low. If above high, returns high. Otherwise returns n.

`max_int(a: Int, b: Int): Int` — the larger of two values.

`min_int(a: Int, b: Int): Int` — the smaller of two values.

`repeat_str(s: Str, count: Int): Str` — concatenates the string count times.

`require_positive(n: Int)` — validates that a number is positive (> 0). Returns `Ok(n)` if valid, `Err("expected positive integer")` otherwise. Useful for input validation:

```suma
result = require_positive(user_input)
result -> {
    Ok = process(it)
    Err = print("Invalid: " + it)
}
```

## math.suma

Located at `stdlib/math.suma`.

Basic math operations for integers.

`abs_int(n: Int): Int` — absolute value.

`pow_int(base: Int, exp: Int): Int` — exponentiation. Handles zero exponent (returns 1) and negative exponent (not supported, don't do it).

`gcd_int(a: Int, b: Int): Int` — greatest common divisor using Euclid's algorithm.

`lcm_int(a: Int, b: Int): Int` — least common multiple. Returns 0 if either input is 0.

`factorial_int(n: Int): Int` — n! for non-negative integers.

`fib_int(n: Int): Int` — nth Fibonacci number. fib_int(0) returns 0, fib_int(1) returns 1.

## list.suma

Located at `stdlib/list.suma`.

Working with lists.

`list_sum(items: List): Int` — adds up all elements. Empty list returns 0.

`list_product(items: List): Int` — multiplies all elements. Empty list returns 1.

`list_max(items: List): Int` — largest element. Empty list returns 0.

`list_min(items: List): Int` — smallest element. Empty list returns 0.

`list_push_range(items: List, start: Int, end: Int): Int` — appends all integers from start to end (inclusive), returns final list size.

## json.suma

Located at `stdlib/json.suma`.

JSON serialization and parsing.

`to_json(value: Any): R` — rejects dynamic JSON conversion in static mode. Use typed helpers instead.

`json_pretty(value: Any): R` — same behavior as `to_json` in static mode.

`to_json_str(value: Str): R`, `to_json_int(value: Int): R`, `to_json_float(value: Float): R`, `to_json_bool(value: Bool): R`, `to_json_null(): R` — typed JSON serialization helpers.

`from_json(json_str: Str): R` — currently returns the input string; dynamic JSON parsing is not supported under static `Any` semantics.

`json_object(): JsonObject` — creates an empty JSON object you can add keys to.

`json_escape(s: Str): Str` — escapes special characters in a string for JSON.

### JsonObject

A simple key-value container:

```suma
obj: JsonObject = json_object()
obj.put("name", "Alice")
obj.put("age", "25")

obj.get("name")    // "Alice"
obj.has("age")     // true
obj.size()         // 2
obj.keys()         // List("name", "age")
```

`JsonObject` stores string values. Use typed conversion helpers before inserting non-string data.

## Putting It Together

Here's a full example using several modules:

```suma
import "core"
import "math"
import "list"

pub main(): Int {
    numbers: List = List(3, 1, 4, 1, 5, 9, 2, 6)
    
    print("Sum: " + to_str(list_sum(numbers)))
    print("Max: " + to_str(list_max(numbers)))
    print("GCD: " to_str(gcd_int(12, 8)))
    print("5! = " + to_str(factorial_int(5)))
    print("Fib(10) = " + to_str(fib_int(10)))
    
    require_positive(-5) -> {
        Ok = print("Valid: " + to_str(it)),
        Err = print("Rejected: " + it)
    }
    
    return 0
}
```
