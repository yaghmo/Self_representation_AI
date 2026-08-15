"use client"

import { Search } from "lucide-react"

function SearchBar({ expanded }: { expanded: boolean }) {
  const radius = expanded ? 9999 : 16
  const marginInline = expanded ? 64 : 0
  const topOffset = expanded ? 24 : 5
  const bgAlpha = expanded ? 15 : 97

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-30 flex justify-center px-4">
      <div
        className="pointer-events-auto flex w-full max-w-md items-center gap-2 border border-border/50 px-4 py-2 shadow-sm backdrop-blur transition-[margin,background-color] duration-500 ease-out"
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
          placeholder="Search"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
    </div>
  )
}

export { SearchBar }
