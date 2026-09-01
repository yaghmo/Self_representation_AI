import { User } from "lucide-react";
import { platformIcon } from "@/lib/platformIcon";
import { formatCount } from "@/lib/formatCount";

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000";

export function SocialRow({
  platform,
  username,
  isAlt,
  followerCount,
  pfpUrl,
  bio,
  actions,
  proxyPfp = true,
  connected,
  onConnect,
  href,
}: {
  platform: string;
  username: string;
  isAlt: boolean;
  followerCount: number | null;
  pfpUrl: string | null;
  bio: string | null;
  actions?: React.ReactNode;
  // Several scraped CDNs (yt3.googleusercontent.com) 403/429 direct
  // hotlinking, so saved pfps route through /social/image_proxy — which
  // only serves already-saved URLs. The not-yet-saved preview row
  // (SocialDialog) passes false and renders the raw URL instead.
  proxyPfp?: boolean;
  // undefined = no OAuth concept for this platform (no dot, not "gray").
  // Pass true/false only for a platform with a real connect/disconnect flow.
  connected?: boolean;
  onConnect?: () => void;
  // Set only for the admin's saved-socials list, so the creator can open
  // their own link — the not-yet-saved preview row has nowhere to send it.
  href?: string;
}) {
  const Icon = platformIcon(platform);
  const imgSrc =
    pfpUrl && proxyPfp
      ? `${SERVICE_URL}/social/image_proxy?url=${encodeURIComponent(pfpUrl)}`
      : pfpUrl;
  const NameTag = href ? "a" : "span";
  return (
    <div className="border-b py-2 text-sm last:border-b-0">
      <div className="flex items-center gap-3">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        {imgSrc ? (
          // eslint-disable-next-line @next/next/no-img-element -- external, unknown-domain URLs the creator pastes in; next/image would need a wildcard remote pattern for arbitrary hosts
          <img
            src={imgSrc}
            alt=""
            // Google's avatar CDN (yt3.googleusercontent.com) 403s a
            // foreign-page Referer on an unproxied fetch — harmless to send
            // no-referrer to every other host too.
            referrerPolicy="no-referrer"
            className="size-8 shrink-0 rounded-full object-cover"
          />
        ) : (
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted">
            <User className="size-4 text-muted-foreground" />
          </div>
        )}
        <NameTag
          className={`font-medium ${href ? "hover:underline" : ""}`}
          {...(href ? { href, target: "_blank", rel: "noopener noreferrer" } : {})}
        >
          {username}
        </NameTag>
        <span className="text-xs text-muted-foreground capitalize">{platform}</span>
        {isAlt && <span className="text-xs text-muted-foreground">- Alt</span>}
        {followerCount != null && (
          <span className="text-xs text-muted-foreground">
            {formatCount(followerCount)} followers
          </span>
        )}
        {connected !== undefined &&
          (connected ? (
            <span className="flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              <span className="size-1.5 rounded-full bg-green-500" />
              Connected
            </span>
          ) : (
            <button
              type="button"
              onClick={onConnect}
              className="flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <span className="size-1.5 rounded-full bg-muted-foreground" />
              Connect
            </button>
          ))}
        {actions && <div className="ml-auto flex gap-1">{actions}</div>}
      </div>
      {bio && <p className="mt-1 pl-7 text-xs text-muted-foreground">{bio}</p>}
    </div>
  );
}
