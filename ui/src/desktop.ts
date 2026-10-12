import { useEffect, useState } from "react";

// What the desktop app (desktop/app.py) offers the page as window.pywebview.api.
// Hosting and joining are only allowed on the app's own page, never on a host's page.
export interface DesktopApi {
  /** Whether this page is the app's own, and its network and internet addresses while hosting. */
  info(): Promise<{ own_page: boolean; lan_url: string | null; public_url: string | null }>;
  /** Start accepting players from the local network; resolves to the address to invite to. */
  host(): Promise<string>;
  /** Also accept players from the internet; resolves to the temporary public address. */
  share_online(): Promise<string>;
  /** Stop accepting players from the network and the internet. */
  stop_hosting(): Promise<void>;
  /** Join from an invite link. The app generates and keeps the seed, then opens the game. */
  join(link: string): Promise<void>;
  /** Back to this app's own games. */
  home(): Promise<void>;
}

export interface Desktop {
  api: DesktopApi;
  /** Whether this page is the app's own (not a friend's host page after joining). */
  ownPage: boolean;
  /** The network address invite links point at, once hosting. */
  lanUrl: string | null;
  /** The internet address invite links point at instead, once shared online. */
  publicUrl: string | null;
}

export type HostingUpdate = Partial<Pick<Desktop, "lanUrl" | "publicUrl">>;

declare global {
  interface Window {
    pywebview?: { api: DesktopApi };
  }
}

/** The desktop bridge, or null in a normal browser. */
export function useDesktop(): [Desktop | null, (update: HostingUpdate) => void] {
  const [desktop, setDesktop] = useState<Desktop | null>(null);

  useEffect(() => {
    let cancelled = false;
    const connect = () => {
      const api = window.pywebview?.api;
      if (!api) return;
      api
        .info()
        .then((info) => {
          if (cancelled) return;
          setDesktop({ api, ownPage: info.own_page, lanUrl: info.lan_url, publicUrl: info.public_url });
        })
        .catch(() => {});
    };
    connect(); // the bridge may already be there
    window.addEventListener("pywebviewready", connect);
    return () => {
      cancelled = true;
      window.removeEventListener("pywebviewready", connect);
    };
  }, []);

  const setHosting = (update: HostingUpdate) => setDesktop((d) => (d ? { ...d, ...update } : d));
  return [desktop, setHosting];
}

/** A random hex string for the joiner's share of the dice. */
export function randomSeed(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
