"use client";

import { useRef, useState } from "react";
import {
  bannerUrl,
  chatIconUrl,
  landingPfpUrl,
  pfpUrl,
  uploadBanner,
  uploadChatIcon,
  uploadLandingPfp,
  uploadPfp,
} from "@/lib/admin/socialApi";
import { MessageCircle, User } from "lucide-react";
import { PlayOnceVideo } from "@/components/media/PlayOnceVideo";
import { ImageCropDialog } from "@/components/admin/ImageCropDialog";

const ACCEPT = "image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime";
const PFP_ACCEPT = `${ACCEPT},image/gif`;
const PFP_ASPECT = 1;
const BANNER_ASPECT = 3;

function isVideo(mime: string | null | undefined) {
  return !!mime?.startsWith("video/");
}

function UploadButton({
  className,
  src,
  mime,
  onClick,
  fallback,
}: {
  className: string;
  src: string | null;
  mime?: string | null;
  onClick: () => void;
  fallback: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${className} relative overflow-hidden bg-muted`}
    >
      {src ? (
        isVideo(mime) ? (
          <PlayOnceVideo src={src} className="size-full object-cover" />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- local blob/service URL, not a next/image remote host
          <img src={src} alt="" className="size-full object-cover" />
        )
      ) : (
        <div className="flex size-full items-center justify-center">{fallback}</div>
      )}
      <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-[10px] text-transparent transition-colors hover:bg-black/40 hover:text-white">
        Change
      </span>
    </button>
  );
}

// Cropping only makes sense for a static image; a video clip uploads as-is,
// and the chat icon slot skips cropping entirely (no aspect ratio to enforce).
// The landing pfp shares the pfp's round/1:1 crop treatment.
type CropTarget = { kind: "pfp" | "banner" | "landingPfp"; file: File };

export function ProfileImages({
  pfpVersion,
  bannerVersion,
  chatIconVersion,
  landingPfpVersion,
  pfpMime,
  bannerMime,
  chatIconMime,
  landingPfpMime,
  bio,
  onSaved,
}: {
  pfpVersion: number | null;
  bannerVersion: number | null;
  chatIconVersion: number | null;
  landingPfpVersion: number | null;
  pfpMime: string | null;
  bannerMime: string | null;
  chatIconMime: string | null;
  landingPfpMime: string | null;
  bio: string | null;
  onSaved: () => void;
}) {
  const pfpInputRef = useRef<HTMLInputElement>(null);
  const bannerInputRef = useRef<HTMLInputElement>(null);
  const chatIconInputRef = useRef<HTMLInputElement>(null);
  const landingPfpInputRef = useRef<HTMLInputElement>(null);
  const [cropTarget, setCropTarget] = useState<CropTarget | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function uploadDirect(kind: "pfp" | "banner" | "chatIcon" | "landingPfp", blob: Blob) {
    try {
      if (kind === "pfp") await uploadPfp(blob);
      else if (kind === "banner") await uploadBanner(blob);
      else if (kind === "chatIcon") await uploadChatIcon(blob);
      else await uploadLandingPfp(blob);
      setError(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function handleFileChange(kind: CropTarget["kind"]) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      // A video clip (or gif, transcoded server-side) has no crop step — it uploads as-is.
      if (file.type.startsWith("video/") || file.type === "image/gif") uploadDirect(kind, file);
      else setCropTarget({ kind, file });
    };
  }

  function handleChatIconChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) uploadDirect("chatIcon", file);
  }

  async function handleCropConfirm(blob: Blob) {
    if (!cropTarget) return;
    try {
      if (cropTarget.kind === "pfp") await uploadPfp(blob);
      else if (cropTarget.kind === "banner") await uploadBanner(blob);
      else await uploadLandingPfp(blob);
      setError(null);
      setCropTarget(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const pfpSrc = pfpVersion != null ? pfpUrl(pfpVersion) : null;
  const bannerSrc = bannerVersion != null ? bannerUrl(bannerVersion) : null;
  const chatIconSrc = chatIconVersion != null ? chatIconUrl(chatIconVersion) : null;
  const landingPfpSrc = landingPfpVersion != null ? landingPfpUrl(landingPfpVersion) : null;

  return (
    <div className="space-y-1 pb-6">
      <p className="text-xs font-medium text-muted-foreground">Profile images</p>
      <p className="text-xs text-muted-foreground">
        A clip (mp4/webm, up to 10s) plays once and freezes on its last frame — same slots as a
        static image. The main pfp also accepts gif and replays every 60s.
      </p>
      <div className="flex gap-4">
        <div className="relative flex-1 pb-6">
          <UploadButton
            className="h-24 w-full rounded-lg border"
            src={bannerSrc}
            mime={bannerMime}
            onClick={() => bannerInputRef.current?.click()}
            fallback={null}
          />
          <div className="absolute -bottom-6 left-4">
            <UploadButton
              className="size-16 rounded-full border-4 border-background shadow"
              src={pfpSrc}
              mime={pfpMime}
              onClick={() => pfpInputRef.current?.click()}
              fallback={<User className="size-6 text-muted-foreground" />}
            />
          </div>
        </div>
        <div className="flex w-28 shrink-0 flex-col items-center gap-1.5 pt-2">
          <UploadButton
            className="size-24 rounded-full border-4 border-background shadow"
            src={landingPfpSrc}
            mime={landingPfpMime}
            onClick={() => landingPfpInputRef.current?.click()}
            fallback={<User className="size-8 text-muted-foreground" />}
          />
          <p className="text-center text-xs text-muted-foreground">
            Landing pfp — plays on the fan landing page
          </p>
        </div>
      </div>
      <input
        ref={bannerInputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={handleFileChange("banner")}
      />
      <input
        ref={pfpInputRef}
        type="file"
        accept={PFP_ACCEPT}
        className="hidden"
        onChange={handleFileChange("pfp")}
      />
      <input
        ref={landingPfpInputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={handleFileChange("landingPfp")}
      />

      <div className="flex items-center gap-2 pt-8">
        <UploadButton
          className="size-12 rounded-full border"
          src={chatIconSrc}
          mime={chatIconMime}
          onClick={() => chatIconInputRef.current?.click()}
          fallback={<MessageCircle className="size-5 text-muted-foreground" />}
        />
        <p className="text-xs text-muted-foreground">
          Chat icon — replays on open and on each message sent
          <br />
          Recommended 720x720
        </p>
      </div>
      <input
        ref={chatIconInputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={handleChatIconChange}
      />

      {error && <p className="text-xs text-destructive">{error}</p>}

      {cropTarget && (
        <ImageCropDialog
          file={cropTarget.file}
          shape={cropTarget.kind === "banner" ? "rect" : "round"}
          aspect={cropTarget.kind === "banner" ? BANNER_ASPECT : PFP_ASPECT}
          otherPfpUrl={cropTarget.kind === "banner" ? pfpSrc : null}
          otherBannerUrl={cropTarget.kind !== "banner" ? bannerSrc : null}
          bio={bio}
          onCancel={() => setCropTarget(null)}
          onConfirm={handleCropConfirm}
        />
      )}
    </div>
  );
}
