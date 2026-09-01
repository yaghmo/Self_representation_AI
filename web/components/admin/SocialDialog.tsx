"use client";

import { useEffect, useRef, useState } from "react";
import {
  addSocial,
  deleteSocial,
  getSocials,
  previewSocial,
  refreshPosts,
  saveContactEmail,
  SocialApiError,
  tiktokDisconnect,
  tiktokLoginUrl,
  tiktokStatus,
  updateSocial,
  type Social,
  type SocialMention,
  type TiktokStatus,
} from "@/lib/admin/socialApi";
import { buildSocialUrl, parseSocialUrl } from "@/lib/admin/socialUrl";
import { platformIcon } from "@/lib/platformIcon";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { BioSection } from "@/components/admin/BioSection";
import { DisplayNameSection } from "@/components/admin/DisplayNameSection";
import { ProfileImages } from "@/components/admin/ProfileImages";
import { SocialRow } from "@/components/SocialRow";
import { formatCount } from "@/lib/formatCount";
import { CheckCircle2, CircleHelp, Loader2, Mail, Pencil, Search, Trash2, X } from "lucide-react";

// Preview also verifies each mention's profile exists server-side, on top
// of the primary link's scrape — needs more time than one scrape alone.
const SCRAPE_TIMEOUT_MS = 20_000;

const COMMON_PLATFORMS = [
  "instagram",
  "tiktok",
  "x",
  "youtube",
  "twitch",
  "telegram",
  "throne",
  "discord",
];

type FormState = {
  id?: string;
  platform: string;
  platformOther: string;
  username: string;
  url: string;
  bio: string;
  followerCount: string;
  pfpUrl: string;
  isAlt: boolean;
};

const EMPTY_FORM: FormState = {
  platform: "instagram",
  platformOther: "",
  username: "",
  url: "",
  bio: "",
  followerCount: "",
  pfpUrl: "",
  isAlt: false,
};

