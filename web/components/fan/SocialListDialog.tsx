"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SocialRow } from "@/components/SocialRow";
import type { PublicSocial } from "@/lib/socialApi";

export function SocialListDialog({
  socials,
  onClose,
}: {
  socials: PublicSocial[];
  onClose: () => void;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-md overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Socials</DialogTitle>
        </DialogHeader>
        <div className="space-y-1">
          {socials.map((social) => (
            <a
              key={social.id}
              href={social.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-md hover:bg-muted/50"
            >
              <SocialRow
                platform={social.platform}
                username={social.username}
                isAlt={social.isAlt}
                followerCount={social.followerCount}
                pfpUrl={social.pfpUrl}
                bio={social.bio}
              />
            </a>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
