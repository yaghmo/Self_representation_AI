"use client"

import { useEffect, useLayoutEffect, useMemo, useState } from "react"
import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { BottomBar } from "@/components/fan/BottomBar"
import { ChatWidget } from "@/components/fan/ChatWidget"
import { SearchBar } from "@/components/fan/SearchBar"
import { mockProfile, mockPosts } from "@/components/fan/mockData"
import {
  getPublicPosts,
  getPublicProfile,
  publicBannerUrl,
  publicChatIconUrl,
  publicLandingPfpUrl,
  publicPfpUrl,
} from "@/lib/socialApi"
import { introAlreadySeen, isVideo, markIntroSeen } from "@/lib/introSplash"
import type { FanProfile, Post } from "@/components/fan/types"

export default function FanPage() {
  const [expanded, setExpanded] = useState(true)
  const [profile, setProfile] = useState<FanProfile>(mockProfile)
  const [posts, setPosts] = useState<Post[]>(mockPosts)
  const [searchQuery, setSearchQuery] = useState("")
  // Only ever flips true for a video pfp — an image pfp has nothing to
  // play, so the intro is skipped from the start (see the profile effect).
  const [introPlaying, setIntroPlaying] = useState(false)
  // Whether there's even a video intro to show is profile data — unknown
  // until getPublicProfile() resolves. Rendering the real page in that gap
  // means it flashes fully visible, then vanishes the instant introPlaying
  // flips true. "Already seen this hour" IS known synchronously though
  // (localStorage) — but not in the initializer here: that runs during SSR
  // too, where localStorage doesn't exist, so a repeat visitor within the
  // hour got `false` from the server and `true` from the client's first
  // render — a guaranteed hydration mismatch, not a flaky one. Starting
  // both at `false` keeps server and client's first render identical; the
  // layout effect below corrects it before the browser paints, so a repeat
  // visit still skips the wait with no visible flash.
  const [introDecided, setIntroDecided] = useState(false)

  useLayoutEffect(() => {
    if (introAlreadySeen()) setIntroDecided(true)
  }, [])

  const filteredPosts = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return posts
    const tag = query.startsWith("#") ? query : `#${query}`
    return posts.filter((post) => post.title?.toLowerCase().includes(tag))
  }, [posts, searchQuery])

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
        // Real data always wins, blank when the creator hasn't set one yet
        // — never falls back to mockData's placeholder name/bio, which
        // used to show fake content as if it were real.
        name: res.displayName ?? "",
        bio: res.bio ?? "",
        contactEmail: res.contactEmail,
        pfpUrl: res.pfpVersion != null ? publicPfpUrl(res.pfpVersion) : null,
        pfpMime: res.pfpMime,
        bannerUrl: res.bannerVersion != null ? publicBannerUrl(res.bannerVersion) : null,
        bannerMime: res.bannerMime,
        chatIconUrl: res.chatIconVersion != null ? publicChatIconUrl(res.chatIconVersion) : null,
        chatIconMime: res.chatIconMime,
        landingPfpUrl:
          res.landingPfpVersion != null ? publicLandingPfpUrl(res.landingPfpVersion) : null,
        landingPfpMime: res.landingPfpMime,
      })
      const introVideo = isVideo(res.landingPfpMime ?? res.pfpMime)
      if (introVideo && !introAlreadySeen()) {
        markIntroSeen()
        setIntroPlaying(true)
      }
      setIntroDecided(true)
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
      {introDecided && (
        <>
          {!introPlaying && (
            <SearchBar
              expanded={expanded}
              posts={posts}
              value={searchQuery}
              onChange={setSearchQuery}
            />
          )}
          <ProfileHeader
            profile={profile}
            expanded={expanded}
            introPlaying={introPlaying}
            onIntroEnded={() => setIntroPlaying(false)}
            onCollapse={() => setExpanded(false)}
          />
          {!introPlaying && (
            <>
              <PostGrid posts={filteredPosts} expanded={expanded} />
              <BottomBar />
              <ChatWidget
                botName={profile.name}
                chatIconUrl={profile.chatIconUrl}
                chatIconMime={profile.chatIconMime}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}
