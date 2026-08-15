import os
from pathlib import Path


def _split_paths(value: str) -> list[Path]:
    return [Path(p) for p in value.split(":") if p]


def _split_set(value: str) -> set[str]:
    return {p for p in value.split(",") if p}


SCAN_ROOTS = _split_paths(os.environ.get("SCAN_ROOTS", "/data"))
DB_PATH = Path(os.environ.get("DB_PATH", "/config/dedupe.db"))
STAGING_DIR = Path(os.environ.get("STAGING_DIR", "/staging"))

# Built React SPA (frontend/dist), baked in at Docker build time. Unset in
# local dev/tests, where the frontend runs separately via `npm run dev`.
STATIC_DIR = Path(os.environ["STATIC_DIR"]) if os.environ.get("STATIC_DIR") else None

EXCLUDE_DIRS = _split_set(
    os.environ.get(
        "EXCLUDE_DIRS",
        "@eaDir,#recycle,#snapshot,.SynologyWorkingDirectory,@tmp,.git",
    )
)

WORKERS = int(os.environ.get("WORKERS", "4"))

# Bytes read from the head and tail of a file for the cheap pre-filter hash,
# before committing to a full read. 2MB balances I/O against how often it
# resolves same-size files without a full read.
PARTIAL_HASH_BYTES = int(os.environ.get("PARTIAL_HASH_BYTES", str(2 * 1024 * 1024)))

# Max hamming distance between two pHashes to consider them "similar".
# imagehash.phash produces a 64-bit hash; 0 = identical, ~10 = loosely similar.
PHASH_THRESHOLD = int(os.environ.get("PHASH_THRESHOLD", "5"))

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp", ".heic",
}

# --- Volume/Folder Comparison Mode ---

# Mount points offered by the folder picker (GET /api/browse). Distinct from
# SCAN_ROOTS: either side of a comparison can be any folder under here, not
# just the fixed roots single-volume dedup scans.
BROWSE_ROOTS = _split_paths(
    os.environ.get("BROWSE_ROOTS", "/volume1:/volume2:/volume3:/volumeUSB1:/volumeUSB2")
)

# Comparison mode's one deliberate exception to "never write to source data":
# a compare run's target root must resolve inside one of these to be copyable
# to. Empty by default — copying is refused until explicitly configured.
WRITABLE_ROOTS = _split_paths(os.environ.get("WRITABLE_ROOTS", ""))
