"""Fixtures: a fake home with two Claude accounts, a fake /proc, a fake tmux. Nothing real runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from cco import procs, state, tmux


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    (h / ".claude" / "sessions").mkdir(parents=True)
    (h / ".claude-ecos" / "sessions").mkdir(parents=True)
    (h / ".bashrc").write_text("alias claude2='CLAUDE_CONFIG_DIR=~/.claude-ecos claude'\n")
    monkeypatch.setenv("HOME", str(h))
    boot = tmp_path / "boot_id"
    boot.write_text("boot-1\n")
    monkeypatch.setattr(state, "BOOT_ID", boot)
    return h


@pytest.fixture
def proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """``proc(pid, argv, env={}, parent=1)`` adds a fake process."""
    root = tmp_path / "proc"
    monkeypatch.setattr(procs, "PROC", root)

    def add(pid: int, argv: list[str], env: dict[str, str] | None = None, parent: int = 1) -> None:
        d = root / str(pid)
        (d / "task" / str(pid)).mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()))
        (d / "stat").write_bytes(f"{pid} ({argv[0]}) S {parent} 0 0".encode())
        (d / "task" / str(pid) / "children").write_text("")
        if parent > 1:
            kids = root / str(parent) / "task" / str(parent) / "children"
            kids.write_text(kids.read_text() + f"{pid} ")

    return add


def register(cfg: Path, pid: int, **reg: Any) -> None:
    (cfg / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, **reg}))


class FakeTmux:
    """Records commands; ``screens`` are what capture-pane returns, one per call."""

    def __init__(self, panes: str = "", screens: list[str] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.panes = panes
        self.screens = screens or []
        self.pane_pid = "100"

    def __call__(self, *args: str, check: bool = True) -> str:
        self.calls.append(args)
        if args[0] == "list-panes":
            return self.panes
        if args[0] == "capture-pane":
            return self.screens.pop(0) if self.screens else ""
        if args[0] == "display-message":
            return self.pane_pid + "\n"
        return ""

    def typed(self) -> list[str]:
        return [c[4] for c in self.calls if c[:1] == ("send-keys",) and "-l" in c]


@pytest.fixture
def fake_tmux(monkeypatch: pytest.MonkeyPatch) -> FakeTmux:
    fake = FakeTmux()
    monkeypatch.setattr(tmux, "run", fake)
    return fake
