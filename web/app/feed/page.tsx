"use client"

import { useEffect, useState } from "react"
import { CreatorCard } from "@/components/feed/CreatorCard"
import { mockProfile, mockPosts } from "@/components/fan/mockData"
import { getPublicPosts, getPublicProfile, publicPfpUrl, publicBannerUrl } from "@/lib/socialApi"
import type { FanProfile, Post } from "@/components/fan/types"

export default function FeedPage() {
  const [profile, setProfile] = useState<FanProfile>(mockProfile)
  const [posts, setPosts] = useState<Post[]>(mockPosts)

  useEffect(() => {
    getPublicProfile().then((res) => {
      setProfile({
        name: res.displayName ?? mockProfile.name,
        bio: res.bio ?? mockProfile.bio,
        pfpUrl: res.pfpVersion != null ? publicPfpUrl(res.pfpVersion) : null,
        pfpMime: res.pfpMime,
        bannerUrl: res.bannerVersion != null ? publicBannerUrl(res.bannerVersion) : null,
      })
    })
    getPublicPosts().then(setPosts)
  }, [])

  return (
    <div className="min-h-[calc(100vh-2.5rem)] px-4 py-8 sm:px-8">
      <h1 className="text-xl font-semibold">Discover creators</h1>
      <div className="mt-4 flex gap-4 overflow-x-auto pb-2">
        <CreatorCard profile={profile} posts={posts} />
      </div>
    </div>
  )
}
