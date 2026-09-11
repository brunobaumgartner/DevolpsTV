import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";
import { ChipBar } from "../../components/ChipBar.jsx";

const PAGE = 30;
const inp = "bg-[#081019] border border-border rounded px-2 py-1 text-xs";

// paginado e filtrado, igual ao Catálogo de VOD — 1170+ canais de uma vez
// só numa lista seria o mesmo problema de peso.
export function AdminChannelCatalog() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [cats, setCats] = useState([]);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    adminApi.channelCategories().then((d) => setCats(d.categories || [])).catch(() => {});
  }, []);

  function load(p = page) {
    setLoading(true);
    const params = { limit: PAGE, offset: p * PAGE };
    if (cat) params.category = cat;
    if (q) params.q = q;
    adminApi
      .channelList(params)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }

  useEffect(() => {
    setPage(0);
    load(0);
  }, [q, cat]);

  const total = data?.count || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const go = (p) => {
    setPage(p);
    load(p);
    window.scrollTo({ top: 0 });
  };
  const reload = () => load(page);

  return (
    <div class="p-4 md:p-8">
      <h1 class="text-lg text-accent font-display mb-4">Canais</h1>

      <input
        value={q}
        onInput={(e) => setQ(e.currentTarget.value)}
        placeholder="Buscar canal…"
        class="w-full bg-[#081019] border border-border rounded px-3 py-1.5 text-sm mb-2"
      />

      <ChipBar
        items={cats.map((c) => ({ value: c.category, label: `${c.category} (${c.count})` }))}
        active={cat}
        onSelect={setCat}
      />

      <div class="text-[11px] text-muted mb-2">{total} canal(is)</div>

      {loading && !data && <div class="text-muted text-sm py-10">Carregando…</div>}
      {data && data.channels.length === 0 && <div class="text-muted text-sm py-10">Nada encontrado.</div>}

      <div class="space-y-2">
        {data?.channels.map((c) => (
          <ChannelRow c={c} open={openId === c.id} onToggle={() => setOpenId(openId === c.id ? null : c.id)} onChange={reload} />
        ))}
      </div>

      {pages > 1 && (
        <div class="flex items-center justify-center gap-4 mt-6 text-sm">
          <button class="btn-ghost rounded px-3 py-1.5 border border-border disabled:opacity-40" disabled={page <= 0} onClick={() => go(page - 1)}>
            ← Anterior
          </button>
          <span class="text-muted">
            {page + 1} / {pages}
          </span>
          <button class="btn-ghost rounded px-3 py-1.5 border border-border disabled:opacity-40" disabled={page + 1 >= pages} onClick={() => go(page + 1)}>
            Próxima →
          </button>
        </div>
      )}
    </div>
  );
}

