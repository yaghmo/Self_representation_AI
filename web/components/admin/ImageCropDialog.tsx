"use client";

import { useEffect, useState } from "react";
import Cropper, { type Area } from "react-easy-crop";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ProfileHeader } from "@/components/fan/ProfileHeader";
import { cropImageToBlob } from "@/lib/cropImage";

export function ImageCropDialog({
  file,
  shape,
  aspect,
  otherPfpUrl,
  otherBannerUrl,
  bio,
  onCancel,
  onConfirm,
}: {
  file: File;
  shape: "round" | "rect";
  aspect: number;
  otherPfpUrl: string | null;
  otherBannerUrl: string | null;
  bio: string | null;
  onCancel: () => void;
  onConfirm: (blob: Blob) => Promise<void>;
}) {
  // Created and revoked in the same effect run, not split across a memo and
  // a separate cleanup — React Strict Mode's dev-only double-invoke
  // (mount -> cleanup -> mount) would otherwise revoke the URL a memoized
  // value still points to, before the real render ever uses it.
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const [step, setStep] = useState<"crop" | "preview">("crop");
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [croppedArea, setCroppedArea] = useState<Area | null>(null);
  const [croppedUrl, setCroppedUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleNext() {
    if (!croppedArea || !imageUrl) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await cropImageToBlob(imageUrl, croppedArea, file.type || "image/png");
      setCroppedUrl(URL.createObjectURL(blob));
      setStep("preview");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!croppedArea || !imageUrl) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await cropImageToBlob(imageUrl, croppedArea, file.type || "image/png");
      await onConfirm(blob);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const previewProfile = {
    name: "You",
    bio: bio ?? "",
    pfpUrl: shape === "round" ? croppedUrl : otherPfpUrl,
    bannerUrl: shape === "rect" ? croppedUrl : otherBannerUrl,
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{step === "crop" ? "Crop image" : "How it'll look"}</DialogTitle>
        </DialogHeader>

        {error && <p className="text-xs text-destructive">{error}</p>}

        {step === "crop" ? (
          <>
            <div className="relative h-64 w-full overflow-hidden rounded-lg bg-muted">
              {imageUrl && (
                <Cropper
                  image={imageUrl}
                  crop={crop}
                  zoom={zoom}
                  aspect={aspect}
                  cropShape={shape}
                  onCropChange={setCrop}
                  onZoomChange={setZoom}
                  onCropComplete={(_, pixels) => setCroppedArea(pixels)}
                />
              )}
            </div>
            <input
              type="range"
              min={1}
              max={3}
              step={0.01}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              className="w-full"
              aria-label="Zoom"
            />
            <DialogFooter>
              <Button variant="outline" onClick={onCancel}>
                Cancel
              </Button>
              <Button onClick={handleNext} disabled={!croppedArea || !imageUrl || busy}>
                {busy ? "…" : "Next"}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <div className="pointer-events-none rounded-lg border p-3">
              <ProfileHeader profile={previewProfile} expanded={false} onCollapse={() => {}} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setStep("crop")} disabled={busy}>
                Back
              </Button>
              <Button onClick={handleConfirm} disabled={busy}>
                {busy ? "Uploading…" : "Confirm"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
