"""cco: keep track of the Claude Code sessions running in tmux, move them between Claude
accounts, and bring them back after a reboot."""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from cco import __version__, autostart, claude, config, procs, state, tmux

app = typer.Typer(help=__doc__, no_args_is_help=True, add_completion=False, rich_markup_mode=None)


class CcoError(Exception):
    pass


def say(msg: str) -> None:
    typer.echo(msg)


def _ago(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.0f} h"
    return f"{seconds / 86400:.0f} d"


def _when(epoch: float) -> str:
    return time.strftime("%a %d %b %H:%M", time.localtime(epoch))


def _info(c: claude.Claude) -> claude.Info:
    path = claude.transcript(c.config_dir, c.session_id)
    return claude.info(path, c.started_at) if path else claude.Info()


def _limits(panes: list[tmux.Pane], infos: dict[str, claude.Info]) -> dict[str, float]:
    seen: dict[str, float] = {}
    for p in panes:
        if p.claude and (reset := infos[p.pane_id].limit_reset):
            seen[p.claude.account] = max(reset, seen.get(p.claude.account, 0.0))
    return state.limits(seen)


def cost_note(info: claude.Info, now: float) -> str:
    """What the first turn on the new account costs, against staying."""
    if not info.context_tokens:
        return ""
    size = f"{info.context_tokens / 1000:.0f}k tokens"
    if info.last_turn is None or now - info.last_turn > config.CACHE_TTL_S:
        idle = f"idle {_ago(now - info.last_turn)}" if info.last_turn else "idle"
        return f"context {size}, {idle}: its cache had expired, so no extra cost"
    left = config.CACHE_TTL_S - (now - info.last_turn)
    return (
        f"context {size}: the first turn re-reads it uncached "
        f"(the old account's cache would have expired in {_ago(left)} anyway)"
    )


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[bool, typer.Option("--version", help="Print the version.")] = False,
) -> None:
    if version:
        say(f"cco {__version__}")
        raise typer.Exit()


@app.command("ls")
def ls() -> None:
    """Every tmux window: its account, status, context size, title, folder."""
    panes = tmux.panes()
    if not panes:
        say("no tmux server running")
        return
    if state.stale():
        say("snapshot is from before the last reboot: `cco restore` brings those sessions back")
    infos = {p.pane_id: _info(p.claude) for p in panes if p.claude}
    limits = _limits(panes, infos)
    for account, reset in sorted(limits.items()):
        say(f"{account}: out of usage until {_when(reset)}")
    home = str(Path.home())
    for p in panes:
        cwd = p.cwd.replace(home, "~", 1)
        c = p.claude
        if not c:
            say(f"{p.where:<14} {'-':<8} {'shell':<8} {'':>5}  {'':<8}  {'':<40} {cwd}")
            continue
        i = infos[p.pane_id]
        status = "LIMIT" if c.account in limits else (c.status or "?")
        ctx = f"{i.context_tokens / 1000:.0f}k" if i.context_tokens else ""
        title = (i.title or c.name or "")[:40]
        sid = (c.session_id or "?")[:8]
        say(f"{p.where:<14} {c.account:<8} {status:<8} {ctx:>5}  {sid:<8}  {title:<40} {cwd}")


def _stop(pid: int, pane_id: str) -> None:
    os.kill(pid, signal.SIGTERM)
    for i in range(100):
        if not procs.alive(pid):
            break
        if i == 50:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.1)
    else:
        raise CcoError(f"pid {pid} would not exit")
    time.sleep(0.5)
    tmux.run("send-keys", "-t", pane_id, "C-u")  # clear any half-typed shell line


@app.command()
def switch(
    sessions: Annotated[list[str] | None, typer.Argument(help="tmux session names.")] = None,
    to: Annotated[str, typer.Option("--to", help="Target account; `cco setup` names them.")] = "",
    limited: Annotated[
        bool, typer.Option("--limited", help="Every session on an account out of usage.")
    ] = False,
    message: Annotated[
        str | None, typer.Option("--say", help="Send this once resumed, e.g. 'continue'.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Also stop sessions mid-turn or running a command.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Only show the plan.")] = False,
) -> None:
    """Move Claude sessions to another account: same conversation, same tmux pane.

    Stops the Claude, copies its transcript and per-session files to the other account's
    config dir (the old copy stays), and resumes it there with its original arguments."""
    accts = config.accounts()
    if to not in accts:
        raise CcoError(f"--to: one of {', '.join(accts)}")
    if not sessions and not limited:
        raise CcoError("name tmux sessions, or pass --limited")
    dst = accts[to]
    panes = [p for p in tmux.panes() if p.claude]
    infos = {p.pane_id: _info(p.claude) for p in panes if p.claude}
    limits = _limits(panes, infos)
    if limited:
        targets = [p for p in panes if p.claude and p.claude.account in limits]
    else:
        targets = [p for p in panes if p.session in (sessions or [])]
        missing = set(sessions or []) - {p.session for p in targets}
        if missing:
            raise CcoError(f"no Claude runs in tmux session(s): {', '.join(sorted(missing))}")
    if not targets:
        say("nothing to switch")
    me = procs.ancestors(os.getpid())
    for p in targets:
        c = p.claude
        assert c is not None
        if c.pid in me:
            say(f"{p.session}: skipped, that is the Claude running cco")
        elif c.account == to:
            say(f"{p.session}: already on {to}")
        elif not c.session_id:
            say(f"{p.session}: skipped, its session id is unknown")
        elif c.status in ("busy", "shell") and not force:
            say(f"{p.session}: skipped, status {c.status}: still working (--force stops it)")
        else:
            _switch_one(p, c, dst, to, infos[p.pane_id], message, dry_run)
    if not dry_run:
        state.save(tmux.panes())


