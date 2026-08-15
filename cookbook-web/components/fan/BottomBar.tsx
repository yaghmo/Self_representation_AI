"use client"

import { useEffect, useState } from "react"
import { Link2, Plus } from "lucide-react"
import { getPublicSocials, type PublicSocial } from "@/lib/socialApi"

// lucide-react ^1.31.0 dropped all brand/logo icons (Instagram included),
// so the instagram case gets a small inline glyph instead of an import.
function InstagramIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
      <line x1="17.5" y1="6.5" x2="17.51" y2="6.5" />
    </svg>
  )
}

function platformIcon(platform: string) {
  if (platform === "instagram") return InstagramIcon
  return Link2
}

function BottomBar() {
  const [socials, setSocials] = useState<PublicSocial[]>([])

  useEffect(() => {
    getPublicSocials().then(setSocials)
  }, [])

  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex h-16 items-center justify-center gap-6 border-t border-border bg-background/95 backdrop-blur">
      {socials.map((social) => {
        const Icon = platformIcon(social.platform)
        return (
          <a
            key={social.id}
            href={social.url}
            target="_blank"
            rel="noreferrer"
            className="flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Icon className="size-5" />
          </a>
        )
      })}
      <div className="group relative flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground">
        <Plus className="size-5" />
        <span className="pointer-events-none absolute -top-8 rounded-md bg-foreground px-2 py-1 text-xs whitespace-nowrap text-background opacity-0 transition-opacity group-hover:opacity-100">
          More
        </span>
      </div>
    </nav>
  )
}

export { BottomBar }