export function SocialDialog({ onClose }: { onClose: () => void }) {
  const [socials, setSocials] = useState<Social[]>([]);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [bio, setBio] = useState<string | null>(null);
  const [contactEmail, setContactEmail] = useState<string | null>(null);
  const [pfpVersion, setPfpVersion] = useState<number | null>(null);
  const [bannerVersion, setBannerVersion] = useState<number | null>(null);
  const [chatIconVersion, setChatIconVersion] = useState<number | null>(null);
  const [landingPfpVersion, setLandingPfpVersion] = useState<number | null>(null);
  const [pfpMime, setPfpMime] = useState<string | null>(null);
  const [bannerMime, setBannerMime] = useState<string | null>(null);
  const [chatIconMime, setChatIconMime] = useState<string | null>(null);
  const [landingPfpMime, setLandingPfpMime] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });

  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRequestRef = useRef(0);
  const [mentions, setMentions] = useState<SocialMention[]>([]);
  const [saving, setSaving] = useState(false);

  const [editingEmail, setEditingEmail] = useState(false);
  const [emailDraft, setEmailDraft] = useState("");

  const [refreshingPosts, setRefreshingPosts] = useState(false);
  const [postsStatus, setPostsStatus] = useState<string | null>(null);

  const [tiktok, setTiktok] = useState<TiktokStatus | null>(null);
  const [tiktokBusy, setTiktokBusy] = useState(false);

  async function handleTiktokLogin() {
    setTiktokBusy(true);
    try {
      const { authorizeUrl } = await tiktokLoginUrl();
      window.location.href = authorizeUrl;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setTiktokBusy(false);
    }
  }

  async function handleTiktokDisconnect() {
    setTiktokBusy(true);
    try {
      await tiktokDisconnect();
      setTiktok({ connected: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTiktokBusy(false);
    }
  }

  async function handleRefreshPosts() {
    setRefreshingPosts(true);
    setPostsStatus(null);
    try {
      const res = await refreshPosts();
      setPostsStatus(`Refreshed — ${res.posts.length} post${res.posts.length === 1 ? "" : "s"}`);
    } catch (e) {
      setPostsStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshingPosts(false);
    }
  }

  useEffect(() => {
    const parsed = parseSocialUrl(form.url);
    if (!parsed) {
      setPreviewLoading(false);
      setMentions([]);
      return;
    }
    const requestId = ++previewRequestRef.current;
    const url = form.url;
    const id = form.id;
    setPreviewLoading(true);
    const controller = new AbortController();
    const timer = setTimeout(() => {
      // Some scrapers (yt-dlp in particular) can hang well past what a
      // paste-and-wait UI should tolerate — give up and let the local
      // parseSocialUrl-derived preview stand instead of blocking Confirm forever.
      const scrapeTimeout = setTimeout(() => controller.abort(), SCRAPE_TIMEOUT_MS);
      previewSocial({ url, id }, controller.signal)
        .then((data) => {
          if (previewRequestRef.current !== requestId) return; // superseded by a newer edit
          setForm((prev) =>
            prev.url === url
              ? {
                  ...prev,
                  followerCount:
                    data.followerCount != null ? String(data.followerCount) : prev.followerCount,
                  pfpUrl: data.pfpUrl ?? prev.pfpUrl,
                  bio: data.bio ?? prev.bio,
                  isAlt: data.isAlt,
                }
              : prev
          );
          setMentions(data.mentions);
        })
        .catch(() => {
          // best-effort — a failed or timed-out preview call just means no
          // scraped data, the local parseSocialUrl-derived preview still shows
        })
        .finally(() => {
          clearTimeout(scrapeTimeout);
          if (previewRequestRef.current === requestId) setPreviewLoading(false);
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.url, form.id]);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const res = await getSocials();
      setSocials(res.socials);
      setDisplayName(res.displayName);
      setBio(res.bio);
      setContactEmail(res.contactEmail);
      setPfpVersion(res.pfpVersion);
      setBannerVersion(res.bannerVersion);
      setChatIconVersion(res.chatIconVersion);
      setLandingPfpVersion(res.landingPfpVersion);
      setPfpMime(res.pfpMime);
      setBannerMime(res.bannerMime);
      setChatIconMime(res.chatIconMime);
      setLandingPfpMime(res.landingPfpMime);
      setError(null);
      tiktokStatus().then(setTiktok).catch(() => setTiktok({ connected: false }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function startEdit(social: Social) {
    const known = COMMON_PLATFORMS.includes(social.platform);
    setForm({
      id: social.id,
      platform: known ? social.platform : "other",
      platformOther: known ? "" : social.platform,
      username: social.username,
      url: social.url,
      bio: social.bio ?? "",
      followerCount:
        social.followerCount != null ? String(social.followerCount) : "",
      pfpUrl: social.pfpUrl ?? "",
      isAlt: social.isAlt,
    });
  }

  function handleUrlChange(url: string) {
    const parsed = parseSocialUrl(url);
    if (!parsed) {
      setForm({ ...form, url });
      return;
    }
    const known = COMMON_PLATFORMS.includes(parsed.platform);
    // Switching target platform means old scraped pfp/follower count/bio
    // belongs to the old target — clear it rather than let the preview
    // merge's `?? prev.X` fallback carry it over to the new social.
    const currentPlatform = form.platform === "other" ? form.platformOther : form.platform;
    const switchingTarget = !form.id || parsed.platform !== currentPlatform;
    setForm({
      ...form,
      url,
      platform: known ? parsed.platform : "other",
      platformOther: known ? "" : parsed.platform,
      // No separate username input exists — it's always derived from the
      // URL, so there's nothing to preserve by falling back to form.username.
      username: parsed.username,
      ...(switchingTarget ? { pfpUrl: "", followerCount: "", bio: "" } : {}),
    });
    if (switchingTarget) setMentions([]);
  }

  async function handleSave() {
    const platform =
      form.platform === "other" ? form.platformOther.trim() : form.platform;
    if (!platform || !form.username || !form.url) {
      setError(
        form.id
          ? "platform, username, and url are required"
          : "paste a link from a supported platform (instagram, tiktok, x, youtube, twitch, telegram, throne, discord)"
      );
      return;
    }
    const params = {
      platform,
      username: form.username,
      url: form.url,
      bio: form.bio || undefined,
      followerCount: form.followerCount ? Number(form.followerCount) : undefined,
      pfpUrl: form.pfpUrl || undefined,
      isAlt: form.isAlt,
    };
    setSaving(true);
    try {
      // A Linktree link isn't a social profile — it's just a list of the
      // creator's other links. Only the mentions extracted from it get
      // stored; the Linktree link itself never becomes a social row.
      if (platform !== "linktree") {
        if (form.id) {
          await updateSocial({ id: form.id, ...params });
        } else {
          try {
            await addSocial(params);
          } catch (e) {
            // Re-pasting an already-linked profile's own URL (to pick up
            // newly discovered mentions) isn't a failure — only bail out
            // for anything that isn't that specific conflict.
            if (!(e instanceof SocialApiError && e.status === 409)) throw e;
          }
        }
      }
      // Whatever's still in `mentions` at this point is exactly what the
      // creator chose to keep — anything they didn't want was already
      // removed via its own discard button. Add/save those alongside the
      // primary link so one Confirm covers the whole batch.
      const platformMentions = mentions.filter(
        (m): m is SocialMention & { type: "platform"; platform: string } =>
          m.type === "platform" && !!m.platform
      );
      const emailMentions = mentions.filter((m) => m.type === "email");
      const results = await Promise.allSettled([
        ...platformMentions.map(async (m) => {
          const url = buildSocialUrl(m.platform, m.value);
          if (!url) throw new Error(`no canonical URL for ${m.platform}`);
          // Scrape pfp/follower count/bio the same way a manually pasted
          // link does, instead of adding a bare platform+username row.
          const scraped = await previewSocial({ url }).catch(() => null);
          // An empty scrape (no pfp/bio/follower count) means the profile
          // doesn't exist on the platform — most often a dead/renamed
          // account behind a mention pulled off a Linktree page. Don't add
          // a link that would just 404 for fans.
          const hasData =
            scraped && (scraped.pfpUrl || scraped.bio || scraped.followerCount != null);
          if (!hasData) return;
          await addSocial({
            platform: m.platform,
            username: m.value,
            url,
            bio: scraped.bio ?? undefined,
            followerCount: scraped.followerCount ?? undefined,
            pfpUrl: scraped.pfpUrl ?? undefined,
            isAlt: scraped.isAlt,
          });
        }),
        // Contact email is a single field, not a list — last kept
        // suggestion wins if more than one somehow survived to Confirm.
        ...(emailMentions.length > 0
          ? [saveContactEmail(emailMentions[emailMentions.length - 1].value)]
          : []),
      ]);
      const failures = results.filter((r) => r.status === "rejected").length;
      setForm({ ...EMPTY_FORM });
      setMentions([]);
      setError(
        failures > 0 ? `${failures} suggestion(s) failed to save — try them individually` : null
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this social?")) return;
    try {
      await deleteSocial(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleDiscardMention(mention: SocialMention) {
    setMentions((prev) => prev.filter((m) => m !== mention));
  }

  async function handleSaveEmail() {
    const email = emailDraft.trim();
    if (!email) return;
    try {
      await saveContactEmail(email);
      setEditingEmail(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteEmail() {
    if (!confirm("Delete contact email?")) return;
    try {
      await saveContactEmail(null);
      setEditingEmail(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const preview = parseSocialUrl(form.url);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-[836px] sm:max-w-[836px] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Profile</DialogTitle>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <ProfileImages
          pfpVersion={pfpVersion}
          bannerVersion={bannerVersion}
          chatIconVersion={chatIconVersion}
          landingPfpVersion={landingPfpVersion}
          pfpMime={pfpMime}
          bannerMime={bannerMime}
          chatIconMime={chatIconMime}
          landingPfpMime={landingPfpMime}
          bio={bio}
          onSaved={refresh}
        />

        <Separator />

        <DisplayNameSection displayName={displayName} onSaved={refresh} />

        <BioSection bio={bio} onSaved={refresh} />

        <div className="space-y-2">
          <p className="text-sm font-medium">Contact</p>
          {editingEmail ? (
            <div className="flex items-center gap-2">
              <Mail className="size-3.5 shrink-0 text-muted-foreground" />
              <Input
                value={emailDraft}
                onChange={(e) => setEmailDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSaveEmail()}
                placeholder="business@example.com"
                className="h-7 text-xs"
                autoFocus
              />
              <Button size="sm" className="h-7 px-2" onClick={handleSaveEmail}>
                Save
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={() => setEditingEmail(false)}
              >
                Cancel
              </Button>
              {contactEmail && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Delete contact email"
                  title="Delete contact email"
                  onClick={handleDeleteEmail}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
          ) : contactEmail ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Mail className="size-3.5 shrink-0" />
              {contactEmail}
              <Button
                variant="ghost"
                size="icon"
                className="size-5"
                aria-label="Update contact email"
                title="Update contact email"
                onClick={() => {
                  setEmailDraft(contactEmail);
                  setEditingEmail(true);
                }}
              >
                <Pencil className="size-3" />
              </Button>
            </p>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">no contact info yet.</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEmailDraft("");
                  setEditingEmail(true);
                }}
              >
                Add contact info
              </Button>
            </>
          )}
        </div>

        <Separator />

        <div className="space-y-3">
          <p className="text-sm font-medium">{form.id ? "Update social" : "Add social"}</p>
          <div className="space-y-1">
            <Label>Link</Label>
            <Input value={form.url} onChange={(e) => handleUrlChange(e.target.value)} />
            <p className="text-xs text-muted-foreground">
              Paste a link and it&apos;ll auto-gather the profile pic, follower count, bio, and
              any other socials mentioned there — give it a few seconds.
            </p>
          </div>
          {preview && preview.platform !== "linktree" && (
            <div className="space-y-1">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {previewLoading && <Loader2 className="size-3 shrink-0 animate-spin" />}
                {previewLoading ? "Scraping…" : "This is how it will show:"}
              </p>
              <div className="rounded-lg border px-2">
                <SocialRow
                  platform={preview.platform}
                  username={form.username || preview.username}
                  isAlt={form.isAlt}
                  followerCount={form.followerCount ? Number(form.followerCount) : null}
                  pfpUrl={form.pfpUrl || null}
                  bio={form.bio}
                  actions={null}
                  // Editing an existing social's pfpUrl is already saved
                  // and known to the proxy; a brand-new add's freshly
                  // scraped pfpUrl isn't saved yet, so the proxy would 404 it.
                  proxyPfp={!!form.id}
                />
              </div>
            </div>
          )}
          {mentions.length > 0 && (
            <div className="space-y-1 rounded-lg border p-2">
              <p className="text-xs font-medium text-muted-foreground">
                {preview?.platform === "linktree"
                  ? "Found on this page — saved with Confirm below, unless removed here"
                  : "Found in bio — saved with Confirm below, unless removed here"}
              </p>
              {mentions.map((mention, i) => {
                const Icon =
                  mention.type === "email" ? Mail : platformIcon(mention.platform ?? "");
                return (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    {mention.pfpUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element -- unsaved candidate, not yet proxy-servable
                      <img
                        src={mention.pfpUrl}
                        alt=""
                        className="size-5 shrink-0 rounded-full object-cover"
                      />
                    ) : (
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className={mention.type === "email" ? "text-muted-foreground" : undefined}>
                      {mention.value}
                    </span>
                    {mention.type === "platform" && (
                      <span className="text-xs text-muted-foreground capitalize">
                        {mention.platform}
                      </span>
                    )}
                    {mention.followerCount != null && (
                      <span className="text-xs text-muted-foreground">
                        {formatCount(mention.followerCount)} followers
                      </span>
                    )}
                    {mention.confidence === "confirmed" ? (
                      <CheckCircle2
                        className="size-3.5 shrink-0 text-green-600"
                        aria-label="Confirmed — this account mentions the primary one back"
                      >
                        <title>Confirmed — this account mentions the primary one back</title>
                      </CheckCircle2>
                    ) : (
                      <>
                        {/* "likely" (exists, but no mutual back-reference) gets the
                            same badge as "unverified" — a guessed handle can land
                            on a real, unrelated account, so existing-but-uncorroborated
                            is no more trustworthy than not-found. */}
                        <CircleHelp
                          className="size-3.5 shrink-0 text-muted-foreground"
                          aria-label="Couldn't confirm this is the right account"
                        >
                          <title>Couldn't confirm this is the right account</title>
                        </CircleHelp>
                        <a
                          href={`https://www.google.com/search?q=${encodeURIComponent(
                            `${mention.value} ${mention.platform ?? ""}`.trim()
                          )}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label="Search for this account"
                          title="Search for this account"
                          className="text-muted-foreground hover:text-foreground"
                        >
                          <Search className="size-3.5 shrink-0" />
                        </a>
                      </>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="ml-auto size-6"
                      aria-label="Discard"
                      title="Discard"
                      onClick={() => handleDiscardMention(mention)}
                    >
                      <X className="size-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex gap-2">
            <Button onClick={handleSave} disabled={previewLoading || saving}>
              {(previewLoading || saving) && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
              {saving ? "Saving…" : "Confirm"}
            </Button>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => {
                setForm({ ...EMPTY_FORM });
                setMentions([]);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>

        <Separator />

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : socials.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No profile linked to this account yet
          </p>
        ) : (
          <div className="space-y-1">
            {socials.map((social) => (
              <SocialRow
                key={social.id}
                platform={social.platform}
                username={social.username}
                isAlt={social.isAlt}
                followerCount={social.followerCount}
                pfpUrl={social.pfpUrl}
                bio={social.bio}
                href={social.url}
                connected={social.platform === "tiktok" ? tiktok?.connected ?? false : undefined}
                onConnect={handleTiktokLogin}
                actions={
                  <>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Update"
                      title="Update"
                      onClick={() => startEdit(social)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Delete"
                      title="Delete"
                      onClick={() => handleDelete(social.id)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </>
                }
              />
            ))}
          </div>
        )}

        <Separator />

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshPosts}
            disabled={refreshingPosts}
          >
            {refreshingPosts && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
            Refresh posts
          </Button>
          <p className="text-xs text-muted-foreground">
            {postsStatus ?? "Pulls recent videos/VODs from linked YouTube, Twitch, TikTok"}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {tiktok?.connected ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleTiktokDisconnect}
                disabled={tiktokBusy}
              >
                {tiktokBusy && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                Disconnect TikTok
              </Button>
              {(() => {
                const linkedTiktok = socials.find((s) => s.platform === "tiktok");
                const linked = linkedTiktok?.username?.replace(/^@/, "");
                const connected = tiktok.username;
                const matches =
                  !!linked && !!connected && linked.toLowerCase() === connected.toLowerCase();
                return matches ? (
                  <p className="text-xs text-muted-foreground">
                    Connected as @{connected} — video listing uses the real TikTok API
                  </p>
                ) : (
                  <p className="text-xs text-amber-600">
                    Connected as @{connected ?? "unknown"}, but the linked profile is @
                    {linked ?? "?"} — listing still falls back to scraping until these match
                  </p>
                );
              })()}
            </>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleTiktokLogin}
                disabled={tiktokBusy}
              >
                {tiktokBusy && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                Connect TikTok
              </Button>
              <p className="text-xs text-muted-foreground">
                Optional — makes TikTok post listing reliable instead of scraped
              </p>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
