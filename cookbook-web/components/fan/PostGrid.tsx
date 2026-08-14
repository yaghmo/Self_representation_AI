import type { Post } from "./types"

function PostGrid({ posts }: { posts: Post[] }) {
  if (posts.length === 0) {
    return (
      <div className="mx-4 mt-8 rounded-2xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground sm:mx-6">
        No posts yet.
      </div>
    )
  }

  return (
    <div className="mx-4 mt-8 grid grid-cols-3 gap-1 sm:mx-6 sm:gap-2">
      {posts.map((post) => (
        <div
          key={post.id}
          className="aspect-square overflow-hidden rounded-md bg-muted"
        >
          <img
            src={post.imageUrl}
            alt={post.caption}
            className="size-full object-cover"
          />
        </div>
      ))}
    </div>
  )
}

export { PostGrid }
