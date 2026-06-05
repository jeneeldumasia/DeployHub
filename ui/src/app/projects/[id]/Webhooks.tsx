"use client";

import { useState } from "react";
import { Webhook, Copy, Check } from "lucide-react";

export function Webhooks({ projectId, webhookSecret }: { projectId: string; webhookSecret?: string }) {
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);

  const webhookUrl = typeof window !== "undefined" 
    ? `${window.location.origin}/api/proxy/webhooks/github/${projectId}`
    : "";

  const copyUrl = () => {
    navigator.clipboard.writeText(webhookUrl);
    setCopiedUrl(true);
    setTimeout(() => setCopiedUrl(false), 2000);
  };

  const copySecret = () => {
    if (webhookSecret) {
      navigator.clipboard.writeText(webhookSecret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
    }
  };

  return (
    <div className="card overflow-hidden mt-6">
      <div className="px-6 py-4 border-b border-canvas-border flex items-center gap-2">
        <Webhook size={16} className="text-text-secondary" />
        <h2 className="text-sm font-semibold text-text-primary">GitHub Webhooks</h2>
      </div>

      <div className="p-6">
        <p className="text-sm text-text-secondary mb-6">
          Configure a webhook in your GitHub repository to automatically trigger deployments on push.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">Payload URL</label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={webhookUrl}
                className="flex-1 bg-black/5 dark:bg-white/5 border border-canvas-border rounded px-3 py-2 text-sm font-mono focus:outline-none"
              />
              <button
                onClick={copyUrl}
                className="btn-secondary py-2 px-3"
                title="Copy URL"
              >
                {copiedUrl ? <Check size={16} className="text-emerald-500" /> : <Copy size={16} />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">Secret</label>
            <div className="flex items-center gap-2">
              <input
                type="text"
                readOnly
                value={webhookSecret || "Not generated"}
                className="flex-1 bg-black/5 dark:bg-white/5 border border-canvas-border rounded px-3 py-2 text-sm font-mono focus:outline-none"
              />
              <button
                onClick={copySecret}
                disabled={!webhookSecret}
                className="btn-secondary py-2 px-3 disabled:opacity-50"
                title="Copy Secret"
              >
                {copiedSecret ? <Check size={16} className="text-emerald-500" /> : <Copy size={16} />}
              </button>
            </div>
          </div>
          
          <div className="pt-2 text-xs text-text-secondary">
            Set the Content type to <code>application/json</code> and select the <code>push</code> event.
          </div>
        </div>
      </div>
    </div>
  );
}
