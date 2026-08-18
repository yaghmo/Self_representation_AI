"""Discord server metadata via the public, unauthenticated invite-resolve
endpoint — no bot token, no OAuth, verified directly against the live API
(a bare `curl`, not assumed from docs). Discord has no public per-user
profile page, only per-server invites, so what a creator shares is a
discord.gg/<code> link: "follower_count" here means the server's member
count and "bio" means the server's description.

Missing/expired invite, or any other failure, returns None — never blocks
adding the link, same contract as every other scraper here.
"""

from __future__ import annotations

import httpx

_INVITE_URL = "https://discord.com/api/v9/invites/{code}"


def scrape_invite(code: str) -> dict | None:
    try:
        response = httpx.get(
            _INVITE_URL.format(code=code),
            params={"with_counts": "true", "with_expiration": "true"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        guild = data.get("guild")
        if not guild:
            return None
        icon_hash = guild.get("icon")
        pfp_url = (
            f"https://cdn.discordapp.com/icons/{guild['id']}/{icon_hash}.png"
            if icon_hash
            else None
        )
        return {
            "pfp_url": pfp_url,
            "follower_count": data.get("approximate_member_count"),
            "bio": guild.get("description"),
        }
    except Exception:
        return None


def _self_check() -> None:
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_invite("discord-developers")
    assert result is not None, "expected a successful resolve of a real, stable invite"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"

    assert scrape_invite("this-should-not-exist-xyz123-nope") is None
    assert scrape_invite("not a valid code at all !!") is None

    print("discord_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
