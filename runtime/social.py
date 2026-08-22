"""Manual CRUD for the creator's linked social accounts.

No scraping, no third-party API calls — every field here is typed in by the
creator through the admin dialog. `data/profile.json` is a flat list, not
subject to the bible's cite/confirm-diff machinery in `tools.py`: this is
contact data the creator wants public, not a claim about the character that
needs a citation.
"""

from __future__ import annotations

import json
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

_IMAGE_MAGIC: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def _sniff_image_type(data: bytes) -> str:
    for magic, mime in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError(f"not a recognized image format — starts with {data[:12]!r}")


def _save_image(path: Path, data: bytes) -> Path:
    _sniff_image_type(data)  # raises ValueError if unrecognized
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        snapshot(path)
    path.write_bytes(data)
    return path


def save_pfp(data: bytes) -> Path:
    return _save_image(PFP_PATH, data)


def save_banner(data: bytes) -> Path:
    return _save_image(BANNER_PATH, data)


def read_pfp() -> tuple[bytes, str] | None:
    """(bytes, mime type), or None if no pfp has been uploaded."""
    if not PFP_PATH.exists():
        return None
    data = PFP_PATH.read_bytes()
    return data, _sniff_image_type(data)


def read_banner() -> tuple[bytes, str] | None:
    if not BANNER_PATH.exists():
        return None
    data = BANNER_PATH.read_bytes()
    return data, _sniff_image_type(data)


def _image_version(path: Path) -> int | None:
    """mtime as an int, for cache-busting the fan-facing image URL — None if unset."""
    return int(path.stat().st_mtime) if path.exists() else None


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