function ChannelRow({ c, open, onToggle, onChange }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (open && !detail) {
      setLoading(true);
      adminApi.channelDetail(c.id).then((d) => {
        setDetail(d);
        setForm({ name: d.name, category: d.category || "", logo_url: d.logo_url || "", is_broadcast_tv: d.is_broadcast_tv });
        setLoading(false);
      });
    }
  }, [open]);

  const refreshDetail = () => adminApi.channelDetail(c.id).then(setDetail);

  return (
    <div class="border border-border rounded-md bg-card">
      <button class="w-full flex items-center gap-2 p-3 text-left" onClick={onToggle}>
        <span class="text-muted text-xs w-4">{open ? "▾" : "▸"}</span>
        {c.logo_url ? (
          <img src={c.logo_url} class="w-10 h-7 object-contain bg-card-hover rounded shrink-0" />
        ) : (
          <div class="w-10 h-7 rounded bg-card-hover shrink-0" />
        )}
        <strong class="text-sm flex-1 truncate">{c.name}</strong>
        <span class="text-[11px] text-muted shrink-0">
          {c.category || "sem categoria"} · {c.stream_count} link(s){c.is_broadcast_tv ? " · TV aberta" : ""}
          {!c.is_active ? " · inativo" : ""}
        </span>
        <span
          class="text-[11px] text-danger border border-danger rounded px-2 py-0.5 shrink-0"
          onClick={async (e) => {
            e.stopPropagation();
            if (!confirm(`Excluir o canal "${c.name}" e todos os seus links?`)) return;
            await adminApi.delChannel(c.id);
            onChange();
          }}
        >
          excluir
        </span>
      </button>

      {open && (
        <div class="px-3 pb-3 border-t border-border">
          {loading && <div class="text-muted text-xs py-2">Carregando…</div>}
          {form && (
            <div class="grid grid-cols-2 gap-2 py-2">
              <input class={inp} placeholder="Nome" value={form.name} onInput={(e) => setForm({ ...form, name: e.currentTarget.value })} />
              <input class={inp} placeholder="Categoria" value={form.category} onInput={(e) => setForm({ ...form, category: e.currentTarget.value })} />
              <input class={inp + " col-span-2"} placeholder="Logo URL" value={form.logo_url} onInput={(e) => setForm({ ...form, logo_url: e.currentTarget.value })} />
              <label class="text-xs text-muted flex items-center gap-2">
                <input type="checkbox" checked={form.is_broadcast_tv} onChange={(e) => setForm({ ...form, is_broadcast_tv: e.currentTarget.checked })} />
                TV aberta
              </label>
              <button
                class="btn-ghost rounded px-2 py-1 border border-border text-xs justify-self-start"
                onClick={async () => {
                  await adminApi.updateChannel(c.id, {
                    name: form.name,
                    category: form.category || null,
                    logo_url: form.logo_url || null,
                    is_broadcast_tv: form.is_broadcast_tv,
                  });
                  setSaved(true);
                  setTimeout(() => setSaved(false), 1500);
                  onChange();
                }}
              >
                {saved ? "✓ salvo" : "salvar"}
              </button>
            </div>
          )}

          <p class="text-[11px] text-muted uppercase tracking-wide mt-2 mb-1">Links (mirrors)</p>
          {detail?.streams.map((s) => (
            <StreamRow s={s} onChange={refreshDetail} />
          ))}
          <AddStream tvgId={c.tvg_id} onChange={refreshDetail} />
        </div>
      )}
    </div>
  );
}

function StreamRow({ s, onChange }) {
  const [url, setUrl] = useState(s.url);
  const [saved, setSaved] = useState(false);
  return (
    <div class="flex items-center gap-2 py-1.5 border-t border-border/60 text-xs">
      <span
        class={
          "w-2 h-2 rounded-full shrink-0 " +
          (s.is_healthy === true ? "bg-ok" : s.is_healthy === false ? "bg-danger" : "bg-muted")
        }
        title={s.is_healthy === true ? "saudável" : s.is_healthy === false ? "com falha" : "não testado"}
      />
      <span class="w-20 shrink-0 text-muted truncate">{s.lang_label || "Português"}</span>
      <input class="flex-1 bg-[#081019] border border-border rounded px-2 py-1" value={url} onInput={(e) => setUrl(e.currentTarget.value)} />
      <button
        class="btn-ghost rounded px-2 py-1 border border-border"
        onClick={async () => {
          await adminApi.updateStream(s.id, { url: url.trim() });
          setSaved(true);
          setTimeout(() => setSaved(false), 1500);
        }}
      >
        {saved ? "✓" : "salvar"}
      </button>
      <button
        class="text-danger"
        onClick={async () => {
          await adminApi.delStream(s.id);
          onChange();
        }}
      >
        ×
      </button>
    </div>
  );
}

function AddStream({ tvgId, onChange }) {
  return (
    <form
      class="flex gap-1.5 mt-2"
      onSubmit={async (e) => {
        e.preventDefault();
        const el = e.currentTarget.elements.u;
        if (!el.value.trim()) return;
        await adminApi.addChannel({ tvg_id: tvgId, name: "", stream_url: el.value.trim() });
        e.currentTarget.reset();
        onChange();
      }}
    >
      <input name="u" placeholder="Novo link (mirror)" class="flex-1 bg-[#081019] border border-border rounded px-2 py-1 text-xs" />
      <button class="btn-ghost rounded px-2 py-1 border border-border text-xs">+ link</button>
    </form>
  );
}
