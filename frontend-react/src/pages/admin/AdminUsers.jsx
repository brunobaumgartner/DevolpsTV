import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

function Panel({ title, children }) {
  return (
    <section class="rounded-md border border-border bg-card p-4 mb-4">
      <h2 class="text-[12px] uppercase tracking-wide text-muted mb-3">{title}</h2>
      {children}
    </section>
  );
}

export function AdminUsers() {
  const [users, setUsers] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", role: "user" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => adminApi.users().then((r) => setUsers(r.users)).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await adminApi.createUser(form);
      setForm({ username: "", password: "", role: "user" });
      load();
    } catch (e2) {
      setErr(e2.message || "Falha ao criar.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(u) {
    if (!confirm(`Apagar o usuário "${u.username}"? Ele perde o acesso imediatamente.`)) return;
    await adminApi.deleteUser(u.id).catch((e) => alert(e.message));
    load();
  }

  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <h1 class="text-lg text-accent font-display mb-4">Usuários</h1>

      <Panel title="Novo usuário">
        <form onSubmit={submit} class="flex flex-wrap items-end gap-3">
          <div>
            <label class="block text-[11px] text-muted mb-1">Usuário</label>
            <input
              value={form.username}
              onInput={(e) => setForm({ ...form, username: e.currentTarget.value })}
              class="bg-[#081019] border border-border rounded px-3 py-1.5 text-sm w-40"
              required
            />
          </div>
          <div>
            <label class="block text-[11px] text-muted mb-1">Senha</label>
            <input
              type="text"
              value={form.password}
              onInput={(e) => setForm({ ...form, password: e.currentTarget.value })}
              class="bg-[#081019] border border-border rounded px-3 py-1.5 text-sm w-40"
              required
            />
          </div>
          <div>
            <label class="block text-[11px] text-muted mb-1">Papel</label>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.currentTarget.value })}
              class="bg-[#081019] border border-border rounded px-2 py-1.5 text-sm"
            >
              <option value="user">Usuário (só a lista)</option>
              <option value="admin">Admin (lista + painel)</option>
            </select>
          </div>
          <button class="btn" disabled={busy}>
            Criar
          </button>
          {err && <span class="text-danger text-xs">{err}</span>}
        </form>
      </Panel>

      <Panel title={`Contas (${users?.length ?? "…"})`}>
        {!users ? (
          <div class="text-muted text-sm">Carregando…</div>
        ) : (
          <div class="space-y-2">
            {users.map((u) => (
              <div class="flex items-center gap-3 rounded border border-border p-3 text-sm flex-wrap">
                <span class="font-medium">{u.username}</span>
                <span
                  class={
                    "text-[11px] px-1.5 py-0.5 rounded " +
                    (u.role === "admin" ? "bg-accent2/20 text-accent" : "bg-white/10 text-muted")
                  }
                >
                  {u.role === "admin" ? "admin" : "usuário"}
                </span>
                {u.token && <code class="text-[11px] text-muted">token: {u.token}</code>}
                <button class="ml-auto text-xs text-muted hover:text-danger" onClick={() => remove(u)}>
                  apagar
                </button>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
