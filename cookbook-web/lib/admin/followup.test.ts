import { describe, expect, it } from "vitest";
import { buildFollowup, entryFeeds, entryIdOf } from "./followup";

const ENTRY = [
  "### S-042",
  "- **Date:** 2026-01-09",
  "- **Q:** placeholder question",
  "- **A:** placeholder answer",
  "- **Feeds:** 0. At a Glance, 6. Voice",
].join("\n");

describe("entryIdOf", () => {
  it("extracts the S-### an entry declares", () => {
    expect(entryIdOf(ENTRY)).toBe("S-042");
  });
  it("returns empty string when there is no entry heading", () => {
    expect(entryIdOf("no heading here")).toBe("");
  });
});

describe("entryFeeds", () => {
  it("parses the comma-separated Feeds line", () => {
    expect(entryFeeds(ENTRY)).toEqual(["0. At a Glance", "6. Voice"]);
  });
  it("returns an empty list for an em-dash Feeds line", () => {
    expect(entryFeeds("### S-043\n- **Feeds:** —\n")).toEqual([]);
  });
});

describe("buildFollowup", () => {
  it("reads each fed section once and includes the entry and current content", async () => {
    const asked: string[] = [];
    const readSection = async (heading: string) => {
      asked.push(heading);
      return `## ${heading}\n- existing line [S-001]\n`;
    };

    const task = await buildFollowup(ENTRY, readSection);
    expect(asked).toEqual(["0. At a Glance", "6. Voice"]);
    expect(task.length).toBe(1);
    expect(task[0].role).toBe("user");
    expect(task[0].content).toContain("S-042");
    expect(task[0].content).toContain("placeholder answer");
    expect(task[0].content).toContain("existing line [S-001]");
    expect(task[0].content).toContain("at a time");
  });

  it("says there is nothing to add when Feeds names no sections", async () => {
    const task = await buildFollowup("### S-043\n- **Feeds:** —\n", async () => "");
    expect(task[0].content).toContain("nothing to add");
  });

  it("reports a section that fails to read instead of throwing", async () => {
    const readSection = async (heading: string) => {
      throw new Error(`no section ${heading}`);
    };
    const task = await buildFollowup(ENTRY, readSection);
    expect(task[0].content).toContain("could not read this section: no section");
    expect(task[0].content).not.toContain("Error: no section");
  });
});
