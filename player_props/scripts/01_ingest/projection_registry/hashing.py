from __future__ import annotations

import hashlib
from pathlib import Path


def hash_file(path: Path | str) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(paths: list[Path | str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(item) for item in paths):
        file_hash = hash_file(path)
        digest.update(str(path.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()
