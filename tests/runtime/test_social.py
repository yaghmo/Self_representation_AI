import os
import shutil
import subprocess
import tempfile

import pytest

import runtime.social as social_module
from runtime.social import (
    SocialAlreadyExists,
    SocialNotFound,
    add_social,
    chaticon_version,
    delete_social,
    get_bio,
    get_contact_email,
    landing_pfp_version,
    list_socials,
    pfp_mime,
    pfp_version,
    read_banner,
    read_chat_icon,
    read_landing_pfp,
    read_pfp,
    save_banner,
    save_chat_icon,
    save_landing_pfp,
    save_pfp,
    set_bio,
    set_contact_email,
    update_social,
)


def test_social_self_check(tmp_path):
    original = social_module.PROFILE_JSON_PATH
    original_images = (social_module.IMAGES_DIR, social_module.PFP_PATH, social_module.BANNER_PATH)
    try:
        social_module.PROFILE_JSON_PATH = tmp_path / "profile.json"
        social_module.IMAGES_DIR = tmp_path / "images"
        social_module.PFP_PATH = social_module.IMAGES_DIR / "pfp.img"
        social_module.BANNER_PATH = social_module.IMAGES_DIR / "banner.img"
        IMAGES_DIR = social_module.IMAGES_DIR

        assert list_socials() == [], "a fresh directory has no socials"
        assert get_bio() is None, "a fresh directory has no bio"
        assert get_contact_email() is None, "a fresh directory has no contact email"
        set_bio("a combined bio")
        assert get_bio() == "a combined bio"
        set_contact_email("biz@example.com")
        assert get_contact_email() == "biz@example.com"
        assert get_bio() == "a combined bio", "setting contact email must not touch the bio"

        entry = add_social({
            "platform": "instagram",
            "username": "handle",
            "url": "https://instagram.com/handle",
            "bio": "a bio",
            "followerCount": 100,
        })
        assert entry["id"].startswith("instagram-")
        assert get_contact_email() == "biz@example.com", "adding a social must not touch the contact email"
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

        # Same platform, same pfp, different literal link: raw invite
        # code first, then the human-chosen vanity that also matches
        # the creator's handle elsewhere in the profile — the vanity
        # wins and replaces the raw code in place.
        add_social({
            "platform": "x",
            "username": "keshaeuw",
            "url": "https://x.com/keshaeuw",
        })
        raw = add_social({
            "platform": "discord",
            "username": "B32WjjMp27",
            "url": "https://discord.gg/B32WjjMp27",
            "pfpUrl": "https://cdn.discordapp.com/icons/1/icon.png",
        })
        swapped = add_social({
            "platform": "discord",
            "username": "KeshaEuw",
            "url": "https://discord.gg/KeshaEuw",
            "pfpUrl": "https://cdn.discordapp.com/icons/1/icon.png",
        })
        assert swapped["id"] == raw["id"], "the same server's row is updated in place, not duplicated"
        assert swapped["username"] == "KeshaEuw"
        assert swapped["url"] == "https://discord.gg/KeshaEuw"
        assert sum(1 for s in list_socials() if s["platform"] == "discord") == 1

        # Neither side matches a known handle — falls back to
        # "no digits beats digits".
        plain = add_social({
            "platform": "telegram",
            "username": "a1b2c3",
            "url": "https://t.me/a1b2c3",
            "pfpUrl": "https://cdn.example.com/tg-icon.png",
        })
        cleaner = add_social({
            "platform": "telegram",
            "username": "cleanname",
            "url": "https://t.me/cleanname",
            "pfpUrl": "https://cdn.example.com/tg-icon.png",
        })
        assert cleaner["id"] == plain["id"]
        assert cleaner["username"] == "cleanname"

        # A genuine tie (same digit-ness, neither a known handle) keeps
        # the incumbent rather than churning data over a coin flip.
        first = add_social({
            "platform": "throne",
            "username": "aaa111",
            "url": "https://throne.com/aaa111",
            "pfpUrl": "https://cdn.example.com/throne-icon.png",
        })
        try:
            add_social({
                "platform": "throne",
                "username": "bbb222",
                "url": "https://throne.com/bbb222",
                "pfpUrl": "https://cdn.example.com/throne-icon.png",
            })
        except SocialAlreadyExists:
            pass
        else:
            raise AssertionError("a tied duplicate must be rejected, not silently swapped")
        assert list_socials()[-1]["username"] == "aaa111", "the incumbent must survive a tie"

        assert read_pfp() is None
        assert pfp_version() is None
        png = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
        save_pfp(png)
        data, mime = read_pfp()
        assert data == png and mime == "image/png"
        assert pfp_version() is not None
        assert not (IMAGES_DIR / ".backups").exists(), (
            "first pfp write has nothing to snapshot"
        )
        jpg = b"\xff\xd8\xff" + b"fake-jpg-bytes"
        save_pfp(jpg)
        assert read_pfp() == (jpg, "image/jpeg")
        assert len(list((IMAGES_DIR / ".backups").iterdir())) == 1, (
            "second pfp write must snapshot the first"
        )

        assert read_banner() is None
        webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"fake-webp-bytes"
        save_banner(webp)
        assert read_banner() == (webp, "image/webp")

        try:
            save_pfp(b"not an image")
        except ValueError:
            pass
        else:
            raise AssertionError("save_pfp accepted non-image bytes")
    finally:
        social_module.PROFILE_JSON_PATH = original
        social_module.IMAGES_DIR, social_module.PFP_PATH, social_module.BANNER_PATH = original_images


