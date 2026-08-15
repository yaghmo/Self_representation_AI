"use client";

import { useEffect, useState } from "react";
import {
  addSocial,
  deleteSocial,
  getSocials,
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
import { Pencil, Trash2, User } from "lucide-react";

const COMMON_PLATFORMS = ["instagram", "tiktok", "x", "youtube", "linkedin"];

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const res = await getSocials();
      setSocials(res.socials);
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
    setForm({
      ...form,
      url,
      platform: known ? parsed.platform : "other",
      platformOther: known ? "" : parsed.platform,
      username: form.username || parsed.username,
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
          <div className="flex gap-2">
            <Button onClick={handleSave}>Save</Button>
            {form.id && (
              <Button variant="outline" onClick={() => setForm({ ...EMPTY_FORM })}>
                Cancel
              </Button>
            )}
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
            {socials.map((social) => {
              const Icon = platformIcon(social.platform);
              return (
                <div key={social.id} className="border-b py-2 text-sm last:border-b-0">
                  <div className="flex items-center gap-3">
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                    {social.pfpUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element -- external, unknown-domain URLs the creator pastes in; next/image would need a wildcard remote pattern for arbitrary hosts
                      <img
                        src={social.pfpUrl}
                        alt=""
                        className="size-8 shrink-0 rounded-full object-cover"
                      />
                    ) : (
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted">
                        <User className="size-4 text-muted-foreground" />
                      </div>
                    )}
                    <span className="font-medium">{social.username}</span>
                    {social.isAlt && (
                      <span className="text-xs text-muted-foreground">-Alt</span>
                    )}
                    {social.followerCount != null && (
                      <span className="text-xs text-muted-foreground">
                        {social.followerCount} followers
                      </span>
                    )}
                    <div className="ml-auto flex gap-1">
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
                    </div>
                  </div>
                  <p className="mt-1 pl-7 text-xs text-muted-foreground">
                    {social.bio || "no bio yet."}
                  </p>
                </div>
              );
            })}
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
