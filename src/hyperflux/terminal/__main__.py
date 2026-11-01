import sys

if "--search-bridge" in sys.argv[1:]:
    from hyperflux.search.bridge import run_search_bridge_service

    run_search_bridge_service()
else:
    from hyperflux.terminal.app import run_terminal

    run_terminal()
