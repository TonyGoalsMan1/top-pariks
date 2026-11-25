"""Check tracked files and an isolated demo export for selected high-risk material."""
import re
import subprocess
import sys
import tarfile
from pathlib import Path

PATTERNS = (
    rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    rb"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{70,}|AKIA[0-9A-Z]{16})\b",
    rb"\b(?:xox[baprs]-[A-Za-z0-9-]{18,}|sk_live_[A-Za-z0-9]{16,})\b",
)

def scan(data, label):
    if any(re.search(pattern, data) for pattern in PATTERNS):
        raise SystemExit(f"Credential-like material detected in {label}")

def sanitize(folder):
    sql_path = folder / "site.sql"
    dump = sql_path.read_bytes()
    hashes = [line.strip() for line in sys.stdin.buffer if line.strip()]
    if not hashes or any(len(value) < 25 or value not in dump for value in hashes):
        raise SystemExit("Demo account password replacement could not be verified.")
    for value in hashes:
        dump = dump.replace(value, b"*")
    scan(dump, "site.sql")
    if re.search(rb"[A-Za-z0-9.+_-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", dump):
        addresses = re.findall(rb"[A-Za-z0-9.+_-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", dump)
        if any(not address.lower().endswith((b"@example.test", b"@example.com", b"@example.net", b"@example.org", b".example")) for address in addresses):
            raise SystemExit("Non-demo email found in the SQL export.")
    sql_path.write_bytes(dump)
    with tarfile.open(folder / "site-files.tar.gz", "r:gz") as archive:
        for item in archive:
            name = Path(item.name).name
            if name in {"wp-config.php", "debug.log", "id_rsa", "id_ed25519"} or name.startswith(".env"):
                raise SystemExit(f"Unexpected file in demo archive: {name}")
            if item.isfile() and item.size <= 2_000_000 and Path(name).suffix in {".php", ".js", ".txt", ".json", ".ini"}:
                with archive.extractfile(item) as stream:
                    scan(stream.read(), item.name)
    print("Demo archive checked. Account passwords are disabled in the exported SQL.")

if len(sys.argv) == 2:
    sanitize(Path(sys.argv[1]))
else:
    for entry in subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0"):
        if entry and Path(entry).is_file():
            scan(Path(entry).read_bytes(), entry)
    print("Tracked files passed the selected credential-pattern scan.")
