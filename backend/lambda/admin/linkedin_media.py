"""Byte rules for a LinkedIn draft attachment.

Pictures stay PNG or JPEG under the existing cap. A GIF stays a GIF. A video
is an H.264 MP4. Character photos keep the picture rule.
"""

from __future__ import annotations

GIF_BYTE_MAX = 3_000_000
VIDEO_BYTE_MAX = 3_000_000
VIDEO_BYTE_MIN = 75_000
# Major brands LinkedIn can play. QuickTime (``qt  ``) and HEVC are not in this set.
_MP4_BRANDS = frozenset({b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V "})


def is_mp4(data: bytes) -> bool:
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _MP4_BRANDS


def check_picture(content_type: str, data: bytes) -> None:
    """PNG or JPEG under the stored picture cap. Used for character photos too."""
    from linkedin_store import IMAGE_BYTE_MAX, LinkedInError

    if content_type not in ("image/png", "image/jpeg"):
        raise LinkedInError("Use a PNG or JPEG image.")
    if not data or len(data) > IMAGE_BYTE_MAX:
        raise LinkedInError("The image must be under 1.5 MB.")
    if content_type == "image/png" and not data.startswith(b"\x89PNG"):
        raise LinkedInError("That file is not a PNG.")
    if content_type == "image/jpeg" and not data.startswith(b"\xff\xd8"):
        raise LinkedInError("That file is not a JPEG.")


def check_post_media(content_type: str, data: bytes) -> None:
    """What a draft may store: a picture, a GIF, or an H.264 MP4."""
    from linkedin_store import LinkedInError

    if content_type in ("image/png", "image/jpeg"):
        check_picture(content_type, data)
        return
    if content_type == "image/gif":
        if not data or len(data) > GIF_BYTE_MAX:
            raise LinkedInError("That GIF must be under 3 MB.")
        if not data.startswith((b"GIF87a", b"GIF89a")):
            raise LinkedInError("That file is not a GIF.")
        return
    if content_type == "video/mp4":
        if len(data) < VIDEO_BYTE_MIN:
            raise LinkedInError("LinkedIn needs a video of at least 75 KB.")
        if len(data) > VIDEO_BYTE_MAX:
            raise LinkedInError("The video must be under 3 MB.")
        if not is_mp4(data):
            raise LinkedInError("That file is not an MP4 video.")
        return
    raise LinkedInError("Use a PNG, JPEG, GIF, or MP4 video.")
