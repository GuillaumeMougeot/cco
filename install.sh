#!/bin/sh
# cco installer: uv (if missing) -> cco -> `cco setup`.
#   curl -LsSf https://raw.githubusercontent.com/GuillaumeMougeot/cco/main/install.sh | sh
set -eu
command -v tmux >/dev/null 2>&1 || { echo "cco: install tmux first (e.g. sudo apt install tmux)" >&2; exit 1; }
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
# CCO_SOURCE overrides the source (e.g. a local checkout).
uv tool install --force --python 3.12 "${CCO_SOURCE:-git+https://github.com/GuillaumeMougeot/cco}"
cco setup </dev/tty
