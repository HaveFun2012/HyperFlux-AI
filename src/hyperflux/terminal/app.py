"""Terminal chat loop."""

from rich.text import Text

from hyperflux.config import Config
from hyperflux.core.engine import HyperFluxEngine
from hyperflux.search.bridge import search_bridge_is_running, start_search_bridge
from hyperflux.terminal.keyboard import read_user_input
from hyperflux.terminal.ui import UI, console

HELP_TEXT = (
    "[bold]Commands[/bold]\n"
    "[user]/help[/user]  Show this help\n"
    "[user]/read <path> [request][/user]  Read a text file inside the workspace\n"
    "[user]/temp <0-2>[/user]  Set generation temperature\n"
    f"[user]/length <1-{Config.MAX_MAX_LENGTH}>[/user]  Set maximum output tokens (thinking + answer)\n"
    "[user]/model flash|apex|horizon[/user]  Switch model: Flash 1 (fast), Apex 1 (standard), Horizon 1 (deep thinking)\n"
    "[user]/think on|off[/user]  Turn thinking on or off (Apex 1)\n"
    "[user]/thinking[/user]  Show the model's thinking for the last answer\n"
    "[user]/sys[/user]  Show model, context, and generation status\n"
    "[user]/search <query>[/user]  Search the web using the local search service\n"
    "[user]/restart-ui[/user]  Refresh the UI and keep this session\n"
    "[dim]Ctrl+Enter adds a line; Backspace at a line start removes it; Enter sends.[/dim]\n"
    "[user]/exit[/user]  Quit HyperFlux\n\n"
    "[dim]Example: /read \"hyperflux/core/engine.py\" Find the bug[/dim]\n"
    "[dim]Normal messages are sent to your local model.[/dim]"
)


def _start_bridge(engine):
    address = f"{Config.SEARCH_BRIDGE_HOST}:{Config.SEARCH_BRIDGE_PORT}"
    try:
        bridge = start_search_bridge(
            engine,
            Config.SEARCH_BRIDGE_HOST,
            Config.SEARCH_BRIDGE_PORT,
            Config.SEARCH_RESULT_COUNT,
        )
    except OSError as error:
        if search_bridge_is_running(Config.SEARCH_BRIDGE_HOST, Config.SEARCH_BRIDGE_PORT):
            console.print(Text(f"Web search bridge already running on {address}", style="dim"))
        else:
            console.print(
                Text(f"Web search bridge unavailable on {address}: {error}", style="error")
            )
        return None
    console.print(Text(f"Web search bridge ready on {address}", style="dim"))
    return bridge


def run_terminal():
    engine = HyperFluxEngine()
    transcript = []
    search_bridge = _start_bridge(engine)
    UI.header(engine.model_name)

    while True:
        try:
            user_input = read_user_input().rstrip("\r\n")
            command = user_input.strip().lower()
            if not command:
                continue
            if command in {"exit", "quit", "/exit", "/quit"}:
                console.print("\n[dim]Session terminated.[/dim]\n")
                break
            if command == "/restart-ui":
                UI.restart(engine.model_name, transcript)
                continue
            if command == "/help":
                console.print(HELP_TEXT)
                continue

            UI.hide_composer()
            UI.restart(engine.model_name, transcript)
            UI.render_user_message(user_input)
            response = engine.process_chat(user_input)
            if not engine.response_rendered_live:
                UI.render_assistant_response(response)
            transcript.append((user_input, response))

        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[dim]Session terminated.[/dim]\n")
            break
    if search_bridge is not None:
        search_bridge.shutdown()
        search_bridge.server_close()
