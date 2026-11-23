"""Exercise the server controller with isolated Docker, Caddy and restic."""

import contextlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import server

from factory import FactoryError, REPO, build_release, health, write_json


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_file(path):
    for _ in range(100):
        if path.is_file():
            return
        time.sleep(0.1)
    raise RuntimeError(f"Missing: {path.name}")


def upload(site, archive, commit):
    (server.STATE / "staging-site").write_text(site.id)
    payload = io.BytesIO((commit + "\n").encode() + archive.read_bytes())
    with patch.object(sys, "stdin", io.TextIOWrapper(payload)):
        server.receive()


def start_s3(stack):
    # Moto supplies a disposable S3 API. TLS is terminated by the same real
    # Caddy process as WordPress, and restic still verifies its certificate.
    import boto3
    from moto.server import ThreadedMotoServer

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = free_port()
    s3 = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    s3.start()
    stack.callback(s3.stop)
    client = boto3.client("s3", endpoint_url=f"http://127.0.0.1:{port}",
                          aws_access_key_id="test", aws_secret_access_key="test",
                          region_name="us-east-1")
    client.create_bucket(Bucket="factory-backups")
    return port, client


def enable_test_s3(stack, site, root, ca, https_port):
    real_restic = shutil.which("restic")
    wrapper = root / "restic"
    wrapper.write_text(
        "#!/bin/sh\n" + f"export SSL_CERT_FILE={shlex.quote(str(ca))}\n"
        + f'exec {shlex.quote(real_restic)} "$@"\n'
    )
    wrapper.chmod(0o700)
    stack.enter_context(patch.object(os, "defpath", f"{root}:{os.defpath}"))
    write_json(site.root / "s3.json", {
        "repository": f"s3:https://127.0.0.1:{https_port}/factory-backups/{site.id}",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
    })
    (site.root / "restic-password").write_text("synthetic-s3-secret\n")
    server.restic(site, "init", remote=True, stdout=subprocess.DEVNULL)