def _switch_one(
    p: tmux.Pane,
    c: claude.Claude,
    dst: Path,
    to: str,
    info: claude.Info,
    message: str | None,
    dry_run: bool,
) -> None:
    assert c.session_id
    cmd = claude.launch_cmd(dst, c.session_id, c.args)
    say(f"{p.session}: {c.account} -> {to}, session {c.session_id}")
    if note := cost_note(info, time.time()):
        say(f"  {note}")
    if dry_run:
        say(f"  would run: {cmd}")
        return
    _stop(c.pid, p.pane_id)
    copied = claude.copy_session(c.config_dir, dst, c.session_id)
    say(f"  copied {len(copied)} items to {dst}")
    tmux.type_line(p.pane_id, cmd)
    trust_ok = claude.trusted(c.config_dir, c.cwd)
    new = tmux.wait_started(p.pane_id, trust_ok)
    if new is None:
        why = "a folder-trust dialog waits for you" if not trust_ok else "not up after 90 s"
        say(f"  WARNING: {why}; `tmux attach -t {p.session}`")
        return
    if new.session_id != c.session_id:
        say(f"  WARNING: resumed as {new.session_id}, expected {c.session_id}")
    say(f"  resumed, pid {new.pid}")
    if message:
        tmux.type_line(p.pane_id, message)
        say(f"  sent: {message}")


@app.command()
def save(quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False) -> None:
    """Snapshot every tmux window and its Claude, for `cco restore`. Cron runs this."""
    msg = state.save(tmux.panes())
    if not quiet:
        say(msg)


def _boot_env() -> None:
    """Under cron at boot: make sure claude is on PATH for the panes' shells."""
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"
    say(time.strftime("%Y-%m-%d %H:%M:%S restore at boot"))


@app.command()
def restore(
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Only show the plan.")] = False,
    boot: Annotated[bool, typer.Option("--boot", help="Run by cron at boot.")] = False,
) -> None:
    """Recreate the snapshot's missing tmux windows and resume each Claude in them."""
    if boot:
        _boot_env()
    snap = state.load()
    if "entries" not in snap:
        raise CcoError(f"no snapshot at {config.state_path()}")
    say(f"snapshot from {snap.get('saved_at')}")
    live = {(p.session, p.window) for p in tmux.panes()}
    live_sessions = {s for s, _ in live}
    for e in snap["entries"]:
        if (e["session"], e["window"]) in live:
            continue
        _restore_one(e, live_sessions, dry_run)
    if not dry_run:
        state.update(boot_id=state.boot_id())


def _restore_one(e: dict[str, Any], live_sessions: set[str], dry_run: bool) -> None:
    c, where = e["claude"], f"{e['session']}:{e['window']}"
    cmd = claude.launch_cmd(Path(c["config_dir"]), c["session_id"], c["args"]) if c else None
    say(f"{where:<14} {c['account'] if c else 'shell':<8} {e['cwd']}")
    if cmd:
        say(f"  {cmd}")
    if dry_run:
        return
    if e["session"] in live_sessions:
        tmux.run("new-window", "-d", "-t", where, "-c", e["cwd"])
    else:
        tmux.run("new-session", "-d", "-s", e["session"], "-c", e["cwd"])
        live_sessions.add(e["session"])
    if cmd:
        tmux.type_line(where, cmd)
        # Same account and folder as before, so its trust answer still stands.
        ok = tmux.wait_started(where, trust_ok=True)
        say("  up" if ok else f"  WARNING: not up after 90 s; `tmux attach -t {e['session']}`")


def _cco_path() -> str:
    found = shutil.which("cco")
    return found or str(Path(sys.argv[0]).resolve())


@app.command()
def setup(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Take every default.")] = False,
) -> None:
    """Name this machine's Claude accounts and choose whether sessions come back at boot.

    Writes ~/.config/cco/config.json and cco's block in this machine's crontab: a snapshot
    every 2 minutes, and `cco restore` at boot (on by default)."""
    found = config.detect()
    known = config.accounts() if config.config_path().exists() else {}
    names = {d: n for n, d in known.items()}
    accts: dict[str, Path] = {}
    for name, d in found.items():
        default = names.get(d, name)
        n = default if yes else str(typer.prompt(f"Name for account {d}", default=default))
        accts[n] = d
    config.save_accounts(accts)
    say("accounts: " + ", ".join(f"{n} = {d}" for n, d in accts.items()))
    boot = yes or typer.confirm(
        "Restore the sessions automatically when this computer boots?", default=True
    )
    log = config.state_path().with_suffix(".log")
    autostart.install(_cco_path(), boot, log)
    say(f"crontab: snapshot every 2 min{', restore at boot' if boot else ''}; log {log}")
    if not boot:
        say("after a reboot, run `cco restore`")


def entrypoint() -> None:
    try:
        app()
    except (CcoError, tmux.TmuxError, FileNotFoundError) as e:
        typer.echo(f"cco: {e}", err=True)
        raise SystemExit(1) from e
