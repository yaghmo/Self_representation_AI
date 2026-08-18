"use client"

import { useEffect, useState } from "react"
import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { BottomBar } from "@/components/fan/BottomBar"
import { ChatWidget } from "@/components/fan/ChatWidget"
import { SearchBar } from "@/components/fan/SearchBar"
import { mockProfile, mockPosts } from "@/components/fan/mockData"
import { getPublicPosts, getPublicProfile, publicBannerUrl, publicPfpUrl } from "@/lib/socialApi"
import type { FanProfile, Post } from "@/components/fan/types"

export default function FanPage() {
  const [expanded, setExpanded] = useState(true)
  const [profile, setProfile] = useState<FanProfile>(mockProfile)
  const [posts, setPosts] = useState<Post[]>(mockPosts)

  useEffect(() => {
    // Browsers restore scroll position on reload by default, which fires
    // before hydration and would silently flip `expanded` to false via the
    // scroll listener below — always land on the expanded header instead.
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual"
    }
    window.scrollTo(0, 0)
  }, [])

  useEffect(() => {
    getPublicProfile().then((res) => {
      setProfile({
        name: mockProfile.name,
        bio: res.bio ?? mockProfile.bio,
        pfpUrl: res.pfpVersion != null ? publicPfpUrl(res.pfpVersion) : null,
        bannerUrl: res.bannerVersion != null ? publicBannerUrl(res.bannerVersion) : null,
      })
    })
    getPublicPosts().then(setPosts)
  }, [])

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
        profile={profile}
        expanded={expanded}
        onCollapse={() => setExpanded(false)}
      />
      <PostGrid posts={posts} expanded={expanded} />
      <BottomBar />
      <ChatWidget botName={mockProfile.name} />
    </div>
  )
}