def main():
    os.umask(0o077)
    with contextlib.ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="factory-server-test-")))
        state = root / "state"
        state.mkdir()
        stack.enter_context(patch.object(server, "STATE", state))
        tools = os.environ.get("FACTORY_TEST_TOOLS")
        if tools:
            stack.enter_context(patch.object(os, "defpath", f"{tools}:{os.defpath}"))

        registry = state / "sites"
        registry.mkdir()
        entries = []
        releases = {}
        for site_id in ("top-pariks", "example-store"):
            profile = server.read_json(REPO / "factory/sites" / f"{site_id}.json")
            profile.update(domain=f"{site_id}.factory.test", port=free_port())
            write_json(registry / f"{site_id}.json", profile)
            site = server.site_for(site_id)
            entries.append(site)
            releases[site.id] = root / site.id
            build_release(site, "HEAD", releases[site.id])
            stack.callback(site.compose, "down", "--volumes", "--remove-orphans")

        https_port = free_port()
        s3_route = ""
        s3_client = None
        if os.environ.get("FACTORY_TEST_S3") == "1":
            s3_port, s3_client = start_s3(stack)
            s3_route = f"127.0.0.1 {{\n reverse_proxy 127.0.0.1:{s3_port}\n}}\n"
        caddyfile = root / "Caddyfile"
        caddyfile.write_text(
            "{\n"
            f"    https_port {https_port}\n"
            "    auto_https disable_redirects\n"
            "    local_certs\n"
            "    admin off\n"
            "    skip_install_trust\n"
            "}\n" + server.proxy_config(entries) + s3_route
        )
        log = stack.enter_context((root / "caddy.log").open("wb"))
        caddy = subprocess.Popen(
            ["caddy", "run", "--config", caddyfile, "--adapter", "caddyfile"],
            env=dict(os.environ, XDG_DATA_HOME=str(root / "caddy-data")), stdout=log, stderr=log,
        )
        def stop_proxy():
            caddy.terminate()
            caddy.wait(timeout=10)
        stack.callback(stop_proxy)
        ca = root / "caddy-data/caddy/pki/authorities/local/root.crt"
        try:
            wait_file(ca)
        except RuntimeError:
            print((root / "caddy.log").read_text())
            raise
        stack.enter_context(patch.dict(os.environ, {"SSL_CERT_FILE": str(ca)}))
        connect = socket.create_connection

        def connect_to_test_caddy(address, *args, **kwargs):
            if address[0].endswith(".factory.test"):
                address = ("127.0.0.1", https_port)
            return connect(address, *args, **kwargs)

        stack.enter_context(patch.object(socket, "create_connection", connect_to_test_caddy))
        for site in entries:
            with site.lock():
                server.provision(site, releases[site.id])
        first, second = entries
        assert (first.runtime / "database-password").read_bytes() != (
            second.runtime / "database-password").read_bytes()
        first_db = first.compose("ps", "-q", "db", capture=True)
        second_db = second.compose("ps", "-q", "db", capture=True)
        def networks(container):
            return set(json.loads(subprocess.check_output([
                "docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container
            ])))
        assert len(networks(first_db)) == 1 and not networks(first_db) & networks(second_db)

        first.wp("option", "update", "server_test_sentinel", "first-only")
        with first.lock():
            try:
                upload(first, releases[first.id] / "theme.zip", "a" * 40)
            except server.SiteBusy:
                pass
            else:
                raise AssertionError("Concurrent deployment passed")
        upload(first, releases[first.id] / "theme.zip", "a" * 40)
        upload(first, releases[first.id] / "theme.zip", "a" * 40)

        broken = root / "broken.zip"
        with ZipFile(releases[first.id] / "theme.zip") as source, ZipFile(broken, "w") as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == f"{first.slug}/functions.php":
                    data = b"<?php throw new RuntimeException('synthetic broken theme');"
                target.writestr(entry, data)
        try:
            upload(first, broken, "b" * 40)
        except FactoryError:
            assert not first.pending.exists() and not first.maintenance.exists()
            assert server.read_json(first.last_release)["commit"] == "a" * 40
        else:
            raise AssertionError("Broken release was accepted")
        health(first)
        health(second)

        # Simulate termination after the stop, before the core transaction is recorded.
        first.maintenance.touch()
        first.stop_web()
        assert server.for_sites("monitor", first.id) == 0
        assert not first.maintenance.exists()

        if s3_client is not None:
            enable_test_s3(stack, first, root, ca, https_port)
        assert server.for_sites("backup", first.id) == 0
        assert not list(first.backups.iterdir())
        result = server.restic(first, "snapshots", "--json", stdout=subprocess.PIPE)
        (entry,) = json.loads(result.stdout)
        (backup_id,) = entry["tags"]
        assert re.fullmatch(server.BACKUP_ID, backup_id)
        first.wp("option", "update", "server_test_sentinel", "modified-after-backup")
        server.restore_copy(first, backup_id, remote=False)
        assert first.wp("option", "get", "server_test_sentinel", capture=True) == "first-only"
        if s3_client is not None:
            s3_client.head_object(Bucket="factory-backups", Key=f"{first.id}/config")
            first.wp("option", "update", "server_test_sentinel", "modified-before-remote-restore")
            server.restore_copy(first, backup_id, remote=True)
            assert first.wp("option", "get", "server_test_sentinel", capture=True) == "first-only"
            print("Encrypted S3-compatible backup and restore passed")
        with contextlib.suppress(subprocess.CalledProcessError):
            second.wp("option", "get", "server_test_sentinel", capture=True, stderr=subprocess.DEVNULL)
            raise AssertionError("Second site could read first site data")

        server.enqueue(first, "check")
        with first.lock():
            server.dispatch()
            assert len(list((state / "queue").glob("*.job"))) == 1
        server.dispatch()
        assert len(list((state / "queue").glob("*.done"))) == 1
        print("HTTPS, isolated sites, deployment, rollback, restart, encrypted restore and queue passed")


if __name__ == "__main__":
    main()
