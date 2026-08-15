"use client"

import { useEffect, useState } from "react"
import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { BottomBar } from "@/components/fan/BottomBar"
import { ChatWidget } from "@/components/fan/ChatWidget"
import { SearchBar } from "@/components/fan/SearchBar"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (!expanded) return
    function handleScroll() {
      if (window.scrollY > 4) setExpanded(false)
    }
    window.addEventListener("scroll", handleScroll, { passive: true })
    return () => window.removeEventListener("scroll", handleScroll)
  }, [expanded])

  return (
    <div className="min-h-[calc(100vh-2.5rem)] pb-24">
      <SearchBar expanded={expanded} />
      <ProfileHeader
        profile={mockProfile}
        expanded={expanded}
        onCollapse={() => setExpanded(false)}
      />
      <PostGrid posts={mockPosts} expanded={expanded} />
      <BottomBar />
      <ChatWidget botName={mockProfile.name} />
    </div>
  )
}
