"""Claude Code's files: the per-process registry, transcripts, and what a session needs to move.

Layout of a config dir, as of Claude Code 2.1.31x:
- ``sessions/<pid>.json``: the live process's session id, cwd, name, status, start time.
- ``projects/<cwd with / and _ as ->/<id>.jsonl``: the transcript, and ``<id>/`` next to it
  (subagents, tool results).
- ``file-history/<id>``, ``session-env/<id>``: per-session state.
- ``.claude.json`` (``~/.claude.json`` for the default dir): per-folder trust.
"""

from __future__ import annotations

import calendar
import json
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from cco import config, procs

TAIL_BYTES = 4_000_000  # enough for the last turns of a 100 MB transcript


@dataclass
class Claude:
    pid: int
    config_dir: Path
    session_id: str | None
    cwd: str
    name: str | None = None
    status: str | None = None  # idle, busy, waiting, shell (Claude's own words)
    started_at: float = 0.0  # epoch seconds
    args: list[str] = field(default_factory=list)

    @property
    def account(self) -> str:
        return config.account_of(self.config_dir)


def registry(cfg: Path, pid: int) -> dict[str, object]:
    path = cfg / "sessions" / f"{pid}.json"
    try:
        data: dict[str, object] = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data


def config_dir_of(pid: int) -> Path:
    value = procs.environ(pid, "CLAUDE_CONFIG_DIR")
    return config.expand(value) if value else config.default_dir().resolve()


def find(pid: int, fallback_cwd: str = "") -> Claude:
    cfg = config_dir_of(pid)
    reg = registry(cfg, pid)
    sid = reg.get("sessionId")
    return Claude(
        pid=pid,
        config_dir=cfg,
        session_id=str(sid) if sid else None,
        cwd=str(reg.get("cwd") or fallback_cwd),
        name=str(reg["name"]) if reg.get("name") else None,
        status=str(reg["status"]) if reg.get("status") else None,
        started_at=float(str(reg.get("startedAt") or 0)) / 1000,
        args=strip_resume(procs.argv(pid)[1:]),
    )


def strip_resume(args: list[str]) -> list[str]:
    """Claude's args minus the ones that pick a session; cco adds ``--resume <id>`` itself."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("--resume", "-r", "--session-id"):
            skip = True
        elif a in ("--continue", "-c") or a.startswith(("--resume=", "--session-id=")):
            continue
        else:
            out.append(a)
    return out


def launch_cmd(cfg: Path, session_id: str | None, args: list[str]) -> str:
    """The shell line that starts Claude on account ``cfg``, resuming ``session_id``."""
    if cfg.resolve() == config.default_dir().resolve():
        env = "env -u CLAUDE_CONFIG_DIR"
    else:
        env = f"CLAUDE_CONFIG_DIR={shlex.quote(str(cfg))}"
    resume = ["--resume", session_id] if session_id else []
    return " ".join([env, "claude", *resume, *map(shlex.quote, args)])


def transcript(cfg: Path, session_id: str | None) -> Path | None:
    if not session_id:
        return None
    return next(iter((cfg / "projects").glob(f"*/{session_id}.jsonl")), None)


@dataclass
class Info:
    title: str | None = None
    context_tokens: int = 0  # what the last turn sent: the next turn re-reads about this much
    last_turn: float | None = None  # epoch of the last API answer
    limit_reset: float | None = None  # epoch when the usage limit this process hit resets


def _epoch(ts: object) -> float:
    return float(calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")))


def _title(lines: list[bytes]) -> str | None:
    for line in reversed(lines):
        if b'"custom-title"' in line or b'"ai-title"' in line:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            title = d.get("customTitle") or d.get("aiTitle")
            if title:
                return str(title)
    return None


def info(path: Path, started_at: float = 0.0, now: float | None = None) -> Info:
    """What the transcript's tail says. A usage-limit error counts only if this process
    (started at ``started_at``) got it and nothing answered since: an older one came from
    whichever account ran the session before a switch."""
    now = time.time() if now is None else now
    out = Info()
    with path.open("rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().splitlines()
    out.title = _title(lines)
    if out.title is None and size > TAIL_BYTES:
        out.title = _title(path.read_bytes().splitlines())
    for line in reversed(lines):
        if b'"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        if d.get("error") == "rate_limit":
            reset = (d.get("quotaLimits") or {}).get("resetsAt")
            if (
                out.last_turn is None
                and reset
                and reset > now
                and _epoch(d["timestamp"]) >= started_at
            ):
                out.limit_reset = float(reset)
            continue
        usage = (d.get("message") or {}).get("usage") or {}
        if usage.get("output_tokens"):
            out.last_turn = _epoch(d["timestamp"])
            out.context_tokens = sum(
                int(usage.get(k) or 0)
                for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            )
            break
    return out


def copy_session(src: Path, dst: Path, session_id: str) -> list[Path]:
    """Copy one conversation from config dir ``src`` to ``dst``; ``src`` keeps its copy."""
    hits = list((src / "projects").glob(f"*/{session_id}.jsonl"))
    if not hits:
        raise FileNotFoundError(f"transcript {session_id}.jsonl not found under {src}/projects")
    copied = []
    for jsonl in hits:
        proj = dst / "projects" / jsonl.parent.name
        proj.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jsonl, proj / jsonl.name)
        copied.append(proj / jsonl.name)
        side = jsonl.with_suffix("")
        if side.is_dir():
            shutil.copytree(side, proj / session_id, dirs_exist_ok=True)
            copied.append(proj / session_id)
    for top in src.iterdir():
        if not top.is_dir() or top.name in ("projects", "sessions"):
            continue
        for item in top.glob(f"{session_id}*"):
            target = dst / top.name / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
            copied.append(target)
    return copied


def trusted(cfg: Path, cwd: str) -> bool:
    """Did account ``cfg`` accept the folder-trust dialog for ``cwd`` or a parent?"""
    is_default = cfg.resolve() == config.default_dir().resolve()
    path = Path.home() / ".claude.json" if is_default else cfg / ".claude.json"
    try:
        projects = json.loads(path.read_text()).get("projects", {})
    except (OSError, ValueError):
        return False
    p = Path(cwd)
    return any(projects.get(str(q), {}).get("hasTrustDialogAccepted") for q in (p, *p.parents))
