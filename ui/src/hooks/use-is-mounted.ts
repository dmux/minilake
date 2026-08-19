"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * False during server rendering and the first client render, true afterwards.
 *
 * The usual `useState(false)` + `useEffect(() => setMounted(true))` does the same
 * thing but sets state inside an effect, which React 19's compiler flags as a
 * cascading render. `useSyncExternalStore` expresses "the server and the client
 * disagree about this value" directly, with no extra render pass.
 *
 * Needed wherever the markup depends on something only the browser knows — the
 * resolved theme, `window` dimensions — since rendering it on the server would be
 * a hydration mismatch.
 */
export function useIsMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
