"""Stop the engine when the desktop process that started it has exited.

The operating-system project lock is released when this process exits.
A stored pid in project.lock.json is not used here. The owner is an open
process handle captured while that process is still alive, so a later reuse
of the same pid does not keep this process running.
"""
from __future__ import annotations

import os
import threading


def exit_when_owner_exits() -> None:
    raw = os.environ.get("AMIX_OWNER_PID", "").strip()
    if os.name != "nt" or not raw:
        return
    try:
        owner = int(raw)
    except ValueError:
        return
    if owner <= 0:
        return
    handle = _open_owner(owner)
    if not handle:
        return

    def _wait() -> None:
        _wait_forever(handle)
        os._exit(0)

    threading.Thread(target=_wait, name="amix-owner", daemon=True).start()


def _open_owner(owner: int) -> int:
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    return int(kernel.OpenProcess(synchronize, False, owner) or 0)


def _wait_forever(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
