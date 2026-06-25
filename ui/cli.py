"""
FlipaRender v10 — CLI helpers
"""

import sys


# ── ANSI colours (auto-disabled when not a tty) ───────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text

def cyan(t: str)   -> str: return _c("96", t)
def green(t: str)  -> str: return _c("92", t)
def yellow(t: str) -> str: return _c("93", t)
def red(t: str)    -> str: return _c("91", t)
def bold(t: str)   -> str: return _c("1",  t)
def dim(t: str)    -> str: return _c("2",  t)


# ── Layout helpers ────────────────────────────────────────────────────────────

def banner(app: str, version: str) -> None:
    width = 44
    print()
    print(cyan("╔" + "═" * width + "╗"))
    print(cyan("║") + bold(f"  {app} v{version}".center(width)) + cyan("║"))
    print(cyan("╚" + "═" * width + "╝"))
    print()


def section(title: str) -> None:
    print()
    print(cyan("─" * 44))
    print(bold(f"  {title}"))
    print(cyan("─" * 44))


def ok(msg: str) -> None:
    print(green("  ✔  ") + msg)


def warn(msg: str) -> None:
    print(yellow("  ⚠  ") + msg)


def err(msg: str) -> None:
    print(red("  ✘  ") + msg)


def info(msg: str) -> None:
    """Informational hint line (ℹ prefix, dimmed)."""
    print(dim(f"  ℹ  {msg}"))


def progress(current: int, total: int, label: str = "frames") -> None:
    """Overwrite the current line with a progress bar."""
    pct   = current / total
    done  = int(pct * 30)
    bar   = "█" * done + dim("░" * (30 - done))
    line  = f"\r  [{bar}] {current}/{total} {label}"
    sys.stdout.write(cyan(line))
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


# ── Input helpers ─────────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw  = input(cyan(f"  › {prompt}{hint}: ")).strip()
    return raw or default


def ask_int(
    prompt: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            n = int(raw)
        except ValueError:
            err("Please enter a whole number.")
            continue
        if min_value is not None and n < min_value:
            err(f"Must be ≥ {min_value}.")
            continue
        if max_value is not None and n > max_value:
            err(f"Must be ≤ {max_value}.")
            continue
        return n


def ask_float(
    prompt: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    """Like ask_int but accepts decimal numbers (e.g. motion blur strength)."""
    while True:
        raw = ask(prompt, f"{default:.2f}")
        try:
            n = float(raw)
        except ValueError:
            err("Please enter a number.")
            continue
        if min_value is not None and n < min_value:
            err(f"Must be ≥ {min_value}.")
            continue
        if max_value is not None and n > max_value:
            err(f"Must be ≤ {max_value}.")
            continue
        return n


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    """Ask the user to pick one item from *choices*."""
    options = "  |  ".join(
        bold(c) if c == default else dim(c) for c in choices
    )
    print(f"\n  {options}\n")
    while True:
        raw = ask(prompt, default).lower()
        if raw in choices:
            return raw
        err(f"Valid options: {', '.join(choices)}")
