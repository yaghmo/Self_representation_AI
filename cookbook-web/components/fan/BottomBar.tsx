"use client"

import { useEffect, useState } from "react"
import { Plus } from "lucide-react"
import { getPublicSocials, type PublicSocial } from "@/lib/socialApi"
import { platformIcon } from "@/lib/platformIcon"

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
