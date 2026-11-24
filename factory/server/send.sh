#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $# == 2 && "$1" =~ ^[0-9a-f]{40}$ && -f "$2" ]]
[[ "${SSH_HOST:-}" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ && "${SSH_PORT:-}" =~ ^[1-9][0-9]{0,4}$ && "$SSH_PORT" -le 65535 ]]
[[ -n "${SSH_KEY:-}" && -n "${SSH_KNOWN_HOSTS:-}" ]] || { echo 'Missing Factory SSH credentials.' >&2; exit 1; }

credentials=$(mktemp -d)
trap 'rm -rf -- "$credentials"' EXIT
printf '%s\n' "$SSH_KEY" > "$credentials/key"
printf '%s\n' "$SSH_KNOWN_HOSTS" > "$credentials/known_hosts"
unset SSH_KEY SSH_KNOWN_HOSTS
{
    printf '%s\n' "$1"
    cat -- "$2"
} | ssh -F /dev/null -T -p "$SSH_PORT" -i "$credentials/key" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=15 \
    -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null \
    -o UserKnownHostsFile="$credentials/known_hosts" -o HostKeyAlgorithms=ssh-ed25519 \
    "factory-deploy@$SSH_HOST" deploy
