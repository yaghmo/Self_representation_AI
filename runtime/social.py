"""Manual CRUD for the creator's linked social accounts.

No scraping, no third-party API calls — every field here is typed in by the
creator through the admin dialog. `data/profile.json` is a flat list, not
subject to the bible's cite/confirm-diff machinery in `tools.py`: this is
contact data the creator wants public, not a claim about the character that
needs a citation.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .bible import PROFILE_PATH
from .tools import snapshot

# admin_social_add/update/etc. run concurrently in FastAPI's threadpool —
# e.g. SocialDialog's Confirm fires several addSocial calls in parallel via
# Promise.allSettled. Without this, two threads racing _load()/_save() on
# the same file silently drop whichever wrote first.
_LOCK = threading.Lock()

PROFILE_JSON_PATH = PROFILE_PATH.parent / "profile.json"
IMAGES_DIR = PROFILE_PATH.parent / "images"
PFP_PATH = IMAGES_DIR / "pfp.img"
BANNER_PATH = IMAGES_DIR / "banner.img"
CHATICON_PATH = IMAGES_DIR / "chaticon.img"
LANDING_PFP_PATH = IMAGES_DIR / "landingpfp.img"

# A clip long enough to matter is long enough to matter in bytes too — this
# is a size cap, not a duration check (duration would need ffprobe or a
# client-side <video> metadata read; not worth it for a single-admin app).
MAX_MEDIA_BYTES = 20 * 1024 * 1024

_IMAGE_MAGIC: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def _sniff_media_type(data: bytes) -> str:
    for magic, mime in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    raise ValueError(f"not a recognized image/video format — starts with {data[:12]!r}")


# .mov shares the ftyp box with .mp4, so both sniff as "video/mp4" above —
# the only way to tell an alpha-carrying export (ProRes 4444, CineForm) apart
# from a plain h264 upload is to ask ffprobe what pixel format it decodes to.
_ALPHA_PIX_FMT_PREFIXES = ("yuva", "gbrap", "argb", "rgba", "abgr", "bgra", "ya8", "ayuv", "vuya")


def _has_alpha_channel(data: bytes) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip().startswith(_ALPHA_PIX_FMT_PREFIXES)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False  # no ffmpeg on this machine — fall back to storing as-is
    finally:
        tmp_path.unlink(missing_ok=True)


def _transcode_alpha_to_webm(data: bytes) -> bytes:
    """Browsers can't render alpha in mp4/mov — re-encode to VP9/webm, the
    one container+codec combo <video> actually composites transparency for."""
    with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as src:
        src.write(data)
        src_path = Path(src.name)
    dst_path = src_path.with_suffix(".webm")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_path), "-an", "-c:v", "libvpx-vp9",
             "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-b:v", "2M", str(dst_path)],
            capture_output=True, timeout=120, check=True,
        )
        return dst_path.read_bytes()
    except FileNotFoundError:
        raise ValueError("ffmpeg is not installed — required to convert an alpha video upload")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"ffmpeg failed to convert the alpha video: {exc.stderr.decode(errors='replace')}") from exc
    finally:
        src_path.unlink(missing_ok=True)
        dst_path.unlink(missing_ok=True)


def _transcode_gif_to_webm(data: bytes) -> bytes:
    """A raw <img> GIF loops forever with no playback control — transcode to
    webm so it goes through the same play-once-then-freeze <video> element
    (and can be re-triggered on a timer) as an uploaded video clip."""
    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as src:
        src.write(data)
        src_path = Path(src.name)
    dst_path = src_path.with_suffix(".webm")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_path), "-c:v", "libvpx-vp9",
             "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-b:v", "2M", str(dst_path)],
            capture_output=True, timeout=120, check=True,
        )
        return dst_path.read_bytes()
    except FileNotFoundError:
        raise ValueError("ffmpeg is not installed — required to convert a gif upload")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"ffmpeg failed to convert the gif: {exc.stderr.decode(errors='replace')}") from exc
    finally:
        src_path.unlink(missing_ok=True)
        dst_path.unlink(missing_ok=True)


def _save_image(path: Path, data: bytes) -> Path:
    if len(data) > MAX_MEDIA_BYTES:
        raise ValueError(f"upload too large ({len(data)} bytes, max {MAX_MEDIA_BYTES})")
    mime = _sniff_media_type(data)  # raises ValueError if unrecognized
    if mime == "video/mp4" and _has_alpha_channel(data):
        data = _transcode_alpha_to_webm(data)
    elif mime == "image/gif":
        data = _transcode_gif_to_webm(data)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        snapshot(path)
    path.write_bytes(data)
    return path


def save_pfp(data: bytes) -> Path:
    return _save_image(PFP_PATH, data)


def save_banner(data: bytes) -> Path:
    return _save_image(BANNER_PATH, data)


def save_chat_icon(data: bytes) -> Path:
    return _save_image(CHATICON_PATH, data)


def save_landing_pfp(data: bytes) -> Path:
    return _save_image(LANDING_PFP_PATH, data)


def read_pfp() -> tuple[bytes, str] | None:
    """(bytes, mime type), or None if no pfp has been uploaded."""
    if not PFP_PATH.exists():
        return None
    data = PFP_PATH.read_bytes()
    return data, _sniff_media_type(data)


def read_banner() -> tuple[bytes, str] | None:
    if not BANNER_PATH.exists():
        return None
    data = BANNER_PATH.read_bytes()
    return data, _sniff_media_type(data)


def read_chat_icon() -> tuple[bytes, str] | None:
    if not CHATICON_PATH.exists():
        return None
    data = CHATICON_PATH.read_bytes()
    return data, _sniff_media_type(data)


def read_landing_pfp() -> tuple[bytes, str] | None:
    if not LANDING_PFP_PATH.exists():
        return None
    data = LANDING_PFP_PATH.read_bytes()
    return data, _sniff_media_type(data)


def _image_version(path: Path) -> int | None:
    """mtime as an int, for cache-busting the fan-facing image URL — None if unset."""
    return int(path.stat().st_mtime) if path.exists() else None


def _peek_mime(path: Path) -> str | None:
    """Sniffed mime type without reading the whole file — cheap enough to
    call from a list endpoint even when the stored media is a multi-MB clip."""
    if not path.exists():
        return None
    with path.open("rb") as f:
        head = f.read(16)
    return _sniff_media_type(head)


class SocialNotFound(Exception):
    """Raised by update_social/delete_social when `id` doesn't match anything."""


