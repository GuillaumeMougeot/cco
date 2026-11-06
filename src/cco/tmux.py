"""tmux: list panes with the Claude in each, type into them, answer Claude's startup dialogs."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from cco import claude, procs


class TmuxError(RuntimeError):
    pass


def run(*args: str, check: bool = True) -> str:
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise TmuxError(f"tmux {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


@dataclass
class Pane:
    session: str
    window: int
    index: int
    pane_id: str
    pid: int
    cwd: str
    claude: claude.Claude | None = None

    @property
    def where(self) -> str:
        return f"{self.session}:{self.window}.{self.index}"


FORMAT = "\t".join(
    "#{" + k + "}"
    for k in (
        "session_name",
        "window_index",
        "pane_index",
        "pane_id",
        "pane_pid",
        "pane_current_path",
    )
)


def panes() -> list[Pane]:
    """Every pane on the tmux server; empty when no server runs."""
    try:
        out = run("list-panes", "-a", "-F", FORMAT)
    except (TmuxError, FileNotFoundError):
        return []
    rows = []
    for line in out.splitlines():
        sess, win, idx, pane_id, pid, cwd = line.split("\t")
        pane = Pane(sess, int(win), int(idx), pane_id, int(pid), cwd)
        cpid = procs.claude_pid(pane.pid)
        if cpid:
            pane.claude = claude.find(cpid, cwd)
            pane.cwd = pane.claude.cwd
        rows.append(pane)
    return rows


def capture(target: str) -> str:
    return run("capture-pane", "-p", "-t", target, check=False)


def type_line(target: str, text: str) -> None:
    run("send-keys", "-t", target, "-l", text)
    run("send-keys", "-t", target, "Enter")


def wait_started(
    target: str,
    trust_ok: bool,
    timeout: float = 90,
    sleep: Callable[[float], None] = time.sleep,
) -> claude.Claude | None:
    """Wait for the Claude just launched in ``target``, answering its startup dialogs:
    "Resume this conversation?" -> Resume (the default); folder trust -> yes, only when
    ``trust_ok``. Returns it once it has registered and shown no dialog for 3 s."""
    shell = int(run("display-message", "-p", "-t", target, "#{pane_pid}").strip())
    quiet, waited = 0, 0.0
    while waited < timeout:
        sleep(1)
        waited += 1
        screen = capture(target)
        if "Yes, I trust this folder" in screen:
            if not trust_ok:
                return None
            run("send-keys", "-t", target, "Down")
            run("send-keys", "-t", target, "Enter")
            quiet = 0
        elif "Resume this conversation?" in screen:
            run("send-keys", "-t", target, "Enter")
            quiet = 0
        else:
            pid = procs.claude_pid(shell)
            quiet = quiet + 1 if pid and claude.registry(claude.config_dir_of(pid), pid) else 0
            if pid and quiet >= 3:
                return claude.find(pid)
    return None
