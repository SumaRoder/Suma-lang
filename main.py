"""Compatibility shim for the Suma-lang CLI.

The installable console script lives in `src.cli`. Importing `main` still
returns the same module object so existing tests and local scripts can keep
using `from main import compile_source`.

---

Suma-lang CLI 的兼容性垫片。

可安装的控制台脚本位于 `src.cli`。导入 `main` 仍然
返回相同的模块对象，因此现有的测试和本地脚本可以继续
使用 `from main import compile_source`。
"""

from __future__ import annotations

import sys

from src import cli as _cli

sys.modules[__name__] = _cli

if __name__ == "__main__":
    _cli.main()
