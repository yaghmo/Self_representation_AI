import type { Post } from "./types"

const SKELETON_COUNT = 6

function PostGrid({ posts, expanded }: { posts: Post[]; expanded: boolean }) {
  const style = {
    opacity: expanded ? 0 : 1,
    transform: expanded ? "translateY(12px)" : "translateY(0)",
  }
  const className =
    "mx-6 mt-8 grid grid-cols-3 gap-1 transition-[opacity,transform] duration-500 ease-out sm:mx-10 sm:gap-2"

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
    <div className={className} style={style}>
      {posts.map((post) => (
        <div
          key={post.id}
          className="aspect-[3/4] overflow-hidden rounded-md bg-muted"
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
