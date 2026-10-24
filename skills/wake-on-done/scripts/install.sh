#!/usr/bin/env bash
# install.sh: install notify-run on THIS machine, make sure its config exists, then send a test notice.
# Usage: install.sh --owner <your bot id> [--url '<webhook URL>'] [--force]
#   --url   write ~/.config/webhook-relay/url.env from the URL and the WEBHOOK_RELAY_KEY env var (the box).
#           Without --url, url.env must already be there (user computers: CopyFromBox it from the box first).
#   --force overwrite an existing different notify-run / url.env; use only after the owner agrees.
# The key is read from the env var only; it is never printed or passed on a command line.
set -eu
OWNER=""; U=""; FORCE=0
while [ $# -gt 0 ]; do case "$1" in
  --owner) OWNER="$2"; shift 2;; --url) U="$2"; shift 2;; --force) FORCE=1; shift;;
  *) echo "install: unknown argument $1" >&2; exit 2;; esac; done
[ -n "$OWNER" ] || { echo "usage: install.sh --owner <bot id> [--url '<webhook URL>'] [--force]" >&2; exit 2; }
for b in bash curl python3; do command -v "$b" >/dev/null || { echo "install: $b not found" >&2; exit 1; }; done
BIN=~/.local/bin/notify-run; CFG=~/.config/webhook-relay/url.env
SRC="$(cd "$(dirname "$0")" && pwd)/notify-run"
mkdir -p ~/.local/bin ~/.config/webhook-relay
if [ -e "$BIN" ] && ! cmp -s "$SRC" "$BIN" && [ "$FORCE" = 0 ]; then
  echo "install: a different $BIN exists; check it, rerun with --force only after the owner agrees" >&2; exit 3; fi
cp "$SRC" "$BIN" && chmod 700 "$BIN"
if [ -n "$U" ]; then
  [ -n "${WEBHOOK_RELAY_KEY:-}" ] || { echo "install: WEBHOOK_RELAY_KEY is not set" >&2; exit 2; }
  if [ -e "$CFG" ] && [ "$FORCE" = 0 ]; then
    echo "install: $CFG exists; check it, rerun with --force only after the owner agrees" >&2; exit 3; fi
  (umask 077; printf 'WEBHOOK_RELAY_URL=%s\nWEBHOOK_RELAY_KEY=%s\n' "$U" "$WEBHOOK_RELAY_KEY" > "$CFG")
fi
[ -f "$CFG" ] || { echo "install: $CFG missing; pass --url on the box, or copy it from the box" >&2; exit 2; }
chmod 600 "$CFG"
echo "install: installed $BIN and $CFG; sending test notice (expect exit_code 3, tail ok)"
"$BIN" --owner "$OWNER" --task setup-test -- bash -c 'echo ok; exit 3' || true
echo "install: test sent from $(hostname); pass = you are woken within ~1 min with exit_code 3, status failed, tail ok"
