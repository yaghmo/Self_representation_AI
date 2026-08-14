import type { FanProfile } from "./types"

function ProfileHeader({ profile }: { profile: FanProfile }) {
  return (
    <header className="relative">
      <div className="h-40 w-full bg-gradient-to-r from-primary/40 via-accent to-primary/20 sm:h-56" />
      <div className="relative -mt-12 flex flex-col items-start gap-3 px-4 sm:-mt-16 sm:px-6">
        <div className="size-24 shrink-0 rounded-full border-4 border-background bg-muted sm:size-32" />
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">{profile.name}</h1>
          <p className="mt-1 max-w-prose text-sm text-muted-foreground sm:text-base">
            {profile.bio}
          </p>
        </div>
      </div>
    </header>
  )
}

export { ProfileHeader }