def test_save_media_rejects_oversized_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")

    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * social_module.MAX_MEDIA_BYTES
    try:
        save_pfp(oversized)
    except ValueError:
        pass
    else:
        raise AssertionError("save_pfp accepted an upload over MAX_MEDIA_BYTES")


def test_save_media_accepts_mp4_and_webm(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")
    monkeypatch.setattr(social_module, "BANNER_PATH", social_module.IMAGES_DIR / "banner.img")

    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-bytes"
    save_pfp(mp4)
    assert read_pfp() == (mp4, "video/mp4")

    webm = b"\x1a\x45\xdf\xa3" + b"fake-webm-bytes"
    save_banner(webm)
    assert read_banner() == (webm, "video/webm")


def test_chat_icon_slot_mirrors_pfp(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "CHATICON_PATH", social_module.IMAGES_DIR / "chaticon.img")

    assert read_chat_icon() is None
    assert chaticon_version() is None

    png = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
    save_chat_icon(png)
    assert read_chat_icon() == (png, "image/png")
    assert chaticon_version() is not None


def test_landing_pfp_slot_mirrors_pfp(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(
        social_module, "LANDING_PFP_PATH", social_module.IMAGES_DIR / "landingpfp.img"
    )

    assert read_landing_pfp() is None
    assert landing_pfp_version() is None

    png = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
    save_landing_pfp(png)
    assert read_landing_pfp() == (png, "image/png")
    assert landing_pfp_version() is not None


def test_pfp_mime_reflects_stored_type_without_full_read(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")

    assert pfp_mime() is None
    save_pfp(b"\xff\xd8\xff" + b"fake-jpg-bytes")
    assert pfp_mime() == "image/jpeg"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_save_media_transcodes_alpha_mov_to_webm(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")

    with tempfile.NamedTemporaryFile(suffix=".mov", delete=False) as mov:
        mov_path = mov.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red@0.5:s=32x32:d=1:r=10",
             "-pix_fmt", "yuva420p", "-c:v", "qtrle", mov_path],
            capture_output=True, check=True,
        )
        alpha_mov = open(mov_path, "rb").read()
    finally:
        os.unlink(mov_path)

    save_pfp(alpha_mov)
    data, mime = read_pfp()
    assert mime == "video/webm", "an alpha mov must be transcoded, not stored as-is"
    assert data.startswith(b"\x1a\x45\xdf\xa3"), "the stored bytes must actually be a webm"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_save_media_transcodes_gif_to_webm(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")

    with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as gif:
        gif_path = gif.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=1:r=10", gif_path],
            capture_output=True, check=True,
        )
        gif_bytes = open(gif_path, "rb").read()
    finally:
        os.unlink(gif_path)

    assert gif_bytes[:6] in (b"GIF87a", b"GIF89a")
    save_pfp(gif_bytes)
    data, mime = read_pfp()
    assert mime == "video/webm", "a gif upload must be transcoded, not stored as-is"
    assert data.startswith(b"\x1a\x45\xdf\xa3"), "the stored bytes must actually be a webm"


def test_save_media_leaves_alpha_free_mp4_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(social_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(social_module, "PFP_PATH", social_module.IMAGES_DIR / "pfp.img")

    # Not a decodable video, so ffprobe (if present) fails and alpha
    # detection falls back to False — the existing passthrough behavior.
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-bytes"
    save_pfp(mp4)
    assert read_pfp() == (mp4, "video/mp4")
