"use client"

import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <p>{mockProfile.name}</p>
      <p>{mockPosts.length} posts</p>
    </div>
  )
}
