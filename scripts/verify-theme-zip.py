"""Verify that the CI ZIP contains exactly the checked-out WordPress theme."""
import stat
import sys
from pathlib import Path
from zipfile import ZipFile

source = Path("theme/top-pariks")
expected = {
    f"{path.relative_to(source.parent).as_posix()}{'/' if path.is_dir() else ''}": path
    for path in [source, *source.rglob("*")]
}
with ZipFile(sys.argv[1]) as archive:
    entries = archive.infolist()
    if len(entries) != len(expected) or set(archive.namelist()) != expected.keys():
        sys.exit("ZIP must contain exactly the top-pariks/ tree from this commit.")
    for entry in entries:
        path = expected[entry.filename]
        mode = stat.S_IFMT(entry.external_attr >> 16)
        allowed_mode = stat.S_IFDIR if path.is_dir() else stat.S_IFREG
        if path.is_symlink() or mode not in (0, allowed_mode):
            sys.exit(f"Unexpected ZIP entry type: {entry.filename}")
        if not path.is_dir() and archive.read(entry) != path.read_bytes():
            sys.exit(f"ZIP content differs from source: {entry.filename}")
    if bad_entry := archive.testzip():
        sys.exit(f"ZIP integrity test failed: {bad_entry}")
print("Verified the CI top-pariks.zip against the checked-out theme.")
