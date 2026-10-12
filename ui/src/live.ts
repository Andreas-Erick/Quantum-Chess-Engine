import { useEffect, useRef, useState } from "react";
import { liveUrl } from "./api";
import type { LiveMessage } from "./types";

const RETRY_MS = 2000;
const KEEPALIVE_MS = 25000;
const UNKNOWN_GAME = 4404; // close code from the server

/**
 * Follow a game's live feed while `gameId` is set, reconnecting if the connection drops.
 * Returns whether the feed is currently connected.
 */
export function useLiveFeed(gameId: string | null, onMessage: (message: LiveMessage) => void): boolean {
  const handler = useRef(onMessage);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    handler.current = onMessage;
  });

  useEffect(() => {
    if (!gameId || typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(liveUrl(gameId));
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data) as LiveMessage);
        } catch {
          // ignore malformed messages
        }
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (!stopped && event.code !== UNKNOWN_GAME) retry = window.setTimeout(connect, RETRY_MS);
      };
    };
    connect();
    // Proxies close idle connections; a message now and then keeps it open.
    const keepalive = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
    }, KEEPALIVE_MS);

    return () => {
      stopped = true;
      window.clearTimeout(retry);
      window.clearInterval(keepalive);
      socket?.close();
      setConnected(false);
    };
  }, [gameId]);

  return connected;
}
