"use client"

import { useEffect, useState } from "react"
import { Plus } from "lucide-react"
import { getPublicSocials, type PublicSocial } from "@/lib/socialApi"
import { platformIcon } from "@/lib/platformIcon"
import { SocialListDialog } from "@/components/fan/SocialListDialog"

const VISIBLE_COUNT = 3

function BottomBar() {
  const [socials, setSocials] = useState<PublicSocial[]>([])
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    getPublicSocials().then(setSocials)
  }, [])

  const visible = socials.slice(0, VISIBLE_COUNT)
  const hasMore = socials.length > VISIBLE_COUNT

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-20 flex h-16 items-center justify-center gap-6 border-t border-border bg-background/95 backdrop-blur">
        {visible.map((social) => {
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
        {hasMore && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="group relative flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Plus className="size-5" />
            <span className="pointer-events-none absolute -top-8 rounded-md bg-foreground px-2 py-1 text-xs whitespace-nowrap text-background opacity-0 transition-opacity group-hover:opacity-100">
              More
            </span>
          </button>
        )}
      </nav>
      {showAll && <SocialListDialog socials={socials} onClose={() => setShowAll(false)} />}
    </>
  )
}

export { BottomBar }
