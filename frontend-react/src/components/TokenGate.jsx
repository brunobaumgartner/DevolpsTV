import { useState } from "preact/hooks";

// visitante sem sessão de admin e sem token salvo: cola o link/token
const RE = /\/p\/([^/]+)\//;

export function TokenGate({ onSave }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState("");

  function submit(e) {
    e.preventDefault();
    const m = v.match(RE);
    const token = (m ? m[1] : v).trim();
    if (!token) return setErr("Cole um link ou token válido.");
    onSave(token);
  }

  return (
    <div class="min-h-[60vh] grid place-items-center p-6">
      <form onSubmit={submit} class="w-full max-w-sm">
        <h1 class="text-accent font-display font-bold uppercase tracking-widest text-lg mb-1">DevolpsTV</h1>
        <p class="text-sm text-muted mb-4">Cole o link da sua playlist (ou o token) para acessar.</p>
        <input
          value={v}
          onInput={(e) => setV(e.currentTarget.value)}
          placeholder="https://…/p/SEU_TOKEN/playlist.m3u8"
          class="w-full bg-[#081019] border border-border rounded px-3 py-2 text-sm"
        />
        {err && <p class="text-danger text-xs mt-2">{err}</p>}
        <button class="btn mt-3 w-full justify-center">Acessar</button>
      </form>
    </div>
  );
}
