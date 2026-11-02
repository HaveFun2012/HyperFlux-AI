"""Find and stop child processes on Windows.

koboldcpp.exe is a PyInstaller "onefile" program: the process we start is only a
launcher that unpacks ~1 GB into %TEMP% and runs the real server as a child.
Killing just the launcher leaves the server running (holding the model in RAM and
port 5001) and leaves the unpacked folder behind. Stopping the child first lets the
launcher exit by itself and clean up.
"""

import ctypes
import os
from ctypes import wintypes

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_TERMINATE = 0x0001
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _parent_map():
    """Return {pid: parent_pid} for every running process."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        return {}
    parents = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def descendant_pids(pid):
    """PIDs of all children, grandchildren, ... of pid (deepest first)."""
    if os.name != "nt" or not pid:
        return []
    parents = _parent_map()
    found = []
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        children = [child for child, parent in parents.items() if parent == current and child != current]
        found.extend(children)
        frontier.extend(children)
    return list(reversed(found))


def terminate_pid(pid):
    """Force-stop one process. Returns True if the stop request was accepted."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)
