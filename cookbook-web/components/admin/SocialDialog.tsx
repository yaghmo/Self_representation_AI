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
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          background: "white",
          color: "#111",
          padding: 24,
          maxWidth: 600,
          width: "90%",
          maxHeight: "80vh",
          overflow: "auto",
        }}
      >
        <h2>Profile</h2>
        {error && <p style={{ color: "red" }}>{error}</p>}

        {loading ? (
          <p>Loading...</p>
        ) : socials.length === 0 && !form ? (
          <p>No profile linked to this account yet</p>
        ) : (
          socials.map((social) => (
            <div
              key={social.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 0",
                borderBottom: "1px solid #eee",
              }}
            >
              <span>{social.platform}</span>
              <span>{social.username}</span>
              {social.followerCount != null && (
                <span>{social.followerCount} followers</span>
              )}
              {social.isAlt && (
                <span style={{ fontSize: 11, color: "#888" }}>-Alt</span>
              )}
              <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                <button onClick={() => startEdit(social)}>Update</button>
                <button onClick={() => handleDelete(social.id)}>Delete</button>
              </div>
            </div>
          ))
        )}

        {form ? (
          <div style={{ marginTop: 16 }}>
            <h3>{form.id ? "Update social" : "Add social"}</h3>
            <label style={{ display: "block" }}>
              Link
              <input
                value={form.url}
                onChange={(e) => handleUrlChange(e.target.value)}
                style={{ width: "100%" }}
              />
            </label>
            <label style={{ display: "block" }}>
              Platform
              <select
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
              >
                {COMMON_PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
                <option value="other">Other</option>
              </select>
            </label>
            {form.platform === "other" && (
              <label style={{ display: "block" }}>
                Platform name
                <input
                  value={form.platformOther}
                  onChange={(e) =>
                    setForm({ ...form, platformOther: e.target.value })
                  }
                />
              </label>
            )}
            <label style={{ display: "block" }}>
              Username
              <input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </label>
            <label style={{ display: "block" }}>
              Bio
              <textarea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
              />
            </label>
            <label style={{ display: "block" }}>
              Follower count
              <input
                type="number"
                value={form.followerCount}
                onChange={(e) =>
                  setForm({ ...form, followerCount: e.target.value })
                }
              />
            </label>
            <label style={{ display: "block" }}>
              Profile picture URL
              <input
                value={form.pfpUrl}
                onChange={(e) => setForm({ ...form, pfpUrl: e.target.value })}
              />
            </label>
            {activePlatform && platformHasOtherEntry(activePlatform) && (
              <label style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={form.isAlt}
                  onChange={(e) =>
                    setForm({ ...form, isAlt: e.target.checked })
                  }
                />{" "}
                -Alt (a second account for this platform)
              </label>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={handleSave}>Save</button>
              <button onClick={() => setForm(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <button onClick={startAdd} style={{ marginTop: 16 }}>
            Add social
          </button>
        )}

        <div style={{ marginTop: 16 }}>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
