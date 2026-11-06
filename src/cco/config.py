"""Where cco keeps things, and the Claude accounts it knows.

An account is a Claude config dir. ``~/.claude`` is Claude's default, launched with
CLAUDE_CONFIG_DIR unset; any other dir is launched with CLAUDE_CONFIG_DIR set to it.
"""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path

# Prompt-cache lifetime Claude Code asks for. A switch after this long costs nothing extra:
# the old account would have re-read the context too.
CACHE_TTL_S = 3600

ALIAS = re.compile(r"""^\s*alias\s+([\w.-]+)=['"]?CLAUDE_CONFIG_DIR=(\S+?)\s+claude\b""", re.M)


def default_dir() -> Path:
    return Path.home() / ".claude"


def config_path() -> Path:
    return Path.home() / ".config" / "cco" / "config.json"


def state_path() -> Path:
    """One snapshot per machine: tmux sessions live on one host, a home dir may not."""
    return Path.home() / ".local" / "state" / "cco" / f"{socket.gethostname()}.json"


def expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(str(path))).resolve()


def aliases(shell_rc: str) -> dict[Path, str]:
    """``alias claude2='CLAUDE_CONFIG_DIR=~/.claude-ecos claude'`` -> {~/.claude-ecos: claude2}."""
    return {expand(d.strip("'\"")): name for name, d in ALIAS.findall(shell_rc)}


def detect() -> dict[str, Path]:
    """``~/.claude`` plus every ``~/.claude-*`` dir that Claude has used, named after the
    shell alias that launches it when there is one."""
    home = Path.home()
    rc = "".join(
        (home / f).read_text(errors="replace")
        for f in (".bashrc", ".bash_aliases", ".zshrc")
        if (home / f).exists()
    )
    names = aliases(rc)
    found = {"claude": default_dir().resolve()}
    for d in sorted(home.glob(".claude-*")):
        if d.is_dir() and ((d / "sessions").is_dir() or (d / ".claude.json").exists()):
            found[names.get(d.resolve(), d.name.lstrip("."))] = d.resolve()
    return found


def accounts() -> dict[str, Path]:
    path = config_path()
    if not path.exists():
        return detect()
    raw: dict[str, str] = json.loads(path.read_text())["accounts"]
    return {name: expand(d) for name, d in raw.items()}


def save_accounts(accts: dict[str, Path]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    home = str(Path.home())
    raw = {
        n: str(d).replace(home, "~", 1) if str(d).startswith(home) else str(d)
        for n, d in accts.items()
    }
    path.write_text(json.dumps({"accounts": raw}, indent=1) + "\n")


def account_of(cfg: Path) -> str:
    for name, d in accounts().items():
        if d == cfg.resolve():
            return name
    return str(cfg)
