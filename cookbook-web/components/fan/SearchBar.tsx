"use client"

import { useMemo, useState } from "react"
import { Search } from "lucide-react"
import type { Post } from "./types"

// De-duped on lowercase so "#Travel" and "#travel" in different captions
// collapse to one suggestion, keeping whichever casing was seen first.
function extractHashtags(posts: Post[]): string[] {
  const seen = new Map<string, string>()
  for (const post of posts) {
    if (!post.title) continue
    for (const match of post.title.matchAll(/#\w+/g)) {
      const key = match[0].toLowerCase()
      if (!seen.has(key)) seen.set(key, match[0])
    }
  }
  return [...seen.values()]
}

function SearchBar({
  expanded,
  posts,
  value,
  onChange,
}: {
  expanded: boolean
  posts: Post[]
  value: string
  onChange: (value: string) => void
}) {
  const [isFocused, setIsFocused] = useState(false)
  const radius = expanded ? 9999 : 16
  const marginInline = expanded ? 64 : 0
  const topOffset = expanded ? 24 : 5
  const bgAlpha = expanded ? 15 : 97

  const hashtags = useMemo(() => extractHashtags(posts), [posts])
  const query = value.replace(/^#/, "").toLowerCase()
  const suggestions = isFocused
    ? hashtags.filter((tag) => tag.slice(1).toLowerCase().includes(query))
    : []

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-30 flex justify-center px-4">
      <div
        className="pointer-events-auto relative flex w-full max-w-md items-center gap-2 border border-border/50 px-4 py-2 shadow-sm backdrop-blur transition-[margin,background-color] duration-500 ease-out"
        style={{
          borderRadius: radius,
          marginInline,
          marginTop: topOffset,
          backgroundColor: `color-mix(in oklch, var(--background) ${bgAlpha}%, transparent)`,
        }}
      >
        <Search className="size-4 shrink-0 text-muted-foreground" />
        <input
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder="Search #hashtag"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />

        {suggestions.length > 0 && (
          <div className="absolute inset-x-0 top-full mt-2 max-h-60 overflow-y-auto rounded-2xl border border-border bg-popover p-1 text-popover-foreground shadow-lg">
            {suggestions.map((tag) => (
              <button
                key={tag}
                type="button"
                // mousedown fires before the input's blur, so the click
                // lands before the dropdown would otherwise close itself
                onMouseDown={(event) => {
                  event.preventDefault()
                  onChange(tag)
                  setIsFocused(false)
                }}
                className="block w-full rounded-lg px-3 py-1.5 text-left text-sm hover:bg-muted"
              >
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export { SearchBar }
