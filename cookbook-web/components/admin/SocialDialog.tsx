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
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  const [form, setForm] = useState<FormState | null>(null);

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

  function startAdd() {
    setForm({ ...EMPTY_FORM });
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
    if (!form) return;
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
    if (!form) return;
    const platform =
      form.platform === "other" ? form.platformOther.trim() : form.platform;
    if (!platform || !form.username || !form.url) {
      setError("platform, username, and url are required");
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
      setForm(null);
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

  function platformHasOtherEntry(platform: string) {
    return socials.some((s) => s.platform === platform && s.id !== form?.id);
  }

  const activePlatform =
    form?.platform === "other" ? form.platformOther : form?.platform ?? "";

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

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : socials.length === 0 && !form ? (
          <p className="text-sm text-muted-foreground">
            No profile linked to this account yet
          </p>
        ) : (
          <div className="space-y-1">
            {socials.map((social) => {
              const Icon = platformIcon(social.platform);
              return (
                <div
                  key={social.id}
                  className="flex items-center gap-3 border-b py-2 text-sm last:border-b-0"
                >
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
              );
            })}
          </div>
        )}

        {form ? (
          <div className="space-y-3 pt-2">
            <Separator />
            <p className="text-sm font-medium">{form.id ? "Update social" : "Add social"}</p>
            <div className="space-y-1">
              <Label>Link</Label>
              <Input value={form.url} onChange={(e) => handleUrlChange(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Platform</Label>
              <Select
                value={form.platform}
                onValueChange={(v) => v !== null && setForm({ ...form, platform: v })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {COMMON_PLATFORMS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.platform === "other" && (
              <div className="space-y-1">
                <Label>Platform name</Label>
                <Input
                  value={form.platformOther}
                  onChange={(e) => setForm({ ...form, platformOther: e.target.value })}
                />
              </div>
            )}
            <div className="space-y-1">
              <Label>Username</Label>
              <Input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>Bio</Label>
              <Textarea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>Follower count</Label>
              <Input
                type="number"
                value={form.followerCount}
                onChange={(e) => setForm({ ...form, followerCount: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>Profile picture URL</Label>
              <Input
                value={form.pfpUrl}
                onChange={(e) => setForm({ ...form, pfpUrl: e.target.value })}
              />
            </div>
            {activePlatform && platformHasOtherEntry(activePlatform) && (
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={form.isAlt}
                  onCheckedChange={(checked) => setForm({ ...form, isAlt: checked === true })}
                />
                <Label className="font-normal">-Alt (a second account for this platform)</Label>
              </div>
            )}
            <div className="flex gap-2 pt-2">
              <Button onClick={handleSave}>Save</Button>
              <Button variant="outline" onClick={() => setForm(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="outline" onClick={startAdd}>
            Add social
          </Button>
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
