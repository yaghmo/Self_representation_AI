import { Crown, Link2 } from "lucide-react"
import {
  SiDiscord,
  SiInstagram,
  SiTelegram,
  SiTiktok,
  SiTwitch,
  SiX,
  SiYoutube,
} from "@icons-pack/react-simple-icons"

// Real brand marks via @icons-pack/react-simple-icons. Throne isn't in that
// pack (too niche to have a simple-icons entry) — its actual mark is three
// points forming a crown, so a crown icon is the closest stand-in without
// inventing a fake logo. "other" (an unrecognized/custom platform) falls
// back to the plain link icon.

type IconProps = { className?: string }

function brandIcon(Si: typeof SiInstagram) {
  function BrandIcon({ className }: IconProps) {
    return <Si className={className} color="currentColor" />
  }
  return BrandIcon
}

function ThroneIcon({ className }: IconProps) {
  return <Crown className={className} />
}

const PLATFORM_ICONS: Record<string, (props: IconProps) => React.JSX.Element> = {
  instagram: brandIcon(SiInstagram),
  tiktok: brandIcon(SiTiktok),
  x: brandIcon(SiX),
  youtube: brandIcon(SiYoutube),
  twitch: brandIcon(SiTwitch),
  telegram: brandIcon(SiTelegram),
  throne: ThroneIcon,
  discord: brandIcon(SiDiscord),
}

export function platformIcon(platform: string) {
  return PLATFORM_ICONS[platform] ?? Link2
}
