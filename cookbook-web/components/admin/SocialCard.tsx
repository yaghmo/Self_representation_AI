"use client";

import { useCallback, useEffect, useState } from "react";
import { getSocials } from "@/lib/admin/socialApi";
import { SocialDialog } from "./SocialDialog";

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
    <>
      <h3>Profile</h3>
      <p>
        {count === null
          ? "..."
          : count === 0
            ? "No profile linked to this account yet"
            : `${count} social${count === 1 ? "" : "s"} linked`}
      </p>
      <button onClick={() => setOpen(true)}>View/Update Profile</button>
      {open && (
        <SocialDialog
          onClose={() => {
            setOpen(false);
            refresh();
          }}
        />
      )}
    </>
  );
}
