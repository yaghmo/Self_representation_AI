export const TOOL_SCHEMAS: Record<string, unknown>[] = [
  {
    type: "function",
    function: {
      name: "search_sources",
      description:
        "Search the creator's logged answers. Returns whole entries whose text contains every word of the query. Capped — narrow the query rather than asking for more.",
      parameters: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_profile_section",
      description:
        "Read one section of the character profile. Use the heading exactly as listed in the system prompt.",
      parameters: {
        type: "object",
        properties: { heading: { type: "string" } },
        required: ["heading"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "append_source",
      description:
        "Propose appending a new entry to the sources file, verbatim, inside the Source log section. The entry id is assigned automatically. The creator must approve before anything is written.",
      parameters: {
        type: "object",
        properties: {
          answer: { type: "string", description: "The creator's answer, verbatim — do not tidy the phrasing." },
          question: { type: "string", description: "The question as asked, verbatim." },
          entry_type: {
            type: "string",
            description: "One of: direct answer | interview | public post | observed event | existing bio.",
          },
          tags: {
            type: "array",
            items: { type: "string" },
            description: "Short topic tags, e.g. personality, fears.",
          },
          date: {
            type: "string",
            description:
              "YYYY-MM-DD the answer was given, fuzzed per the redaction policy if needed. Use the literal string 'unknown' if the date is not known — today's date is filled in for you. Never guess a date.",
          },
          feeds: {
            type: "array",
            items: { type: "string" },
            description: "Profile sections this entry should feed, e.g. '6. Voice'.",
          },
        },
        required: ["answer", "question", "entry_type", "tags", "date", "feeds"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "add_profile_line",
      description:
        "Propose adding ONE line to a profile section. Read the section first so you do not repeat something already there. The line must carry the cite of the entry it comes from, e.g. '- **Lives in:** Berlin [S-075]'. Everything else in the file stays exactly as it is. The creator must approve.",
      parameters: {
        type: "object",
        properties: {
          heading: { type: "string", description: "Section heading, exactly as listed in the system prompt." },
          line: {
            type: "string",
            description: "The single line to add, including its [S-###] cite. Match the bullet style already used in that section.",
          },
        },
        required: ["heading", "line"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "replace_profile_line",
      description:
        "Propose rewriting ONE existing line in a profile section. Read the section first. `find` must identify exactly one line — if it matches several the call is refused. Keep every [S-###] cite the old line carried unless it's listed in `retracting`; add the new one alongside. The creator must approve.",
      parameters: {
        type: "object",
        properties: {
          heading: { type: "string", description: "Section heading, exactly as listed in the system prompt." },
          find: { type: "string", description: "Distinctive text from the line to replace, e.g. 'Where they're from'." },
          line: { type: "string", description: "The full replacement line, cites included." },
          retracting: {
            type: "array",
            items: { type: "string" },
            description:
              "S-### cites this rewrite deliberately drops, e.g. ['S-075'] — use when the line carries more than one fact and only some are being retracted. Any cite missing from the new line that isn't listed here still refuses the edit.",
          },
        },
        required: ["heading", "find", "line"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "remove_profile_line",
      description:
        "Propose removing ONE existing line from a profile section — use when the creator wants a fact retracted, e.g. 'remove that I have siblings'. Read the section first. `find` must identify exactly one line — if it matches several the call is refused. The cited source entry is left in sources.md untouched; only the profile's line goes. The creator must approve.",
      parameters: {
        type: "object",
        properties: {
          heading: { type: "string", description: "Section heading, exactly as listed in the system prompt." },
          find: { type: "string", description: "Distinctive text from the line to remove, e.g. 'Has a younger sister'." },
        },
        required: ["heading", "find"],
      },
    },
  },
];

const FOLLOWUP_TOOL_NAMES = new Set(["add_profile_line", "replace_profile_line"]);

export const FOLLOWUP_SCHEMAS: Record<string, unknown>[] = TOOL_SCHEMAS.filter(
  (schema) => FOLLOWUP_TOOL_NAMES.has((schema.function as { name: string }).name)
);
