"""Prepare the one persistent state directory used by the Codespace pilot."""

import os
import stat
import sys


def reject_checkout(directory):
    try:
        os.stat(".git", dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError("Runtime state must be outside Git checkouts")


def prepare(workspaces, uid, gid):
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(workspaces, directory_flags)
    try:
        info = os.fstat(parent)
        if info.st_uid not in (0, uid) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise ValueError("The workspace parent must have a trusted owner and protect directory entries")
        reject_checkout(parent)
        name = ".factory-pilot-017"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Runtime state must be a real directory")
        if info.st_uid not in (0, uid):
            raise ValueError(f"Runtime state belongs to an unexpected UID ({info.st_uid})")
        if info.st_uid != uid and os.getuid() != 0:
            raise PermissionError("Changing ownership of root-owned runtime state requires sudo")

        directory = os.open(name, directory_flags, dir_fd=parent)
        try:
            reject_checkout(directory)
            info = os.fstat(directory)
            mode = stat.S_IMODE(info.st_mode)
            # Only adopt a root-owned or shared-writable directory while it is empty.
            if info.st_uid != uid or mode & 0o022:
                if os.listdir(directory):
                    raise ValueError(
                        f"Cannot safely repair populated runtime state (UID {info.st_uid}, mode {mode:04o})"
                    )
                os.fchmod(directory, 0o700)
                if os.listdir(directory):
                    os.fchmod(directory, mode)
                    raise ValueError("Runtime state changed during repair")
                if info.st_uid != uid:
                    os.fchown(directory, uid, gid)
            elif mode != 0o700:
                os.fchmod(directory, 0o700)
        finally:
            os.close(directory)
    finally:
        os.close(parent)


if __name__ == "__main__":
    os.umask(0o077)
    elevated = sys.argv[1:] == ["--sudo"]
    try:
        if elevated:
            uid, gid = (int(os.environ[name]) for name in ("SUDO_UID", "SUDO_GID"))
        else:
            uid, gid = os.getuid(), os.getgid()
        prepare("/workspaces", uid, gid)
    except PermissionError as error:
        if not elevated:
            sys.exit(3)
        sys.exit(f"Factory state: {error}")
    except (OSError, ValueError) as error:
        sys.exit(f"Factory state: {error}")
