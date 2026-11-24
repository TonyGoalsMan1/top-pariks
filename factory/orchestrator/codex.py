"""Run the official Codex CLI with ChatGPT auth and structured file proposals."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

from .executors import Critical, Retryable


CLI = [
    "codex", "--no-daemon", "-a", "never",
    "-c", 'forced_login_method="chatgpt"', "-c", 'web_search="disabled"',
    "--disable", "shell_tool", "--disable", "apps", "--disable", "hooks",
    "--disable", "plugins", "--disable", "skill_search",
    "--disable", "multi_agent", "--disable", "multi_agent_v2",
]


def run(args, directory, timeout, *, prompt=None, lease=None):
    # The CLI retains ownership of auth and can use the existing ChatGPT login.
    # GitHub, Docker, API keys and forwarded agents are excluded from its environment.
    env = {key: os.environ[key] for key in (
        "PATH", "HOME", "CODEX_HOME", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR",
    ) if key in os.environ}
    try:
        return subprocess.run([*CLI, *args], cwd=directory, env=env, text=True,
                              input=prompt, stdin=subprocess.DEVNULL if prompt is None else None,
                              capture_output=True, timeout=timeout,
                              pass_fds=() if lease is None else (lease,))
    except subprocess.TimeoutExpired:
        raise Retryable("Codex CLI deadline exceeded") from None
    except OSError:
        raise Critical("Cannot start Codex CLI") from None


def check(directory):
    if os.environ.get("FACTORY_AUTHORIZE_CODEX_CHATGPT") != "1":
        raise Critical("Codex requires explicit owner authorization to use ChatGPT quota")
    result = run(["login", "status"], directory, 20)
    if result.returncode or "Logged in using ChatGPT" not in result.stdout + result.stderr:
        raise Critical("Sign in using ChatGPT with codex login")
    result = run(["exec", "--help"], directory, 10)
    flags = ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--output-schema", "--json")
    if result.returncode or any(flag not in result.stdout for flag in flags):
        raise Critical("Update Codex CLI to a release supporting isolated structured exec")


def execute(instructions, data, definition, timeout, reserve, lease, record_usage):
    with tempfile.TemporaryDirectory(prefix="factory-codex-") as directory:
        check(directory)
        root = Path(directory)
        schema_path = root / "schema.json"
        schema_path.write_text(json.dumps(definition), encoding="utf-8")
        output = root / "result.json"
        reserve()
        result = run([
            "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--sandbox", "read-only", "--skip-git-repo-check", "--json",
            "--output-schema", str(schema_path), "--output-last-message", str(output), "-",
        ], directory, timeout, prompt=instructions + "\n\n" + json.dumps(data, ensure_ascii=False),
            lease=lease)
        try:
            events = [json.loads(line) for line in result.stdout.splitlines()]
            completed = [event["usage"] for event in events if event["type"] == "turn.completed"]
        except (KeyError, TypeError, ValueError):
            raise Critical("Codex did not return valid JSON events") from None
        if len(completed) == 1 and record_usage is not None:
            usage = completed[0]
            if not isinstance(usage, dict) or not all(
                    type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens")):
                raise Critical("Codex returned invalid token usage")
            record_usage(usage, None)
        if result.returncode or len(completed) != 1:
            raise Retryable("Codex turn failed; check ChatGPT session, quota and connectivity")
        if any(event.get("item", {}).get("type") in {
            "command_execution", "file_change", "mcp_tool_call", "web_search", "collab_tool_call",
        } for event in events):
            raise Critical("Unexpected tool activity in Codex proposal")
        try:
            with output.open("rb") as message:
                content = message.read(192 * 1024 + 1)
            if len(content) <= 192 * 1024:
                return json.loads(content)
        except (OSError, ValueError):
            raise Critical("Codex did not return a structured proposal") from None
        raise Critical("Codex proposal exceeds the result size limit")
