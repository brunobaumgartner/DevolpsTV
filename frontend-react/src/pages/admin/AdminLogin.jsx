import { useState } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

export function AdminLogin({ onOk }) {
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
    <div class="min-h-[60vh] grid place-items-center p-6">
      <form onSubmit={submit} class="w-full max-w-sm">
        <h1 class="text-accent font-display font-bold uppercase tracking-widest text-lg mb-4">DevolpsTV — admin</h1>
        <input
          value={u}
          onInput={(e) => setU(e.currentTarget.value)}
          placeholder="usuário"
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
          Entrar
        </button>
      </form>
    </div>
  );
}
