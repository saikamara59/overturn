type Listener = (e: { matches: boolean }) => void;

let mobile = false;
const listeners = new Set<Listener>();

/** Installed once from vitest.setup.ts — jsdom has no matchMedia. */
export function installMatchMedia(): void {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      get matches() {
        // Our app only queries the mobile breakpoint; anything else is false.
        return query.includes('max-width') ? mobile : false;
      },
      media: query,
      addEventListener: (_: 'change', fn: Listener) => listeners.add(fn),
      removeEventListener: (_: 'change', fn: Listener) => listeners.delete(fn),
      onchange: null,
      addListener: (fn: Listener) => listeners.add(fn),
      removeListener: (fn: Listener) => listeners.delete(fn),
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

/** Switch the simulated viewport; notifies mounted hooks. */
export function setViewportMobile(next: boolean): void {
  mobile = next;
  listeners.forEach((fn) => fn({ matches: next }));
}

export function resetViewport(): void {
  mobile = false;
  listeners.clear();
}
