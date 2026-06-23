"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

/**
 * Connects to the WebSocket status endpoint for live updates.
 * Calls router.refresh() when the backend emits a state transition.
 * Automatically reconnects if the connection drops during long builds.
 */
export function AutoRefresh({ projectId, deploymentId, token }: { projectId: string; deploymentId: string; token?: string }) {
  const router = useRouter();
  const lastState = useRef<string | null>(null);

  useEffect(() => {
    if (!token) return;
    
    let ws: WebSocket;
    let reconnectTimer: NodeJS.Timeout;
    let isUnmounted = false;

    const connect = () => {
      const wsUrl = process.env.NEXT_PUBLIC_API_URL?.replace("http", "ws") || "ws://localhost:8000";
      ws = new WebSocket(`${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/status?token=${token}`);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.state && data.state !== lastState.current) {
            lastState.current = data.state;
            router.refresh();
          }
        } catch (e) {
          console.error("Failed to parse websocket message", e);
        }
      };

      ws.onclose = () => {
        if (!isUnmounted) {
          // Cloudflare drops idle WS after 100s. Reconnect automatically.
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
    };

    connect();

    return () => {
      isUnmounted = true;
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.close();
      }
    };
  }, [router, projectId, deploymentId, token]);

  return null;
}
