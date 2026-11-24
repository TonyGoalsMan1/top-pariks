#!/bin/sh
set -eu
[ "${SSH_ORIGINAL_COMMAND:-}" = deploy ] || exit 126
exec /usr/bin/sudo -n /usr/local/sbin/wordpress-factory receive
