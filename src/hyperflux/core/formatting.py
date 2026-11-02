"""Clean up Markdown the model writes before it is shown."""

import re

# ---- LaTeX -> readable terminal text --------------------------------------------
# The terminal can't draw real maths, so turn common LaTeX into plain symbols:
#   $\frac{3}{4} \times 2$  ->  3/4 × 2

_SYMBOLS = {
    r"\times": "×", r"\div": "÷", r"\cdot": "·", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\neq": "≠",
    r"\approx": "≈", r"\equiv": "≡", r"\infty": "∞", r"\pi": "π", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\Delta": "Δ",
    r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\sum": "Σ", r"\int": "∫",
    r"\rightarrow": "→", r"\to": "→", r"\Rightarrow": "⇒", r"\degree": "°",
    r"\circ": "°", r"\%": "%", r"\quad": "  ", r"\qquad": "    ", r"\,": " ",
    r"\;": " ", r"\!": "", r"\left": "", r"\right": "",
}
_SUPERSCRIPTS = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_MATH_SPANS = re.compile(
    r"\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)"
    r"|(?<![\\$\w])\$(?![\s$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?![\w$])"
)


def _read_group(tex, start):
    """Return (content, end) for a {...} group at tex[start], or a single char."""
    if start < len(tex) and tex[start] == "{":
        depth = 0
        for index in range(start, len(tex)):
            if tex[index] == "{":
                depth += 1
            elif tex[index] == "}":
                depth -= 1
                if depth == 0:
                    return tex[start + 1:index], index + 1
        return tex[start + 1:], len(tex)
    return tex[start:start + 1], start + 1


def _wrap(part):
    part = part.strip()
    return part if re.fullmatch(r"[\w.]+", part) else f"({part})"


def latex_to_text(tex):
    out = []
    index = 0
    while index < len(tex):
        if tex.startswith(r"\frac", index) or tex.startswith(r"\dfrac", index):
            index += 5 if tex.startswith(r"\frac", index) else 6
            top, index = _read_group(tex, index)
            bottom, index = _read_group(tex, index)
            out.append(f"{_wrap(latex_to_text(top))}/{_wrap(latex_to_text(bottom))}")
        elif tex.startswith(r"\sqrt", index):
            inner, index = _read_group(tex, index + 5)
            out.append(f"√{_wrap(latex_to_text(inner))}")
        elif tex.startswith(r"\text", index):
            inner, index = _read_group(tex, index + 5)
            out.append(inner)
        elif tex[index] == "^":
            power, index = _read_group(tex, index + 1)
            power = latex_to_text(power)
            translated = power.translate(_SUPERSCRIPTS)
            out.append(translated if translated != power or not power else f"^{_wrap(power)}")
        elif tex[index] == "\\":
            match = re.match(r"\\(?:[A-Za-z]+|.)", tex[index:])
            command = match.group(0)
            out.append(_SYMBOLS.get(command, command.lstrip("\\")))
            index += len(command)
        elif tex[index] in "{}":
            index += 1
        else:
            out.append(tex[index])
            index += 1
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def render_math_for_terminal(text):
    """Replace $...$ / $$...$$ maths with readable text; displayed maths gets its own line."""
    def replace(match):
        display = match.group(1) or match.group(2)
        tex = display or match.group(3) or match.group(4)
        readable = latex_to_text(tex)
        return f"\n\n{readable}\n\n" if display else readable
    rendered = _MATH_SPANS.sub(replace, text)
    # Drop trailing spaces, then collapse runs of blank lines left between equations.
    rendered = re.sub(r"[ \t]+\n", "\n", rendered)
    return re.sub(r"\n{3,}", "\n\n", rendered).strip()

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