class SocialAlreadyExists(Exception):
    """Raised by add_social when platform+username is already linked —
    same account re-added via a second Confirm, a re-run bio-mention batch,
    or pasting the same link twice."""


def _load() -> dict:
    if not PROFILE_JSON_PATH.exists():
        return {"bio": None, "contactEmail": None, "socials": []}
    data = json.loads(PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    return {
        "bio": data.get("bio"),
        "contactEmail": data.get("contactEmail"),
        "socials": data.get("socials", []),
    }


def _save(bio: str | None, contact_email: str | None, socials: list[dict]) -> None:
    PROFILE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_JSON_PATH.write_text(
        json.dumps(
            {"version": 1, "bio": bio, "contactEmail": contact_email, "socials": socials},
            indent=2,
        ),
        encoding="utf-8",
    )


def pfp_version() -> int | None:
    return _image_version(PFP_PATH)


def banner_version() -> int | None:
    return _image_version(BANNER_PATH)


def chaticon_version() -> int | None:
    return _image_version(CHATICON_PATH)


def pfp_mime() -> str | None:
    return _peek_mime(PFP_PATH)


def banner_mime() -> str | None:
    return _peek_mime(BANNER_PATH)


def chaticon_mime() -> str | None:
    return _peek_mime(CHATICON_PATH)


def landing_pfp_version() -> int | None:
    return _image_version(LANDING_PFP_PATH)


def landing_pfp_mime() -> str | None:
    return _peek_mime(LANDING_PFP_PATH)


def list_socials() -> list[dict]:
    return _load()["socials"]


def get_bio() -> str | None:
    return _load()["bio"]


def set_bio(text: str) -> None:
    with _LOCK:
        data = _load()
        _save(text, data["contactEmail"], data["socials"])


def get_contact_email() -> str | None:
    return _load()["contactEmail"]


def set_contact_email(email: str | None) -> None:
    with _LOCK:
        data = _load()
        _save(data["bio"], email, data["socials"])


def _is_cleaner_username(candidate: str, incumbent: str, known_handles: set[str]) -> bool:
    """Best-effort pick between two links for the same real profile — e.g. a
    Discord vanity invite (discord.gg/Name) over its raw invite code
    (discord.gg/B32WjjMp27). Prefers whichever matches the creator's handle
    elsewhere in the profile; falls back to "has no digits", since an
    auto-generated code almost always mixes them in and a chosen vanity
    name almost never does. Ties keep the incumbent — no reason to churn
    data when neither signal picks a winner."""
    candidate = candidate.lstrip("@").lower()
    incumbent = incumbent.lstrip("@").lower()
    candidate_known, incumbent_known = candidate in known_handles, incumbent in known_handles
    if candidate_known != incumbent_known:
        return candidate_known
    candidate_digits = any(c.isdigit() for c in candidate)
    incumbent_digits = any(c.isdigit() for c in incumbent)
    if candidate_digits != incumbent_digits:
        return not candidate_digits
    return False


def add_social(fields: dict) -> dict:
    """`fields` must include platform, username, url; may include bio,
    followerCount, pfpUrl, isAlt. Generates `id`, appends, saves."""
    with _LOCK:
        data = _load()
        socials = data["socials"]
        new_pfp = fields.get("pfpUrl")
        for existing in socials:
            if existing["platform"].lower() != fields["platform"].lower():
                continue
            if existing["username"].lower() == fields["username"].lower():
                raise SocialAlreadyExists(f"{fields['platform']}:{fields['username']}")
            # Same platform, different username string, but the exact same
            # scraped pfp — e.g. a Discord vanity invite (discord.gg/Name)
            # and its raw invite code, or a YouTube handle with different
            # "@"/casing: different literal links, same real profile. The
            # username alone won't catch that; an identical pfp URL will.
            if new_pfp and existing.get("pfpUrl") == new_pfp:
                known_handles = {
                    s["username"].lstrip("@").lower() for s in socials if s is not existing
                }
                if _is_cleaner_username(fields["username"], existing["username"], known_handles):
                    existing["username"] = fields["username"]
                    existing["url"] = fields["url"]
                    _save(data["bio"], data["contactEmail"], socials)
                    return existing
                raise SocialAlreadyExists(f"{fields['platform']}:{fields['username']}")
        entry = {
            "id": f"{fields['platform']}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
            "platform": fields["platform"],
            "username": fields["username"],
            "url": fields["url"],
            "bio": fields.get("bio"),
            "followerCount": fields.get("followerCount"),
            "pfpUrl": fields.get("pfpUrl"),
            "isAlt": fields.get("isAlt", False),
        }
        socials.append(entry)
        _save(data["bio"], data["contactEmail"], socials)
        return entry


def update_social(id: str, fields: dict) -> dict:
    """`fields` should already be filtered to only the keys the caller wants
    changed — this function overwrites exactly what it's given, nothing
    more, so an unset field a caller left out is not touched."""
    with _LOCK:
        data = _load()
        socials = data["socials"]
        for entry in socials:
            if entry["id"] == id:
                entry.update(fields)
                _save(data["bio"], data["contactEmail"], socials)
                return entry
        raise SocialNotFound(id)


def delete_social(id: str) -> None:
    with _LOCK:
        data = _load()
        socials = data["socials"]
        remaining = [e for e in socials if e["id"] != id]
        if len(remaining) == len(socials):
            raise SocialNotFound(id)
        _save(data["bio"], data["contactEmail"], remaining)
