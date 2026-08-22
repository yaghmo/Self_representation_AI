import pytest

from runtime.stories import MalformedStory, next_event_id, next_story_id, parse_story, render_story


def test_stories_self_check():
    text = (
        "# ST-001 — a weekend hiking trip\n"
        "**Summary:** the guide at the trailhead, the storm, getting back after dark\n"
        "**Keywords:** hiking, mountains, weather\n"
        "**Logged:** [~early 2026]\n"
        "\n"
        "## E-001 — meeting the guide\n"
        "He was already waiting when we pulled in.\n"
        "\n"
        "## E-002 — the storm\n"
        "It came in fast on the second afternoon.\n"
    )

    story = parse_story(text)
    assert story.id == "ST-001", story.id
    assert story.title == "a weekend hiking trip", story.title
    assert story.keywords == ["hiking", "mountains", "weather"], story.keywords
    assert story.logged == "[~early 2026]", story.logged
    assert [e.id for e in story.events] == ["E-001", "E-002"]
    assert story.events[1].title == "the storm"
    assert story.events[0].text.strip() == "He was already waiting when we pulled in."

    # Round-trip is exact. The index is derived from these files, so a render
    # that reflows text would silently re-embed chunks that never changed.
    assert render_story(story) == text, "round-trip changed the file"

    # Amending an event edits its text and leaves every id alone. Renumbering
    # would break stable-id ordering, and with it the KV prefix cache.
    story.events[0].text = "He was already waiting, red jacket, when we pulled in.\n"
    amended = parse_story(render_story(story))
    assert [e.id for e in amended.events] == ["E-001", "E-002"], "ids moved"
    assert "red jacket" in amended.events[0].text

    # Ids are allocated from the maximum, never from the count — a deleted
    # event must not free its number for reuse.
    assert next_story_id(["ST-001", "ST-004"]) == "ST-005"
    assert next_story_id([]) == "ST-001"
    assert next_event_id(story) == "E-003"

    malformed = "no heading here\n"
    with pytest.raises(MalformedStory):
        parse_story(malformed)

    # Trailing significant whitespace (markdown hard breaks) must survive round-trip.
    # This catches silent data loss from over-aggressive whitespace stripping.
    text_with_hardbreak = (
        "# ST-002 — test\n"
        "**Summary:** test\n"
        "**Keywords:** test\n"
        "**Logged:** test\n"
        "\n"
        "## E-001 — line with hard break\n"
        "End with two spaces  \n"  # Two trailing spaces = markdown hard line break
    )
    story_hb = parse_story(text_with_hardbreak)
    assert "  \n" in story_hb.events[0].text, "trailing spaces lost in parse"
    rendered_hb = render_story(story_hb)
    assert "  \n" in rendered_hb, "trailing spaces lost in render"
    assert rendered_hb == text_with_hardbreak, "round-trip with trailing spaces failed"
