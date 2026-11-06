"""cco's lines in this machine's crontab: a snapshot every 2 minutes, and restore at boot.

The crontab, not a systemd user unit: crontabs are per machine, need no root, and run at boot
without a login (a user unit would need `loginctl enable-linger`). Cron's environment is bare,
so the lines carry the shell, PATH and locale tmux and Claude need.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

BEGIN = "# >>> cco: managed by `cco setup` >>>"
END = "# <<< cco <<<"
SAVE_EVERY = "*/2 * * * *"


def block(cco: str, boot: bool, env: dict[str, str], log: Path) -> str:
    # cron turns % into a newline
    prefix = " ".join(f"{k}={shlex.quote(v)}".replace("%", r"\%") for k, v in env.items())
    out = shlex.quote(str(log))
    lines = [BEGIN, f"{SAVE_EVERY} {prefix} {cco} save -q >> {out} 2>&1"]
    if boot:
        lines.append(f"@reboot {prefix} {cco} restore --boot >> {out} 2>&1")
    return "\n".join([*lines, END]) + "\n"


def without(crontab: str) -> str:
    """``crontab`` minus cco's block (and the hand-written lines of cco 0.0)."""
    keep, inside = [], False
    for line in crontab.splitlines():
        if line == BEGIN:
            inside = True
        elif line == END:
            inside = False
        elif not inside and "cco save" not in line and not line.startswith("# cco:"):
            keep.append(line)
    text = "\n".join(keep).rstrip("\n")
    return text + "\n" if text else ""


def read() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""  # 1: no crontab yet


def write(crontab: str) -> None:
    subprocess.run(["crontab", "-"], input=crontab, text=True, check=True)


def installed(crontab: str) -> tuple[bool, bool]:
    """(snapshots on, restore at boot on)."""
    ours = crontab.partition(BEGIN)[2].partition(END)[0]
    return " save " in ours, "@reboot" in ours


def environment() -> dict[str, str]:
    """What cron lacks: the login shell for tmux panes, PATH with claude on it, a UTF-8 locale."""
    return {
        "SHELL": os.environ.get("SHELL", "/bin/bash"),
        "PATH": ":".join(dict.fromkeys(os.environ.get("PATH", "/usr/bin:/bin").split(":"))),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }


def install(cco: str, boot: bool, log: Path) -> None:
    write(without(read()) + block(cco, boot, environment(), log))


def uninstall() -> None:
    write(without(read()))
