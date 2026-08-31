"use client"

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { PostPlayer } from "./PostPlayer"
import type { Post } from "./types"

function PostModal({ post, onClose }: { post: Post; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogTitle className="sr-only">{post.title ?? `${post.platform} post`}</DialogTitle>
        <div className="aspect-[3/4] w-full bg-black">
          <PostPlayer post={post} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

export { PostModal }
