"use client";

import { useCallback, useEffect, useState } from "react";
import { getSocials } from "@/lib/admin/socialApi";
import { SocialDialog } from "./SocialDialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function SocialCard() {
  const [count, setCount] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(() => {
    getSocials()
      .then((res) => setCount(res.socials.length))
      .catch(() => setCount(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Profile</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">
          {count === null
            ? "…"
            : count === 0
              ? "No profile linked to this account yet"
              : `${count} social${count === 1 ? "" : "s"} linked`}
        </p>
        <Button variant="outline" size="sm" className="w-full" onClick={() => setOpen(true)}>
          View/Update Profile
        </Button>
      </CardContent>
      {open && (
        <SocialDialog
          onClose={() => {
            setOpen(false);
            refresh();
          }}
        />
      )}
    </Card>
  );
}
