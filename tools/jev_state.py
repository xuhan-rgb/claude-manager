"""Per-turn state with atomic writes and nonblocking single-owner locks."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def turn_path(event, root=None):
    root = Path(root or Path.home() / ".local/state/jev-router")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not event.get("session_id") or not event.get("turn_id"):
        raise ValueError("hook lacks session or turn id")
    identity = json.dumps([event["session_id"], event["turn_id"]])
    return root / (hashlib.sha256(identity.encode()).hexdigest() + ".json")


@contextmanager
def locked(path):
    with path.with_suffix(".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def save(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".jev-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read(path):
    return json.loads(path.read_text())
