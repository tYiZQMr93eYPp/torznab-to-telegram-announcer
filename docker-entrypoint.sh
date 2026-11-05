#!/bin/sh
# Runs the announcer as PUID:PGID (default 1000:1000).
# Started as root, it fixes the ownership of /data and then drops privileges.
# Started as another user (`docker run --user` / compose `user:`), it just runs the command.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "$PUID$PGID" in
  *[!0-9]*) echo "PUID and PGID must be numeric (got PUID=$PUID PGID=$PGID)" >&2; exit 2 ;;
esac

if [ "$(id -u)" = 0 ]; then
  chown -R "$PUID:$PGID" /data
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
