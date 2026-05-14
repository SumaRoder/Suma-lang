from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SDK_SRC = _ROOT / "SecPluginPySdk" / "src"
if _SDK_SRC.is_dir():
    sdk_path = str(_SDK_SRC)
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)

_plugins: dict[str, Any] = {}

_pending_handlers: list[tuple[str, Any]] = []
_active_senders: dict[int, Any] = {}


def _make_async_handler(plugin, func):
    async def handler(messenger):
        _active_senders[id(messenger)] = plugin.get_sender()
        try:
            return func(messenger)
        finally:
            _active_senders.pop(id(messenger), None)

    handler.__name__ = getattr(func, "__name__", "suma_handler")
    return handler


def on_msg(regex: str):
    def decorate(func):
        _pending_handlers.append((regex, func))
        return func

    return decorate


def sdk_source_path() -> str:
    return str(_SDK_SRC)


def sdk_status() -> str:
    try:
        import secplugin

        return f"secplugin {secplugin.__version__} loaded from {secplugin.__file__}"
    except Exception as exc:
        return f"secplugin unavailable: {exc}"


def dependency_status() -> str:
    try:
        import websockets  # type: ignore

        version = getattr(websockets, "__version__", "unknown")
        return f"websockets {version} available"
    except Exception as exc:
        return f"websockets unavailable: {exc}"


def create_echo_plugin(url: str, pid: str, name: str, token: str, regex: str, reply: str) -> str:
    try:
        from secplugin import Plugin
    except Exception as exc:
        return f"ERROR: {exc}"

    plugin = Plugin(
        url=url,
        pid=pid,
        name=name,
        token=token,
        reload=False,
        log_path=str(_ROOT / "secplugin_suma.log"),
    )
    sender = plugin.get_sender()

    @plugin.on_msg(regex)
    async def _echo(messenger):
        await sender.send_msg(messenger, reply)

    for pending_regex, func in _pending_handlers:
        plugin.on_msg(pending_regex)(_make_async_handler(plugin, func))

    handle = f"plugin-{len(_plugins) + 1}"
    _plugins[handle] = plugin
    return handle


def send_msg(messenger, text: str) -> str:
    sender = _active_senders.get(id(messenger))
    if sender is None:
        return "ERROR: send_msg() must be called inside an on_msg handler"
    try:
        sender.send_ws_msg.__self__  # keep linters quiet about dynamic SDK objects
    except Exception:
        pass
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        loop.create_task(sender.send_msg(messenger, text))
        return "queued"
    except Exception as exc:
        return f"ERROR: {exc}"


def describe_plugin(handle: str) -> str:
    if handle.startswith("ERROR:"):
        return handle
    plugin = _plugins.get(handle)
    if plugin is None:
        return f"ERROR: unknown plugin handle '{handle}'"
    return (
        f"handle={handle}, running={plugin.running()}, closed={plugin.closed()}, "
        f"timeout={plugin.get_local_send_wait_timeout()}"
    )


def set_local_timeout(handle: str, timeout: float) -> str:
    if handle.startswith("ERROR:"):
        return handle
    plugin = _plugins.get(handle)
    if plugin is None:
        return f"ERROR: unknown plugin handle '{handle}'"
    plugin.set_local_send_wait_timeout(timeout)
    return f"timeout={plugin.get_local_send_wait_timeout()}"


def run_plugin(handle: str) -> str:
    if handle.startswith("ERROR:"):
        return handle
    plugin = _plugins.get(handle)
    if plugin is None:
        return f"ERROR: unknown plugin handle '{handle}'"
    plugin.run()
    return "stopped"
