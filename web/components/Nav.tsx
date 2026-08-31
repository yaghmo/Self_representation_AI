"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

// Admin link is unconditional — a future deployment-gating pass (config/stack.json's agent flag)
// needs to update this list too, not just gate the route.
const LINKS = [
  { href: "/", label: "Cookbook" },
  { href: "/feed", label: "Feed" },
  { href: "/fan", label: "Fan" },
  { href: "/admin", label: "Admin" },
] as const

function Nav() {
  const pathname = usePathname()

  return (
    <nav className="flex items-center gap-4 border-b border-border bg-card px-4 py-2 text-sm">
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            "font-medium transition-colors hover:text-foreground",
            pathname === link.href
              ? "text-foreground"
              : "text-muted-foreground"
          )}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  )
}

export { Nav }
