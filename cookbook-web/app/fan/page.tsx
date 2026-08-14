"use client"

import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <ProfileHeader profile={mockProfile} />
      <PostGrid posts={mockPosts} />
    </div>
  )
}
