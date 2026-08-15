import hashlib

from . import config


def partial_hash(path: str, size: int) -> str | None:
    """Cheap pre-filter hash: head + tail chunks, not the whole file."""
    chunk = config.PARTIAL_HASH_BYTES
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            h.update(f.read(chunk))
            if size > chunk:
                f.seek(max(size - chunk, chunk))
                h.update(f.read(chunk))
    except OSError:
        return None
    return h.hexdigest()


def full_hash(path: str) -> str | None:
    h = hashlib.blake2b(digest_size=32)
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()
