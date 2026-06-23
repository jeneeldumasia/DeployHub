"use client";

import { useEffect, useRef, useState } from "react";
import { Terminal, Wifi, WifiOff } from "lucide-react";

const ANSI_RE = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g;

interface Props {
  projectId: string;
  deploymentId: string;
  token?: string;
}

/**
 * Inline live-log terminal shown on the deployment page while a build is active.
 * Connects directly to the WS log endpoint and streams output in real-time.
 * Automatically stops when the server closes the connection (build finished).
 */
export function LiveLogPanel({ projectId, deploymentId, token }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!token) return;

    const wsUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
      .replace(/^http/, "ws");

    const ws = new WebSocket(
      `${wsUrl}/ws/projects/${projectId}/deployments/${deploymentId}/logs?token=${token}`
    );
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (e: MessageEvent) => {
      const line = (e.data as string).replace(ANSI_RE, "");
      setLines((prev) => [...prev, line]);
    };

    ws.onerror = () => {
      setLines((prev) => [...prev, "\n[connection error]"]);
      setConnected(false);
      setEnded(true);
    };

    ws.onclose = () => {
      setConnected(false);
      setEnded(true);
    };

    return () => {
      ws.close();
    };
  }, [projectId, deploymentId, token]);

  // Auto-scroll to bottom on new lines
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-canvas-border bg-zinc-900/80">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-brand" />
          <span className="text-xs font-semibold font-mono text-zinc-200">Build Output</span>
        </div>
        <div className="flex items-center gap-1.5">
          {connected && (
            <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium">
              <Wifi size={11} className="animate-pulse" />
              Live
            </span>
          )}
          {ended && (
            <span className="flex items-center gap-1 text-xs text-zinc-500 font-medium">
              <WifiOff size={11} />
              Stream ended
            </span>
          )}
          {!connected && !ended && (
            <span className="text-xs text-zinc-500 font-medium animate-pulse">Connecting…</span>
          )}
        </div>
      </div>

      {/* Terminal body */}
      <div className="bg-zinc-950 h-72">
        {lines.length === 0 && !ended ? (
          <div className="flex items-center justify-center h-full text-zinc-600 font-mono text-xs gap-2">
            <Wifi size={13} className="animate-pulse text-emerald-600" />
            Waiting for build output…
          </div>
        ) : (
          <pre
            ref={scrollRef}
            className="h-full overflow-y-auto p-4 text-[11px] font-mono leading-relaxed text-zinc-300 whitespace-pre-wrap"
          >
            {lines.join("\n")}
            {/* Blinking cursor while live */}
            {connected && (
              <span className="inline-block w-1.5 h-3 bg-emerald-400 ml-0.5 animate-pulse align-text-bottom" />
            )}
          </pre>
        )}
      </div>
    </div>
  );
}
