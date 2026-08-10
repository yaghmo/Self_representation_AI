import type { Message } from "./types";

const ENTRY = /^### (S-\d+)/m;

export function entryIdOf(entry: string): string {
  const match = ENTRY.exec(entry);
  return match ? match[1] : "";
}

export function entryFeeds(entry: string): string[] {
  for (const line of entry.split("\n")) {
    const stripped = line.trim().replace(/^-+/, "").trim();
    if (stripped.toLowerCase().startsWith("**feeds:**")) {
      const listed = stripped.split("**").slice(2).join("**").trim();
      return listed
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part && part !== "—");
    }
  }
  return [];
}

export async function buildFollowup(
  entry: string,
  readSection: (heading: string) => Promise<string>
): Promise<Message[]> {
  const entryId = entryIdOf(entry) || "the entry above";
  const sections = entryFeeds(entry);

  if (sections.length === 0) {
    return [
      {
        role: "user",
        content: `${entry}\n\nThis entry names no sections in its Feeds line, so there is nothing to add to the profile. Say so and stop.`,
      },
    ];
  }

  const current: string[] = [];
  for (const name of sections) {
    try {
      current.push(await readSection(name));
    } catch (exc) {
      current.push(`## ${name}\n[could not read this section: ${exc}]`);
    }
  }
  const joined = current.join("\n\n");

  const content =
    `This entry was just logged:\n\n${entry}\n\n` +
    `It feeds ${sections.length} section(s): ${sections.join(", ")}.\n` +
    `Here they are as they stand:\n\n${joined}\n\n` +
    `Record what ${entryId} says in each of those sections, one call at a time. The sections are above — you have everything you need, so do not go looking for more.\n\n` +
    `If the section already has a line for this field — an Age row, a Nationality row, a **Family:** bullet — use \`replace_profile_line\` on that line, keeping every cite it already carries and adding ${entryId}. Use \`add_profile_line\` only for a field that is not there at all. Never copy a line that is already in the section: leave the ones this entry does not change exactly as they are.\n\n` +
    `Every line you write carries ${entryId}. Match the shape already used — a row where there is a table, a bullet where there are bullets. One fact goes in one line: do not file the same thing again under a second label.\n\n` +
    `When the sections are done, say what you changed and stop.`;

  return [{ role: "user", content }];
}
