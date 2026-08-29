from pathlib import Path

import runtime.posts as posts_module
import runtime.social as social_module
import runtime.tiktok_oauth as tiktok_oauth_module
from runtime.social import add_social


def test_posts_self_check(tmp_path):
    original_posts_path = posts_module.POSTS_PATH
    original_profile_json = social_module.PROFILE_JSON_PATH
    original_tiktok_token_path = tiktok_oauth_module.TOKEN_PATH
    original_yt = posts_module.list_youtube_videos
    original_tw = posts_module.list_twitch_vods
    original_tk = posts_module.list_tiktok_videos
    original_ig = posts_module.list_instagram_posts
    original_x = posts_module.list_x_posts

    posts_module.list_youtube_videos = lambda url, limit: [
        {"kind": "video", "embedId": "yt1", "url": "https://y", "title": "t", "thumbnailUrl": "th"}
    ]
    posts_module.list_twitch_vods = lambda username, limit: [
        {"kind": "vod", "embedId": "tw1", "url": "https://t", "title": "t", "thumbnailUrl": None,
         "publishedAt": "2026-01-01T00:00:00Z"}
    ]
    posts_module.list_tiktok_videos = lambda url, limit: []
    posts_module.list_instagram_posts = lambda url, limit: [
        {"kind": "image", "embedId": "ig1", "url": "https://i", "title": "t", "thumbnailUrl": "th"}
    ]
    posts_module.list_x_posts = lambda url, limit: [
        {"kind": "post", "embedId": "x1", "url": "https://x", "title": None, "thumbnailUrl": None}
    ]

    try:
        posts_module.POSTS_PATH = tmp_path / "posts.json"
        social_module.PROFILE_JSON_PATH = tmp_path / "profile.json"
        # Deterministic "not connected" regardless of whatever the real
        # TikTok OAuth state on this machine happens to be — otherwise
        # a genuinely connected account would make this self-check hit
        # the real API instead of the stubbed scraper below.
        tiktok_oauth_module.TOKEN_PATH = tmp_path / "tiktok_token.json"

        assert posts_module.list_posts() == [], "no cache file yet -> empty list"
        assert posts_module.refresh_posts() == [], "no linked socials yet -> nothing to scrape"

        add_social({"platform": "youtube", "username": "h", "url": "https://youtube.com/@h"})
        add_social({"platform": "twitch", "username": "h2", "url": "https://twitch.tv/h2"})
        add_social({"platform": "instagram", "username": "h3", "url": "https://instagram.com/h3"})
        add_social({"platform": "x", "username": "h4", "url": "https://x.com/h4"})

        posts = posts_module.refresh_posts()
        assert len(posts) == 4
        assert {p["platform"] for p in posts} == {"youtube", "twitch", "instagram", "x"}
        for post in posts:
            assert post["id"] == f"{post['platform']}-{post['embedId']}"
            assert post["socialId"]
        assert posts_module.list_posts() == posts, "refresh must persist to the cache file"
    finally:
        posts_module.POSTS_PATH = original_posts_path
        social_module.PROFILE_JSON_PATH = original_profile_json
        tiktok_oauth_module.TOKEN_PATH = original_tiktok_token_path
        posts_module.list_youtube_videos = original_yt
        posts_module.list_twitch_vods = original_tw
        posts_module.list_tiktok_videos = original_tk
        posts_module.list_instagram_posts = original_ig
        posts_module.list_x_posts = original_x
