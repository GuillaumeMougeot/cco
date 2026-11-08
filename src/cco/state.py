"""The snapshot `cco restore` rebuilds from, and the usage limits cco has seen.

``{"boot_id", "saved_at", "entries": [{session, window, cwd, claude: {...} | null}],
"limits": {account: reset epoch}}``. The boot id guards the snapshot: after a reboot, `save`
would overwrite it with whatever little runs so far, so it waits until `restore` has run.

A window that disappears stays in the snapshot, marked ``gone_since``: cco can't tell a crash
(systemd-oomd kills a whole tmux pane) from a window closed on purpose. `cco forget` drops it.
A window whose Claude exited keeps its last Claude, marked ``exited``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cco import config, tmux

BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def boot_id() -> str:
    return BOOT_ID.read_text().strip()


def load() -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(config.state_path().read_text())
    except (OSError, ValueError):
        return {}
    return data


def write(state: dict[str, Any]) -> None:
    path = config.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    tmp.replace(path)


def update(**fields: Any) -> None:
    write({**load(), **fields})


def stale() -> bool:
    """The snapshot predates this boot and has not been restored yet."""
    s = load()
    return bool(s.get("entries")) and s.get("boot_id") != boot_id()


def entries(panes: list[tmux.Pane]) -> list[dict[str, Any]]:
    """One entry per window (its first pane): cco restores one pane per window."""
    out = []
    for p in panes:
        if p.index != 0:
            continue
        c = p.claude
        out.append(
            {
                "session": p.session,
                "window": p.window,
                "cwd": p.cwd,
                "claude": c
                and {
                    "config_dir": str(c.config_dir),
                    "account": c.account,
                    "session_id": c.session_id,
                    "name": c.name,
                    "args": c.args,
                },
            }
        )
    return out


def save(panes: list[tmux.Pane]) -> str:
    """Snapshot ``panes``; returns what happened, for the user."""
    if stale():
        return "snapshot is from before the last reboot; run `cco restore` first"
    if not panes:
        return "no tmux server; snapshot left as is"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    before = {(e["session"], e["window"]): e for e in load().get("entries", [])}
    rows = entries(panes)
    for e in rows:
        old = before.pop((e["session"], e["window"]), None)
        if e["claude"] is None and old and old.get("claude"):
            e["claude"], e["exited"] = old["claude"], True
    gone = [{**e, "gone_since": e.get("gone_since", now)} for e in before.values()]
    update(boot_id=boot_id(), saved_at=now, entries=rows + gone)
    extra = f", {len(gone)} gone" if gone else ""
    return f"saved {len(rows)} windows{extra} to {config.state_path()}"


def forget(sessions: list[str]) -> list[str]:
    """Drop ``sessions`` from the snapshot; returns the names that were not in it."""
    snap = load()
    names = {e["session"] for e in snap.get("entries", [])}
    update(entries=[e for e in snap.get("entries", []) if e["session"] not in sessions])
    return sorted(set(sessions) - names)


def limits(seen: dict[str, float], now: float | None = None) -> dict[str, float]:
    """Accounts out of usage, with their reset time: those seen now plus those remembered.
    Remembered ones stay flagged after their sessions moved away or exited."""
    now = time.time() if now is None else now
    stored: dict[str, float] = load().get("limits", {})
    out = {a: t for a, t in stored.items() if t > now}
    for account, reset in seen.items():
        out[account] = max(reset, out.get(account, 0.0))
    if out != stored:
        update(limits=out)
    return out
