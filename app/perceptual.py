import imagehash
from pillow_heif import register_heif_opener
from PIL import Image, UnidentifiedImageError

register_heif_opener()


def compute_phash(path: str) -> str | None:
    """64-bit perceptual hash for near-duplicate image detection.

    Returns None for anything that isn't a decodable image — callers should
    treat that as "no signal", not an error.
    """
    try:
        with Image.open(path) as img:
            return str(imagehash.phash(img))
    except (UnidentifiedImageError, OSError, ValueError):
        return None
