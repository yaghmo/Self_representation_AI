"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
import { platformIcon } from "@/lib/platformIcon"
import { PostModal } from "@/components/fan/PostModal"
import { PlayOnceVideo } from "@/components/media/PlayOnceVideo"
import type { FanProfile, Post } from "@/components/fan/types"

function isVideo(mime: string | null | undefined) {
  return !!mime?.startsWith("video/")
}

const MAX_THUMBS = 3

function CreatorCard({ profile, posts }: { profile: FanProfile; posts: Post[] }) {
  const router = useRouter()
  const [openPost, setOpenPost] = useState<Post | null>(null)

  return (
    <>
      <button
        type="button"
        onClick={() => router.push("/fan")}
        className="flex w-64 shrink-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:bg-accent"
      >
        <div className="flex items-center gap-3">
          <div className="size-12 shrink-0 overflow-hidden rounded-full bg-muted">
            {profile.pfpUrl && (
              isVideo(profile.pfpMime) ? (
                <PlayOnceVideo src={profile.pfpUrl} className="size-full object-cover" />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element -- served from our own service, not a next/image remote host
                <img src={profile.pfpUrl} alt="" className="size-full object-cover" />
              )
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium">{profile.name}</p>
            <p className="truncate text-xs text-muted-foreground">{profile.bio}</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {posts.slice(0, MAX_THUMBS).map((post) => {
            const Icon = platformIcon(post.platform)
            return (
              <div
                key={post.id}
                role="button"
                tabIndex={0}
                onClick={(event) => {
                  event.stopPropagation()
                  setOpenPost(post)
                }}
                className="relative aspect-[3/4] overflow-hidden rounded-md bg-muted"
              >
                {post.thumbnailUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element -- third-party platform thumbnail, not a next/image remote host
                  <img src={post.thumbnailUrl} alt="" className="size-full object-cover" />
                ) : (
                  <div className="flex size-full items-center justify-center">
                    <Icon className="size-4 text-muted-foreground" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </button>
      {openPost && <PostModal post={openPost} onClose={() => setOpenPost(null)} />}
    </>
  )
}

export { CreatorCard }
