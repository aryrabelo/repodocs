#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
BIN_DIR="$PREFIX/bin"

mkdir -p "$BIN_DIR"
ln -sf "$ROOT/repodocs" "$BIN_DIR/repodocs"
ln -sf "$ROOT/repodocs" "$BIN_DIR/repodocs-all"

"$BIN_DIR/repodocs" --selftest

printf 'Installed:\n  %s\n  %s\n' "$BIN_DIR/repodocs" "$BIN_DIR/repodocs-all"
printf 'Ensure %s is on PATH.\n' "$BIN_DIR"
