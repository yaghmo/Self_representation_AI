"use client";

import { useRef, useState } from "react";
import { bannerUrl, pfpUrl, uploadBanner, uploadPfp } from "@/lib/admin/socialApi";
import { User } from "lucide-react";
import { ImageCropDialog } from "@/components/admin/ImageCropDialog";

const ACCEPT = "image/png,image/jpeg,image/webp";
const PFP_ASPECT = 1;
const BANNER_ASPECT = 3;

function UploadButton({
  className,
  src,
  onClick,
  fallback,
}: {
  className: string;
  src: string | null;
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
        // eslint-disable-next-line @next/next/no-img-element -- local blob/service URL, not a next/image remote host
        <img src={src} alt="" className="size-full object-cover" />
      ) : (
        <div className="flex size-full items-center justify-center">{fallback}</div>
      )}
      <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-[10px] text-transparent transition-colors hover:bg-black/40 hover:text-white">
        Change
      </span>
    </button>
  );
}

type CropTarget = { kind: "pfp" | "banner"; file: File };

export function ProfileImages({
  pfpVersion,
  bannerVersion,
  bio,
  onSaved,
}: {
  pfpVersion: number | null;
  bannerVersion: number | null;
  bio: string | null;
  onSaved: () => void;
}) {
  const pfpInputRef = useRef<HTMLInputElement>(null);
  const bannerInputRef = useRef<HTMLInputElement>(null);
  const [cropTarget, setCropTarget] = useState<CropTarget | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(kind: CropTarget["kind"]) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (file) setCropTarget({ kind, file });
    };
  }

  async function handleCropConfirm(blob: Blob) {
    if (!cropTarget) return;
    try {
      if (cropTarget.kind === "pfp") await uploadPfp(blob);
      else await uploadBanner(blob);
      setError(null);
      setCropTarget(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const pfpSrc = pfpVersion != null ? pfpUrl(pfpVersion) : null;
  const bannerSrc = bannerVersion != null ? bannerUrl(bannerVersion) : null;

  return (
    <div className="space-y-1 pb-6">
      <p className="text-xs font-medium text-muted-foreground">Profile images</p>
      <div className="relative">
        <UploadButton
          className="h-24 w-full rounded-lg border"
          src={bannerSrc}
          onClick={() => bannerInputRef.current?.click()}
          fallback={null}
        />
        <div className="absolute -bottom-6 left-4">
          <UploadButton
            className="size-16 rounded-full border-4 border-background shadow"
            src={pfpSrc}
            onClick={() => pfpInputRef.current?.click()}
            fallback={<User className="size-6 text-muted-foreground" />}
          />
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
        accept={ACCEPT}
        className="hidden"
        onChange={handleFileChange("pfp")}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}

      {cropTarget && (
        <ImageCropDialog
          file={cropTarget.file}
          shape={cropTarget.kind === "pfp" ? "round" : "rect"}
          aspect={cropTarget.kind === "pfp" ? PFP_ASPECT : BANNER_ASPECT}
          otherPfpUrl={cropTarget.kind === "banner" ? pfpSrc : null}
          otherBannerUrl={cropTarget.kind === "pfp" ? bannerSrc : null}
          bio={bio}
          onCancel={() => setCropTarget(null)}
          onConfirm={handleCropConfirm}
        />
      )}
    </div>
  );
}
