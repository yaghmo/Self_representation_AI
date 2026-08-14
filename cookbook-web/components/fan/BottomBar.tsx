import { Link2, Plus } from "lucide-react"

function BottomBar() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex items-center justify-center gap-6 border-t border-border bg-background/95 py-3 backdrop-blur">
      <span
        aria-disabled="true"
        className="flex size-9 items-center justify-center rounded-full text-muted-foreground/50"
      >
        <Link2 className="size-5" />
      </span>
      <span
        aria-disabled="true"
        className="flex size-9 items-center justify-center rounded-full text-muted-foreground/50"
      >
        <Link2 className="size-5" />
      </span>
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
