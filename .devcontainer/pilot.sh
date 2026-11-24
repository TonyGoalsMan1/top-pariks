#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

if [[ ${CODESPACES:-} != true || ! ${CODESPACE_NAME:-} =~ ^[a-z0-9][a-z0-9-]*$ ||
      ${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-} != app.github.dev || -z ${GITHUB_USER:-} ]]; then
  echo "Run this command in the pilot GitHub Codespace." >&2
  exit 2
fi

export FACTORY_PILOT_HOME="/workspaces/.factory-pilot-017"
export CODEX_HOME="$FACTORY_PILOT_HOME/codex"
repository="$GITHUB_USER/top-pariks-factory-pilot"
origin="https://$CODESPACE_NAME-8787.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
pilot=(bash scripts/factory-pilot-017.sh)
if python3 -IB .devcontainer/pilot-state.py; then
  :
else
  status=$?
  [[ "$status" == 3 ]] || exit "$status"
  sudo -n /usr/bin/python3 -IB - --sudo < .devcontainer/pilot-state.py
fi
python3 -B -c 'import sys; from pathlib import Path; from factory.orchestrator.__main__ import private_state; private_state(Path(sys.argv[1]))' "$FACTORY_PILOT_HOME"
log="$FACTORY_PILOT_HOME/start.log"

panel_ready() {
  curl --noproxy '*' --fail --silent --max-time 2 -H "Host: ${origin#https://}" \
    http://127.0.0.1:8787/manifest.webmanifest >/dev/null
}

case "${1:-}" in
  start)
    # Leave the IDE responsive while pinned WooCommerce packages and images are fetched.
    # Hold the lock before returning so access can safely follow start immediately.
    exec 9<>"$FACTORY_PILOT_HOME/panel.lock"
    if flock -n 9; then
      nohup bash "$0" serve </dev/null >>"$log" 2>&1 &
    fi
    printf 'Factory panel: %s\n' "$origin"
    ;;
  serve)
    for attempt in {1..30}; do
      if docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    docker info --format '{{.ServerVersion}}'
    "${pilot[@]}" install --panel-only
    "${pilot[@]}" setup --repository "$repository" --generate-password
    "${pilot[@]}" baseline
    exec env -u GH_TOKEN -u GITHUB_TOKEN -u FACTORY_GITHUB_TOKEN -u OPENAI_API_KEY \
      -u CODEX_API_KEY -u CODEX_HOME -u FACTORY_AUTHORIZE_CODEX_CHATGPT -u FACTORY_AUTHORIZE_TEST_PREVIEW \
      "${pilot[@]}" panel --origin "$origin" --require-dispatcher
    ;;
  access)
    for attempt in {1..90}; do
      if panel_ready; then
        printf '%s\nЛогин: owner\nПароль: ' "$origin"
        cat "$FACTORY_PILOT_HOME/owner-password"
        exit 0
      fi
      if flock -n "$FACTORY_PILOT_HOME/panel.lock" true; then
        echo "Factory is stopped. Run bash .devcontainer/pilot.sh start." >&2
        break
      fi
      sleep 2
    done
    echo "Startup log: $log" >&2
    exit 1
    ;;
  login)
    "${pilot[@]}" install
    install -d -m 700 "$CODEX_HOME"
    "${pilot[@]}" codex login --device-auth
    "${pilot[@]}" codex login status
    ;;
  publish)
    panel_ready || { echo "Start the panel first." >&2; exit 2; }
    "${pilot[@]}" setup --repository "$repository" --generate-password --publish
    ;;
  dispatch)
    if [[ ${FACTORY_AUTHORIZE_CODEX_CHATGPT:-} != 1 || ${FACTORY_AUTHORIZE_TEST_PREVIEW:-} != 1 ]]; then
      echo "Explicit owner approval for ChatGPT quota and local test deployment is required." >&2
      exit 2
    fi
    panel_ready || { echo "Start the panel first." >&2; exit 2; }
    if [[ -z ${FACTORY_GITHUB_TOKEN:-} ]]; then
      read -rsp 'Pilot repository token: ' FACTORY_GITHUB_TOKEN
      printf '\n'
      export FACTORY_GITHUB_TOKEN
    fi
    exec "${pilot[@]}" run --origin "$origin" --dispatcher-only
    ;;
  *)
    echo "Usage: bash .devcontainer/pilot.sh {start|access|login|publish|dispatch}" >&2
    exit 2
    ;;
esac
