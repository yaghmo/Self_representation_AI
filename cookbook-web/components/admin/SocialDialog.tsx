"use client";

import { useEffect, useRef, useState } from "react";
import {
  addSocial,
  deleteSocial,
  getSocials,
  previewSocial,
  updateSocial,
  type Social,
} from "@/lib/admin/socialApi";
import { parseSocialUrl } from "@/lib/admin/socialUrl";
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
import { platformIcon } from "@/lib/platformIcon";
import { BioSection } from "@/components/admin/BioSection";
import { Pencil, Trash2, User } from "lucide-react";

const COMMON_PLATFORMS = ["instagram", "tiktok", "x", "youtube", "linkedin"];

function SocialRow({
  platform,
  username,
  isAlt,
  followerCount,
  pfpUrl,
  bio,
  actions,
}: {
  platform: string;
  username: string;
  isAlt: boolean;
  followerCount: number | null;
  pfpUrl: string | null;
  bio: string | null;
  actions: React.ReactNode;
}) {
  const Icon = platformIcon(platform);
  return (
    <div className="border-b py-2 text-sm last:border-b-0">
      <div className="flex items-center gap-3">
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        {pfpUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- external, unknown-domain URLs the creator pastes in; next/image would need a wildcard remote pattern for arbitrary hosts
          <img src={pfpUrl} alt="" className="size-8 shrink-0 rounded-full object-cover" />
        ) : (
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted">
            <User className="size-4 text-muted-foreground" />
          </div>
        )}
        <span className="font-medium">{username}</span>
        {isAlt && <span className="text-xs text-muted-foreground">-Alt</span>}
        {followerCount != null && (
          <span className="text-xs text-muted-foreground">{followerCount} followers</span>
        )}
        <div className="ml-auto flex gap-1">{actions}</div>
      </div>
      <p className="mt-1 pl-7 text-xs text-muted-foreground">{bio || "no bio yet."}</p>
    </div>
  );
}

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
  const [bio, setBio] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });

  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRequestRef = useRef(0);

  useEffect(() => {
    const parsed = parseSocialUrl(form.url);
    if (!parsed) {
      setPreviewLoading(false);
      return;
    }
    const requestId = ++previewRequestRef.current;
    const url = form.url;
    const id = form.id;
    setPreviewLoading(true);
    const timer = setTimeout(() => {
      previewSocial({ url, id })
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
        })
        .catch(() => {
          // best-effort — a failed preview call just means no scraped data,
          // the local parseSocialUrl-derived preview still shows
        })
        .finally(() => {
          if (previewRequestRef.current === requestId) setPreviewLoading(false);
        });
    }, 400);
    return () => clearTimeout(timer);
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
      setBio(res.bio);
      setError(null);
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
    // Pointing the form at a different platform (or starting a brand-new
    // add) means any previously scraped pfp/follower count/bio belongs to
    // the old target — carrying it over via the preview merge's `?? prev.X`
    // fallback would save it under the new social. Only same-target edits
    // (tweaking an existing social's own URL, same platform) keep them,
    // since that fallback exists precisely to survive the in-flight debounce
    // there.
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
  }

  async function handleSave() {
    const platform =
      form.platform === "other" ? form.platformOther.trim() : form.platform;
    if (!platform || !form.username || !form.url) {
      setError(
        form.id
          ? "platform, username, and url are required"
          : "paste a link from a supported platform (instagram, tiktok, x, youtube, linkedin)"
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
    try {
      if (form.id) {
        await updateSocial({ id: form.id, ...params });
      } else {
        await addSocial(params);
      }
      setForm({ ...EMPTY_FORM });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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

  const preview = parseSocialUrl(form.url);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Profile</DialogTitle>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-3">
          <p className="text-sm font-medium">{form.id ? "Update social" : "Add social"}</p>
          <div className="space-y-1">
            <Label>Link</Label>
            <Input value={form.url} onChange={(e) => handleUrlChange(e.target.value)} />
          </div>
          {preview && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                {previewLoading ? "This is how it will show (scraping…):" : "This is how it will show:"}
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
                />
              </div>
            </div>
          )}
          <div className="flex gap-2">
            <Button onClick={handleSave}>Confirm</Button>
            <Button variant="outline" onClick={() => setForm({ ...EMPTY_FORM })}>
              Cancel
            </Button>
          </div>
        </div>

        <Separator />

        <BioSection bio={bio} onSaved={refresh} />

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

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
