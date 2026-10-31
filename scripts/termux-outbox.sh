#!/usr/bin/env bash
# Offline capture and drain for a phone. Termux-targeted, but it is
# just bash + ssh and works anywhere.
#
# The device half of `templedb device outbox`. Capture appends to a
# local file and never touches the network, so it works in a subway;
# drain ships the file when there is signal.
#
#   tdb note "subject" "body…"        capture a thought
#   tdb msg  <session_id> "text…"     queue a prompt into an agent session
#   tdb ls                            show what is waiting locally
#   tdb drain                         ship it to the mothership
#
# Install (Termux):
#   pkg install openssh
#   mkdir -p ~/bin && cp termux-outbox.sh ~/bin/tdb && chmod +x ~/bin/tdb
#   # then add the phone's ~/.ssh/id_ed25519.pub to
#   # users.users.zach.openssh.authorizedKeys.keys in system_config
#
# Why SSH and not HTTP: the GUI is bound to 127.0.0.1 and has no
# authentication at all, so exposing it is a security decision that
# has not been made yet. SSH to the mothership over the tailnet is
# already key-only and already the Tier 0 path, so origination works
# today without opening a port or inventing a token.

set -euo pipefail

: "${TDB_HOST:=100.75.210.3}"      # zmothership2 on the tailnet
: "${TDB_USER:=zach}"
: "${TDB_DEVICE:=$(getprop ro.product.model 2>/dev/null || hostname)}"
: "${TDB_OUTBOX:=$HOME/.templedb-outbox.jsonl}"

mkdir -p "$(dirname "$TDB_OUTBOX")"
touch "$TDB_OUTBOX"

# A uuid without uuidgen, which Termux does not ship by default.
_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then uuidgen; return; fi
  od -xN16 /dev/urandom 2>/dev/null \
    | head -1 | awk '{OFS="-"; print $2$3,$4,$5,$6,$7$8$9}'
}

# JSON-escape stdin. Captured text is free-form -- quotes, newlines,
# apostrophes in a dictated sentence -- and a naive printf would emit
# invalid JSON that submit then rejects as malformed, losing the
# capture at the one point where it cannot be re-dictated.
_jstr() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
  else
    sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' \
      | awk 'BEGIN{printf "\""} {printf "%s", (NR>1 ? "\\n" : "") $0} END{printf "\""}'
  fi
}

# occurred_at is the DEVICE clock on purpose: it records when the
# thought happened, not when the radio came back. The server keeps its
# own received_at, so the lag stays visible instead of being lost.
_now() { date '+%Y-%m-%d %H:%M:%S'; }

_append() {
  printf '%s\n' "$1" >> "$TDB_OUTBOX"
  echo "queued (${TDB_OUTBOX##*/}: $(wc -l < "$TDB_OUTBOX") pending)"
}

cmd_note() {
  [ $# -ge 2 ] || { echo "usage: tdb note <subject> <body…>" >&2; exit 2; }
  local subject="$1"; shift
  local body="$*"
  _append "$(printf '{"event_uuid":%s,"kind":"handoff_note","device_id":%s,"occurred_at":%s,"payload":{"subject":%s,"body":%s,"to_topic":"templedb"}}' \
    "$(printf '%s' "$(_uuid)" | _jstr)" \
    "$(printf '%s' "$TDB_DEVICE" | _jstr)" \
    "$(printf '%s' "$(_now)" | _jstr)" \
    "$(printf '%s' "$subject" | _jstr)" \
    "$(printf '%s' "$body" | _jstr)")"
}

cmd_msg() {
  [ $# -ge 2 ] || { echo "usage: tdb msg <session_id> <text…>" >&2; exit 2; }
  local sid="$1"; shift
  case "$sid" in (*[!0-9]*|'') echo "session_id must be numeric" >&2; exit 2;; esac
  local text="$*"
  _append "$(printf '{"event_uuid":%s,"kind":"agent_message","device_id":%s,"occurred_at":%s,"payload":{"session_id":%s,"content":%s}}' \
    "$(printf '%s' "$(_uuid)" | _jstr)" \
    "$(printf '%s' "$TDB_DEVICE" | _jstr)" \
    "$(printf '%s' "$(_now)" | _jstr)" \
    "$sid" \
    "$(printf '%s' "$text" | _jstr)")"
}

cmd_ls() {
  local n; n=$(wc -l < "$TDB_OUTBOX")
  if [ "$n" -eq 0 ]; then echo "(outbox empty)"; return; fi
  echo "$n pending:"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$TDB_OUTBOX" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        print("  (malformed line)"); continue
    p = e.get("payload", {})
    what = p.get("subject") or p.get("content", "")
    print(f"  {e.get('occurred_at','?')[:16]}  {e.get('kind','?'):<14} {str(what)[:48]}")
PY
  else
    cat "$TDB_OUTBOX"
  fi
}

# Drain is safe to interrupt and safe to repeat. Every event carries a
# client-generated event_uuid and submit is idempotent on it, so a
# timeout mid-transfer costs a duplicate submit, not a duplicate
# prompt. The local file is only cleared after the remote has
# confirmed, so a failure leaves the queue intact -- the one ordering
# that cannot lose a capture.
cmd_drain() {
  local n; n=$(wc -l < "$TDB_OUTBOX")
  if [ "$n" -eq 0 ]; then echo "(outbox empty, nothing to drain)"; return 0; fi
  echo "draining $n event(s) to ${TDB_USER}@${TDB_HOST}…"
  if ssh -o BatchMode=yes -o ConnectTimeout=10 \
         "${TDB_USER}@${TDB_HOST}" \
         "templedb device outbox submit --device $(printf '%q' "$TDB_DEVICE")" \
         < "$TDB_OUTBOX"; then
    : > "$TDB_OUTBOX"
    echo "drained; local queue cleared"
    echo "apply on the mothership with: templedb device outbox apply"
  else
    echo "drain FAILED — queue kept, retry when you have signal" >&2
    exit 1
  fi
}

case "${1:-}" in
  note)  shift; cmd_note "$@" ;;
  msg)   shift; cmd_msg  "$@" ;;
  ls)    shift; cmd_ls ;;
  drain) shift; cmd_drain ;;
  *) sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
