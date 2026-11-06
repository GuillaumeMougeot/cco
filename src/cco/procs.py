"""Reading processes from /proc: who runs Claude, with which config dir. Linux only."""

from __future__ import annotations

import os
from pathlib import Path

PROC = Path("/proc")  # tests point this at a fake tree


def read(pid: int, name: str) -> bytes:
    try:
        return (PROC / str(pid) / name).read_bytes()
    except OSError:
        return b""


def alive(pid: int) -> bool:
    return (PROC / str(pid)).exists()


def argv(pid: int) -> list[str]:
    return [a.decode() for a in read(pid, "cmdline").split(b"\0") if a]


def environ(pid: int, key: str) -> str | None:
    prefix = key.encode() + b"="
    for kv in read(pid, "environ").split(b"\0"):
        if kv.startswith(prefix):
            return kv[len(prefix) :].decode()
    return None


def children(pid: int) -> list[int]:
    return [int(p) for p in read(pid, f"task/{pid}/children").split()]


def parent(pid: int) -> int:
    stat = read(pid, "stat")
    return int(stat.rsplit(b")", 1)[1].split()[1]) if stat else 0


def ancestors(pid: int) -> set[int]:
    """``pid`` and every process above it."""
    out = set()
    while pid > 1 and pid not in out:
        out.add(pid)
        pid = parent(pid)
    return out


def claude_pid(root: int) -> int | None:
    """``root`` or its first descendant whose argv[0] is claude."""
    todo = [root]
    while todo:
        pid = todo.pop(0)
        args = argv(pid)
        if args and os.path.basename(args[0]) == "claude":
            return pid
        todo += children(pid)
    return None
