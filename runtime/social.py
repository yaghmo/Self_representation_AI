"""Manual CRUD for the creator's linked social accounts.

No scraping, no third-party API calls — every field here is typed in by the
creator through the admin dialog. `data/profile.json` is a flat list, not
subject to the bible's cite/confirm-diff machinery in `tools.py`: this is
contact data the creator wants public, not a claim about the character that
needs a citation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .bible import PROFILE_PATH

PROFILE_JSON_PATH = PROFILE_PATH.parent / "profile.json"


class SocialNotFound(Exception):
    """Raised by update_social/delete_social when `id` doesn't match anything."""


def _load() -> dict:
    if not PROFILE_JSON_PATH.exists():
        return {"bio": None, "socials": []}
    data = json.loads(PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    return {"bio": data.get("bio"), "socials": data.get("socials", [])}


def _save(bio: str | None, socials: list[dict]) -> None:
    PROFILE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_JSON_PATH.write_text(
        json.dumps({"version": 1, "bio": bio, "socials": socials}, indent=2),
        encoding="utf-8",
    )


def list_socials() -> list[dict]:
    return _load()["socials"]


def get_bio() -> str | None:
    return _load()["bio"]


def set_bio(text: str) -> None:
    data = _load()
    _save(text, data["socials"])


def add_social(fields: dict) -> dict:
    """`fields` must include platform, username, url; may include bio,
    followerCount, pfpUrl, isAlt. Generates `id`, appends, saves."""
    data = _load()
    socials = data["socials"]
    entry = {
        "id": f"{fields['platform']}-{int(time.time() * 1000)}",
        "platform": fields["platform"],
        "username": fields["username"],
        "url": fields["url"],
        "bio": fields.get("bio"),
        "followerCount": fields.get("followerCount"),
        "pfpUrl": fields.get("pfpUrl"),
        "isAlt": fields.get("isAlt", False),
    }
    socials.append(entry)
    _save(data["bio"], socials)
    return entry


def update_social(id: str, fields: dict) -> dict:
    """`fields` should already be filtered to only the keys the caller wants
    changed — this function overwrites exactly what it's given, nothing
    more, so an unset field a caller left out is not touched."""
    data = _load()
    socials = data["socials"]
    for entry in socials:
        if entry["id"] == id:
            entry.update(fields)
            _save(data["bio"], socials)
            return entry
    raise SocialNotFound(id)


def delete_social(id: str) -> None:
    data = _load()
    socials = data["socials"]
    remaining = [e for e in socials if e["id"] != id]
    if len(remaining) == len(socials):
        raise SocialNotFound(id)
    _save(data["bio"], remaining)


def _self_check() -> None:
    import tempfile

    global PROFILE_JSON_PATH
    original = PROFILE_JSON_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            PROFILE_JSON_PATH = Path(tmp) / "profile.json"

            assert list_socials() == [], "a fresh directory has no socials"
            assert get_bio() is None, "a fresh directory has no bio"
            set_bio("a combined bio")
            assert get_bio() == "a combined bio"

            entry = add_social({
                "platform": "instagram",
                "username": "handle",
                "url": "https://instagram.com/handle",
                "bio": "a bio",
                "followerCount": 100,
            })
            assert entry["id"].startswith("instagram-")
            assert entry["isAlt"] is False, "isAlt defaults to False"
            assert entry["pfpUrl"] is None, "unset optional fields are None"
            assert list_socials() == [entry]

            updated = update_social(entry["id"], {"followerCount": 200})
            assert updated["followerCount"] == 200
            assert updated["bio"] == "a bio", "fields not in the update are untouched"
            assert list_socials()[0]["followerCount"] == 200

            second = add_social({
                "platform": "instagram",
                "username": "handle2",
                "url": "https://instagram.com/handle2",
                "isAlt": True,
            })
            assert second["isAlt"] is True
            assert len(list_socials()) == 2
            assert get_bio() == "a combined bio", "adding a social must not touch the bio"

            delete_social(entry["id"])
            remaining = list_socials()
            assert len(remaining) == 1
            assert remaining[0]["id"] == second["id"]

            try:
                update_social("no-such-id", {"bio": "x"})
            except SocialNotFound:
                pass
            else:
                raise AssertionError("update_social accepted an unknown id")

            try:
                delete_social("no-such-id")
            except SocialNotFound:
                pass
            else:
                raise AssertionError("delete_social accepted an unknown id")
    finally:
        PROFILE_JSON_PATH = original

    print("social: all checks passed")


if __name__ == "__main__":
    _self_check()
