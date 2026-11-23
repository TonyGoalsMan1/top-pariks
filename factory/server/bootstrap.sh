#!/usr/bin/env bash
set -euo pipefail
umask 022
[[ $(id -u) == 0 && $# == 1 ]] || { echo "Usage (root): $0 DEPLOY_PUBLIC_KEY.pub" >&2; exit 2; }
key=$(<"$1")
[[ "$key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [^[:cntrl:]]*)?$ ]] || { echo 'Expected one Ed25519 public key.' >&2; exit 2; }
ssh-keygen -lf "$1" >/dev/null

source /etc/os-release
case "$ID:$VERSION_ID" in
    ubuntu:24.04|debian:12|debian:13) ;;
    *) echo 'Use Ubuntu 24.04, Debian 12 or Debian 13 with systemd.' >&2; exit 2 ;;
esac
[[ -d /run/systemd/system ]]
exec 9>/run/wordpress-factory-bootstrap.lock
flock -n 9
source_dir=$(cd -- "$(dirname -- "$0")/../.." && pwd)
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl git python3 caddy restic openssh-server sudo rsync

if ! docker compose version >/dev/null 2>&1; then
    if ! command -v docker >/dev/null || dpkg -s docker.io >/dev/null 2>&1; then
        if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
            apt-get install -y docker.io docker-compose-v2
        elif [[ $(apt-cache show docker-compose | awk '/^Version: / {print $2; exit}') == 2.* ]]; then
            apt-get install -y docker.io docker-compose
        elif ! command -v docker >/dev/null; then
            install -d -m 0755 /etc/apt/keyrings
            curl -fsS --proto '=https' "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/factory-docker.asc
            chmod 0644 /etc/apt/keyrings/factory-docker.asc
            printf 'deb [arch=%s signed-by=/etc/apt/keyrings/factory-docker.asc] https://download.docker.com/linux/%s %s stable\n' \
                "$(dpkg --print-architecture)" "$ID" "$VERSION_CODENAME" > /etc/apt/sources.list.d/factory-docker.list
            apt-get update -qq
            apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        else
            echo 'Install Compose v2 for the existing Docker installation and run bootstrap again.' >&2
            exit 1
        fi
    else
        apt-get install -y docker-compose-plugin
    fi
fi
docker compose version >/dev/null
systemctl enable --now docker
docker info >/dev/null

install -d -m 0700 /var/lib/wordpress-factory
# Serialize code installation with server operations.
exec 8>/var/lib/wordpress-factory/server.lock
flock -w 600 -x 8
install -d -m 0755 /etc/wordpress-factory /usr/local/lib/wordpress-factory /usr/local/libexec /etc/caddy
[[ -e /etc/wordpress-factory/deploy.keys ]] || install -m 0644 /dev/null /etc/wordpress-factory/deploy.keys
if ! cmp -s "$1" /etc/wordpress-factory/deploy.keys; then
    printf '%s\n' "$key" > /etc/wordpress-factory/deploy.keys.new
    chmod 0644 /etc/wordpress-factory/deploy.keys.new
    mv -fT /etc/wordpress-factory/deploy.keys.new /etc/wordpress-factory/deploy.keys
fi
if ! id factory-deploy >/dev/null 2>&1; then
    install -d -m 0755 /var/empty/wordpress-factory
    useradd --system --home-dir /var/empty/wordpress-factory --shell /bin/sh factory-deploy
    # OpenSSH rejects locked accounts with UsePAM=no. Set an unknown random
    # password hash while the dedicated daemon permits public keys exclusively.
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' | sed 's/^/factory-deploy:/' | chpasswd
fi
[[ "$(id -nG factory-deploy)" == factory-deploy ]]
install -m 0755 "$source_dir/factory/server/receive.sh" /usr/local/libexec/wordpress-factory-receive
printf '%s\n' 'factory-deploy ALL=(root) NOPASSWD: /usr/local/sbin/wordpress-factory receive' > /etc/sudoers.d/wordpress-factory
chmod 0440 /etc/sudoers.d/wordpress-factory
visudo -cf /etc/sudoers.d/wordpress-factory >/dev/null

# Copy only the application and tracked fixture/profile trees. Without --delete
# a repeat bootstrap preserves owner-installed profiles and fixtures.
rsync -r --exclude '__pycache__' "$source_dir/factory" "$source_dir/sandbox" /usr/local/lib/wordpress-factory/
install -m 0755 "$source_dir/factory/server/wordpress-factory" /usr/local/sbin/wordpress-factory
install -m 0644 "$source_dir/factory/server/sshd_config" /etc/wordpress-factory/sshd_config
if [[ ! -f /etc/wordpress-factory/ssh_host_ed25519_key ]]; then
    ssh-keygen -q -t ed25519 -N '' -f /etc/wordpress-factory/ssh_host_ed25519_key
fi
install -d -m 0755 /run/sshd
sshd -t -f /etc/wordpress-factory/sshd_config
install -m 0644 "$source_dir"/factory/server/systemd/* /etc/systemd/system/
if [[ ! -s /etc/caddy/WordPressFactory.caddy ]]; then
    printf '%s\n' '# No Factory sites registered.' > /etc/caddy/WordPressFactory.caddy
fi
if ! grep -qxF 'import /etc/caddy/WordPressFactory.caddy' /etc/caddy/Caddyfile; then
    # The distro example binds :80 and would mask HTTPS redirects.
    if dpkg-query -W -f='${Conffiles}\n' caddy | awk '$1=="/etc/caddy/Caddyfile" {print $2}' |
        grep -qx "$(md5sum /etc/caddy/Caddyfile | cut -d ' ' -f1)"; then
        cp -an /etc/caddy/Caddyfile /etc/caddy/Caddyfile.distro
        printf '%s\n' 'import /etc/caddy/WordPressFactory.caddy' > /etc/caddy/Caddyfile
    else
        printf '\n%s\n' 'import /etc/caddy/WordPressFactory.caddy' >> /etc/caddy/Caddyfile
    fi
fi
caddy validate --config /etc/caddy/Caddyfile >/dev/null
systemctl daemon-reload
systemctl enable --now caddy wordpress-factory-ssh.service wordpress-factory-backup.timer \
    wordpress-factory-monitor.timer wordpress-factory-queue.timer
systemctl restart wordpress-factory-ssh.service
systemctl reload caddy
echo 'Factory SSH host key fingerprint (verify and record through this console):'
ssh-keygen -lf /etc/wordpress-factory/ssh_host_ed25519_key.pub
cat /etc/wordpress-factory/ssh_host_ed25519_key.pub
