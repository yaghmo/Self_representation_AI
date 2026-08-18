"use client"

import { useState } from "react"
import type { Post } from "./types"
import { PostCard } from "./PostCard"
import { PostModal } from "./PostModal"

const SKELETON_COUNT = 6

function PostGrid({ posts, expanded }: { posts: Post[]; expanded: boolean }) {
  const [openPost, setOpenPost] = useState<Post | null>(null)
  const style = {
    opacity: expanded ? 0 : 1,
    transform: expanded ? "translateY(12px)" : "translateY(0)",
  }
  const className =
    "mx-12 mt-8 grid grid-cols-4 gap-3 transition-[opacity,transform] duration-500 ease-out sm:mx-20 sm:gap-4"

  if (posts.length === 0) {
    return (
      <div className={className} style={style}>
        {Array.from({ length: SKELETON_COUNT }).map((_, index) => (
          <div
            key={index}
            className="aspect-[3/4] animate-pulse rounded-md bg-muted"
          />
        ))}
      </div>
    )
  }

  return (
    <>
      <div className={className} style={style}>
        {posts.map((post) => (
          <PostCard key={post.id} post={post} onOpen={setOpenPost} />
        ))}
      </div>
      {openPost && <PostModal post={openPost} onClose={() => setOpenPost(null)} />}
    </>
  )
}

export { PostGrid }
