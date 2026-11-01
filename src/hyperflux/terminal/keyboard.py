"""Read a message from the terminal (Enter sends, Ctrl+Enter adds a new line on Windows)."""

import ctypes
import os
import sys
from ctypes import wintypes

from rich.text import Text

from hyperflux.terminal.ui import UI, console


def _read_simple_line():
    UI.show_composer()
    try:
        return console.input("")
    finally:
        console.print()


def read_user_input():
    if os.name != "nt" or not sys.stdin.isatty():
        return _read_simple_line()

    class KeyEventRecord(ctypes.Structure):
        _fields_ = [
            ("key_down", wintypes.BOOL),
            ("repeat_count", wintypes.WORD),
            ("virtual_key_code", wintypes.WORD),
            ("virtual_scan_code", wintypes.WORD),
            ("unicode_char", wintypes.WCHAR),
            ("control_key_state", wintypes.DWORD),
        ]

    class EventRecord(ctypes.Union):
        _fields_ = [("key_event", KeyEventRecord)]

    class InputRecord(ctypes.Structure):
        _anonymous_ = ("event",)
        _fields_ = [("event_type", wintypes.WORD), ("event", EventRecord)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [wintypes.DWORD]
    get_std_handle.restype = wintypes.HANDLE
    get_console_mode = kernel32.GetConsoleMode
    get_console_mode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_console_mode.restype = wintypes.BOOL
    read_console_input = kernel32.ReadConsoleInputW
    read_console_input.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(InputRecord),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    read_console_input.restype = wintypes.BOOL

    input_handle = get_std_handle(wintypes.DWORD(-10))
    if not input_handle or input_handle == wintypes.HANDLE(-1).value:
        return _read_simple_line()
    console_mode = wintypes.DWORD()
    if not get_console_mode(input_handle, ctypes.byref(console_mode)):
        return _read_simple_line()

    value = []
    UI.show_composer()
    while True:
        record = InputRecord()
        events_read = wintypes.DWORD()
        if not read_console_input(
            input_handle, ctypes.byref(record), 1, ctypes.byref(events_read)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not events_read.value or record.event_type != 0x0001:
            continue

        key = record.key_event
        if not key.key_down:
            continue

        control_pressed = bool(key.control_key_state & 0x000C)
        if key.virtual_key_code == 0x0D:
            if control_pressed:
                value.append("\n")
                console.print()
                console.print(Text("... ", style="dim"), end="")
            else:
                console.print()
                return "".join(value)
            continue

        if key.virtual_key_code == 0x08:
            if value and value[-1] == "\n":
                value.pop()
                previous_line = "".join(value).rsplit("\n", 1)[-1]
                prefix = "... " if "\n" in value else "❯ "
                console.file.write("\r\x1b[2K\x1b[1A\r\x1b[2K")
                console.file.flush()
                console.print(Text(prefix, style="user"), end="")
                if previous_line:
                    console.print(Text(previous_line, style="white"), end="")
            elif value:
                value.pop()
                console.file.write("\b \b")
                console.file.flush()
            continue

        character = key.unicode_char
        if character and character >= " " and character != "\x7f":
            value.append(character)
            console.print(Text(character), end="")
