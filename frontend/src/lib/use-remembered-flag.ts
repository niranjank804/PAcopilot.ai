"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * A yes/no layout preference (a collapsed pane, say) remembered in this
 * browser. Starts at `initial` on every render path, then picks up the
 * stored value after mount, so the server render and the first client
 * render agree. Storage can be missing or refuse (private windows); the
 * flag then simply is not remembered.
 */
export function useRememberedFlag(key: string, initial: boolean) {
  const [value, setValue] = useState(initial);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored === "1" || stored === "0") setValue(stored === "1");
    } catch {
      // Not remembered; the default stands.
    }
  }, [key]);

  const update = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // Not remembered; it still applies for this visit.
      }
    },
    [key],
  );

  return [value, update] as const;
}
