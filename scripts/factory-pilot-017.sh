#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

pilot_home="${FACTORY_PILOT_HOME:-$HOME/.factory-pilot-017}"
export PATH="$pilot_home/tools/node_modules/.bin:/opt/homebrew/bin:$PATH"

case "${1:-}" in
  install)
    panel_only=false
    case "${2:-}" in
      '') ;;
      --panel-only) panel_only=true ;;
      *) echo "Usage: bash scripts/factory-pilot-017.sh install [--panel-only]" >&2; exit 2 ;;
    esac
    dependencies=(git gh curl)
    if ! "$panel_only"; then
      dependencies+=(npm)
    fi
    packages=()
    for name in "${dependencies[@]}"; do
      command -v "$name" >/dev/null || packages+=("$name")
    done
    if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      packages+=(python3)
    fi
    if ! command -v gtimeout >/dev/null && ! command -v timeout >/dev/null; then
      packages+=(coreutils)
    fi
    if (( ${#packages[@]} )); then
      case "$(uname -s)" in
        Darwin)
          command -v brew >/dev/null || { echo "Install Homebrew first." >&2; exit 2; }
          for i in "${!packages[@]}"; do
            [[ "${packages[$i]}" != npm ]] || packages[$i]=node
          done
          brew install "${packages[@]}"
          ;;
        Linux)
          sudo apt-get update
          sudo apt-get install -y "${packages[@]}"
          ;;
        *) echo "Use macOS or Ubuntu, including Ubuntu in WSL2." >&2; exit 2 ;;
      esac
    fi
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'
    if ! docker compose version >/dev/null 2>&1; then
      echo "Start your existing local Docker installation with Compose v2." >&2
      exit 2
    fi
    if "$panel_only"; then
      exit 0
    fi
    if ! command -v codex >/dev/null || ! codex exec --help | grep -F -- '--ignore-user-config' >/dev/null; then
      python3 -B -c 'import sys; from pathlib import Path; from factory.orchestrator.__main__ import private_state; private_state(Path(sys.argv[1]))' "$pilot_home"
      npm install --prefix "$pilot_home/tools" --no-save --package-lock=false @openai/codex@0.172.0
    fi
    codex --version
    ;;
  setup)
    shift
    python3 -B -m factory.pilot_setup --home "$pilot_home" "$@"
    ;;
  codex)
    shift
    exec codex "$@"
    ;;
  baseline)
    endpoint="${DOCKER_HOST:-}"
    if [[ -n "${DOCKER_CONTEXT:-}" || -z "$endpoint" ]]; then
      endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
    fi
    [[ "$endpoint" == unix:///* ]] || { echo "Select a local Docker Unix socket." >&2; exit 2; }
    state="$pilot_home/state/wordpress"
    args=(--site "$pilot_home/site.json" --state "$state" --repository "$pilot_home/seed")
    commit="$(git -C "$pilot_home/seed" rev-parse refs/heads/main)"
    release="$(mktemp -d "$pilot_home/baseline.XXXXXXXX")"
    trap 'rm -rf -- "$release"' EXIT
    python3 -B factory/factory.py "${args[@]}" build "$release/package" --ref "$commit"
    python3 -B factory/factory.py "${args[@]}" start "$release/package"
    python3 -B factory/factory.py "${args[@]}" health
    ;;
  run)
    shift
    exec python3 -B -m factory.pilot --config "$pilot_home/projects.json" \
      --accounts "$pilot_home/accounts.json" --state "$pilot_home/state" --workers 1 "$@"
    ;;
  panel)
    shift
    exec python3 -B -m factory.control --config "$pilot_home/projects.json" \
      --accounts "$pilot_home/accounts.json" --state "$pilot_home/state" "$@"
    ;;
  *)
    echo "Usage: bash scripts/factory-pilot-017.sh {install|setup|codex|baseline|run|panel}" >&2
    exit 2
    ;;
esac
