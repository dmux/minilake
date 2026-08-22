import { afterEach, describe, expect, it, vi } from "vitest";

const KEY = "minilake.editor-tabs";

type Store = typeof import("../editor-tabs").useEditorTabsStore;

/**
 * The store is created — and `persist` reads storage — at module load, so every
 * case installs its own `window.localStorage` first and imports afterwards.
 */
async function loadStore(localStorage: unknown): Promise<Store> {
  vi.resetModules();
  Object.defineProperty(globalThis, "window", {
    value: {
      get localStorage() {
        if (localStorage instanceof Error) throw localStorage;
        return localStorage;
      },
    },
    configurable: true,
    writable: true,
  });
  return (await import("../editor-tabs")).useEditorTabsStore;
}

function memoryStorage(seed: Record<string, string> = {}) {
  const data = { ...seed };
  return {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
    removeItem: (key: string) => {
      delete data[key];
    },
  };
}

function persisted(tabs: { id: string; title: string; sql: string }[], activeTabId: string | null) {
  return JSON.stringify({ state: { tabs, activeTabId }, version: 0 });
}

const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");

afterEach(() => {
  if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
  else delete (globalThis as { window?: unknown }).window;
});

describe("useEditorTabsStore", () => {
  it("has already restored persisted tabs on the first read", async () => {
    // The invariant the query editor page depends on: by the time an effect runs,
    // rehydration is done, so `tabs.length === 0` means "nothing to restore".
    const store = await loadStore(
      memoryStorage({
        [KEY]: persisted([{ id: "tab_saved", title: "Query 1", sql: "SELECT 42;" }], "tab_saved"),
      }),
    );

    expect(store.getState().tabs).toHaveLength(1);
    expect(store.getState().tabs[0].sql).toBe("SELECT 42;");
    expect(store.getState().activeTabId).toBe("tab_saved");
  });

  it("still reports an empty list through getInitialState after restoring tabs", async () => {
    // Not a wart to fix here, but the reason the query editor page gates its
    // "open a first tab" effect on `useIsMounted`: zustand hands React
    // `getInitialState()` as the server snapshot, and `persist` pins that to the
    // pre-rehydration state. The hydration render — and the effect after it — see
    // no tabs even though localStorage had some. Drop the gate and every reload
    // adds a blank tab beside the restored ones.
    const store = await loadStore(
      memoryStorage({
        [KEY]: persisted([{ id: "tab_saved", title: "Query 1", sql: "SELECT 42;" }], "tab_saved"),
      }),
    );

    expect(store.getState().tabs).toHaveLength(1);
    expect(store.getInitialState().tabs).toEqual([]);
  });

  it("starts empty and usable when nothing was stored", async () => {
    const store = await loadStore(memoryStorage());

    expect(store.getState().tabs).toEqual([]);

    const id = store.getState().addTab();
    expect(store.getState().tabs).toHaveLength(1);
    expect(store.getState().activeTabId).toBe(id);
  });

  it("stays usable when reading storage throws", async () => {
    const store = await loadStore({
      ...memoryStorage(),
      getItem: () => {
        throw new Error("storage blocked");
      },
    });

    expect(store.getState().tabs).toEqual([]);
    store.getState().addTab({ title: "Query 1", sql: "SELECT 1;" });
    expect(store.getState().tabs).toHaveLength(1);
  });

  it("stays usable when localStorage itself is unreachable", async () => {
    // Safari private mode / blocked site data: touching `window.localStorage` throws,
    // and `persist` then skips rehydration entirely.
    const store = await loadStore(new Error("SecurityError"));

    expect(store.getState().tabs).toEqual([]);
    store.getState().addTab();
    expect(store.getState().tabs).toHaveLength(1);
  });

  it("leaves no active tab once the last one is closed", async () => {
    // The state the page has to recover from by opening a fresh tab.
    const store = await loadStore(memoryStorage());
    const id = store.getState().addTab();

    store.getState().closeTab(id);

    expect(store.getState().tabs).toEqual([]);
    expect(store.getState().activeTabId).toBeNull();
  });

  it("keeps focus on the neighbouring tab when closing the active one", async () => {
    const store = await loadStore(memoryStorage());
    const first = store.getState().addTab();
    const second = store.getState().addTab();
    const third = store.getState().addTab();

    store.getState().setActiveTab(second);
    store.getState().closeTab(second);

    expect(store.getState().tabs.map((t) => t.id)).toEqual([first, third]);
    expect(store.getState().activeTabId).toBe(third);
  });
});
