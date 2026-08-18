"use client"

import { Play } from "lucide-react"
import { platformIcon } from "@/lib/platformIcon"
import type { Post } from "./types"

function PostCard({ post, onOpen }: { post: Post; onOpen: (post: Post) => void }) {
  const Icon = platformIcon(post.platform)
  return (
    <button
      type="button"
      onClick={() => onOpen(post)}
      className="group relative aspect-[3/4] overflow-hidden rounded-md bg-muted"
    >
      {post.thumbnailUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- third-party platform thumbnail, not a next/image remote host
        <img src={post.thumbnailUrl} alt="" className="size-full object-cover" />
      ) : (
        <div className="flex size-full items-center justify-center">
          <Icon className="size-8 text-muted-foreground" />
        </div>
      )}
      <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/30">
        <Play className="size-8 fill-white text-white opacity-0 drop-shadow transition-opacity group-hover:opacity-100" />
      </span>
      <span className="absolute bottom-1.5 left-1.5 flex size-5 items-center justify-center rounded-full bg-black/60 text-white">
        <Icon className="size-3" />
      </span>
    </button>
  )
}

export { PostCard }
