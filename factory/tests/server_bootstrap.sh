#!/usr/bin/env bash
# Run only on a disposable systemd host with sudo (the GitHub-hosted runner).
set -euo pipefail
umask 077
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
ssh-keygen -q -t ed25519 -f "$work/client" -N ''
ssh-keygen -q -t ed25519 -f "$work/wrong" -N ''

sudo bash factory/server/bootstrap.sh "$work/client.pub"
for service in wordpress-factory-ssh.service caddy wordpress-factory-monitor.timer \
    wordpress-factory-backup.timer wordpress-factory-queue.timer; do
    sudo systemctl is-active "$service"
done

host_key=/etc/wordpress-factory/ssh_host_ed25519_key.pub
sudo sha256sum "$host_key" > "$work/fingerprint"
sudo install -m 0600 "$work/client.pub" /var/lib/wordpress-factory/bootstrap-test-sentinel
sudo bash factory/server/bootstrap.sh "$work/client.pub"
sudo sha256sum --check "$work/fingerprint"
sudo cmp "$work/client.pub" /var/lib/wordpress-factory/bootstrap-test-sentinel

printf '127.0.0.1 top-pariks.factory.test\n' | sudo tee -a /etc/hosts >/dev/null
sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
{
    local_certs
}
import /etc/caddy/WordPressFactory.caddy
CADDY
sudo systemctl reload caddy
python3 factory/factory.py --site factory/sites/top-pariks.json build "$work/release"
# The internal CA exists as soon as the first site is loaded. On the test host
# configure it before the controller verifies its HTTPS endpoint.
(
    ca=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
    for attempt in {1..90}; do
        if sudo test -s "$ca"; then
            sudo install -m 0644 "$ca" /usr/local/share/ca-certificates/factory-ci.crt
            sudo update-ca-certificates >/dev/null
            exit 0
        fi
        sleep 1
    done
    exit 1
) &
trust_pid=$!
sudo wordpress-factory add-site "$PWD/factory/sites/top-pariks.json" top-pariks.factory.test "$work/release"
wait "$trust_pid"
sudo wordpress-factory enable-staging top-pariks
sudo bash factory/server/bootstrap.sh "$work/client.pub"
sudo wordpress-factory add-site "$PWD/factory/sites/top-pariks.json" top-pariks.factory.test "$work/release"

export SSH_HOST=127.0.0.1 SSH_PORT=2222
export SSH_KEY="$(<"$work/client")"
export SSH_KNOWN_HOSTS="[127.0.0.1]:2222 $(awk '{print $1, $2}' "$host_key")"
sha=$(git rev-parse HEAD)
factory/server/send.sh "$sha" "$work/release/theme.zip"
if SSH_KNOWN_HOSTS="[127.0.0.1]:2222 $(awk '{print $1, $2}' "$work/wrong.pub")" \
    factory/server/send.sh "$sha" "$work/release/theme.zip"; then
    echo 'Unpinned host key was accepted' >&2
    exit 1
fi
ssh_options=(-F /dev/null -p 2222 -o BatchMode=yes -o IdentitiesOnly=yes
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$work/known_hosts" -i "$work/client")
printf '%s\n' "$SSH_KNOWN_HOSTS" > "$work/known_hosts"
if ssh "${ssh_options[@]}" factory-deploy@127.0.0.1 'id'; then
    echo 'Arbitrary SSH command was accepted' >&2
    exit 1
fi
if ssh "${ssh_options[@]}" -N -o ExitOnForwardFailure=yes -R 0:127.0.0.1:80 factory-deploy@127.0.0.1; then
    echo 'SSH forwarding was accepted' >&2
    exit 1
fi
sudo wordpress-factory monitor top-pariks
