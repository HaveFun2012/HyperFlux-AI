"""Terminal theme, shared console, and rendering helpers."""

import ctypes
import os
from ctypes import wintypes

from rich import box
from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from hyperflux.core.formatting import render_math_for_terminal

custom_theme = Theme({
    "brand": "bold #A78BFA",
    "dim": "#94A3B8",
    "user": "bold #67E8F9",
    "assistant": "#E5E7EB",
    "code": "#67E8F9",
    "success": "bold #34D399",
    "error": "bold #F87171",
})

console = Console(theme=custom_theme)
THINKING_PREVIEW_LINES = 12


class UI:
    @staticmethod
    def header(model_name):
        """Render a compact terminal header without full-width boxes."""
        title = Text()
        title.append(" ✦ ", style="brand")
        title.append("HyperFlux", style="bold white")
        title.append(" · HyperFlux Gen 1 Gemma4", style="dim")
        console.print(title)

        details = Text()
        details.append("  Model ", style="dim")
        details.append(model_name, style="bold #67E8F9")
        details.append(" · KoboldCPP :5001", style="dim")
        console.print(details)
        console.print(Text("  Ctrl+Enter: new line · Enter: send", style="dim"))
        console.print(Text("  /help · /sys · /search · /read · /temp · /length · /exit", style="dim"))
        console.print()

    @staticmethod
    def show_composer():
        """Place the prompt bar on the terminal's bottom row when available."""
        if os.name == "nt" and console.is_terminal:
            class Coord(ctypes.Structure):
                _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short)]

            class SmallRect(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_short),
                    ("top", ctypes.c_short),
                    ("right", ctypes.c_short),
                    ("bottom", ctypes.c_short),
                ]

            class ConsoleScreenBufferInfo(ctypes.Structure):
                _fields_ = [
                    ("size", Coord),
                    ("cursor_position", Coord),
                    ("attributes", wintypes.WORD),
                    ("window", SmallRect),
                    ("maximum_window_size", Coord),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_std_handle = kernel32.GetStdHandle
            get_std_handle.argtypes = [wintypes.DWORD]
            get_std_handle.restype = wintypes.HANDLE
            get_screen_buffer_info = kernel32.GetConsoleScreenBufferInfo
            get_screen_buffer_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ConsoleScreenBufferInfo),
            ]
            get_screen_buffer_info.restype = wintypes.BOOL

            output_handle = get_std_handle(wintypes.DWORD(-11))
            screen_info = ConsoleScreenBufferInfo()
            if output_handle and output_handle != wintypes.HANDLE(-1).value and (
                get_screen_buffer_info(output_handle, ctypes.byref(screen_info))
            ):
                if screen_info.cursor_position.y >= screen_info.window.bottom:
                    console.file.write("\r\n")
                console.file.write(f"\x1b[{console.size.height};1H")
                console.file.flush()
        else:
            console.print()
        console.print(Text("❯ ", style="user"), end="")

    @staticmethod
    def hide_composer():
        """Clear the live prompt line before generation starts."""
        console.print("\r\x1b[2K", end="")

    @staticmethod
    def render_user_message(text: str):
        prompt = Text("❯ ", style="user")
        prompt.append(text, style="white")
        console.print(prompt)

    @staticmethod
    def assistant_panel(text: str, status: str = "", thinking: str = ""):
        """Assistant turn. `thinking` streams dimmed while the model thinks; once the
        answer starts, callers drop it and pass a short "Thought for Ns" status."""
        heading = Text("✦ HyperFlux", style="bold white")
        content: list[RenderableType] = [heading]
        if status:
            content.append(Text(status, style="dim"))
        if thinking:
            # Show only the latest lines so the panel doesn't grow off-screen.
            recent = "\n".join(render_math_for_terminal(thinking).splitlines()[-THINKING_PREVIEW_LINES:])
            content.append(Text(recent, style="italic #94A3B8"))
        if text:
            # The terminal can't draw LaTeX, so show maths as plain symbols (3/4 × 2).
            text = render_math_for_terminal(text)
            content.append(Markdown(text, code_theme="monokai"))
        return Panel(
            Group(*content),
            box=box.SQUARE,
            border_style="#4B5563",
            style="on #1F2937",
            padding=(0, 1),
            expand=True,
        )

    @staticmethod
    def render_assistant_response(text: str):
        """Render the assistant turn in a square, gray-backed panel."""
        console.print()
        console.print(UI.assistant_panel(text))
        console.print()

    @staticmethod
    def restart(model_name: str, transcript):
        """Redraw the terminal UI without resetting the engine or transcript."""
        console.clear()
        UI.header(model_name)
        for user_message, assistant_response in transcript:
            UI.render_user_message(user_message)
            UI.render_assistant_response(assistant_response)

    @staticmethod
    def render_error(text):
        console.print(Text("Error: ", style="error"), end="")
        console.print(Text(text, style="error"))
