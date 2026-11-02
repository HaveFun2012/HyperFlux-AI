"""Clean up Markdown the model writes before it is shown."""

import re

_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _split_row(line):
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    # "\|" is a literal pipe inside a cell.
    return [cell.strip().replace("\x01", "|") for cell in inner.replace("\\|", "\x01").split("|")]


def _is_row(line):
    return len(line) >= 3 and line.startswith("|") and line.endswith("|")


def repair_collapsed_tables(text):
    """Split one-line tables back into rows.

    Small models sometimes write a whole table on one line:
        | A | B | | :--- | :--- | | x | y |
    The run of ":---" cells gives the column count, so the rows can be rebuilt.
    Anything that doesn't fit that shape exactly is left unchanged.
    """
    repaired = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not _is_row(stripped) or not re.search(r"\|\s*\|", stripped):
            repaired.append(line)
            continue
        cells = _split_row(stripped)
        columns = run = 0
        for cell in cells:
            run = run + 1 if _SEPARATOR_CELL.match(cell) else 0
            columns = max(columns, run)
        if columns < 2 or (len(cells) + 1) % (columns + 1):
            repaired.append(line)
            continue
        rows = []
        for start in range(0, len(cells), columns + 1):
            gap = start + columns
            if gap < len(cells) and cells[gap] != "":
                rows = []
                break
            rows.append("| " + " | ".join(cells[start:gap]) + " |")
        separator_ok = len(rows) >= 2 and all(_SEPARATOR_CELL.match(c) for c in _split_row(rows[1]))
        repaired.append("\n".join(rows) if separator_ok else line)
    return "\n".join(repaired)
