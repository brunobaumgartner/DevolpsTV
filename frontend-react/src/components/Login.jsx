import { useState } from "preact/hooks";
import { adminApi } from "../lib/api.js";

// login obrigatório pra qualquer coisa no site — substitui o antigo
// "cole seu token" (TokenGate). Serve tanto pra conta "user" (só a lista)
// quanto "admin" (lista + painel) — o /admin/me decide o que cada um vê.
export function Login({ onOk }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await adminApi.login(u, p);
      onOk();
    } catch {
      setErr("Usuário ou senha inválidos.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="min-h-screen grid place-items-center p-6">
      <form onSubmit={submit} class="w-full max-w-sm">
        <h1 class="text-accent font-display font-bold uppercase tracking-widest text-lg mb-1 drop-shadow-[0_0_10px_rgba(0,217,255,.5)]">
          DevolpsTV
        </h1>
        <p class="text-sm text-muted mb-4">Entra com seu usuário e senha pra acessar.</p>
        <input
          value={u}
          onInput={(e) => setU(e.currentTarget.value)}
          placeholder="usuário"
          autofocus
          class="w-full bg-[#081019] border border-border rounded px-3 py-2 text-sm mb-2"
        />
        <input
          type="password"
          value={p}
          onInput={(e) => setP(e.currentTarget.value)}
          placeholder="senha"
          class="w-full bg-[#081019] border border-border rounded px-3 py-2 text-sm"
        />
        {err && <p class="text-danger text-xs mt-2">{err}</p>}
        <button class="btn mt-3 w-full justify-center" disabled={busy}>
          {busy ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}
