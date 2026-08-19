import * as React from "react"

const MOBILE_BREAKPOINT = 768

/**
 * True below the mobile breakpoint.
 *
 * Rewritten from shadcn's stock `useState` + `useEffect` version, which sets state
 * inside the effect body to seed the initial value — a cascading render that React
 * 19's compiler rejects. `useSyncExternalStore` subscribes to the media query
 * directly and supplies a server snapshot, so there is no extra render pass and no
 * hydration mismatch.
 */
export function useIsMobile() {
  const subscribe = React.useCallback((onStoreChange: () => void) => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    mql.addEventListener("change", onStoreChange)
    return () => mql.removeEventListener("change", onStoreChange)
  }, [])

  return React.useSyncExternalStore(
    subscribe,
    () => window.innerWidth < MOBILE_BREAKPOINT,
    // Server rendering has no viewport; desktop is the safer default for a
    // developer tool, and the first client render corrects it.
    () => false,
  )
}
