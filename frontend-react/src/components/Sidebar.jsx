import { useState, useEffect } from "preact/hooks";
import { Link, useLocation, navigate } from "../lib/router.jsx";
import { adminApi } from "../lib/api.js";

const NAV = [
  ["/", "Início", "▚"],
  ["/tv", "TV ao vivo", "📡"],
  ["/filmes", "Filmes", "🎬"],
  ["/series", "Séries", "📺"],
  ["/animes", "Anime", "✦"],
];

export function Sidebar({ isAdmin, onLogout }) {
  const { path } = useLocation();
  const [open, setOpen] = useState(false);

  // fecha o drawer sempre que a rota muda (uso no mobile)
  useEffect(() => setOpen(false), [path]);

  const item = (href, label, icon, exact = true) => (
    <Link
      href={href}
      class={
        "flex items-center gap-3 rounded-md px-3 py-2.5 text-[15px] transition-colors " +
        (exact && path === href ? "bg-card text-accent" : "text-muted hover:text-text hover:bg-card/60")
      }
    >
      <span class="w-5 text-center text-sm">{icon}</span>
      <span>{label}</span>
    </Link>
  );

  return (
    <>
      {/* barra fina no topo — SÓ mobile, só pra abrir o menu */}
      <div class="md:hidden sticky top-0 z-40 flex items-center gap-3 h-12 px-3 bg-bg/95 backdrop-blur border-b border-border">
        <button onClick={() => setOpen(true)} class="text-accent text-xl leading-none" aria-label="Menu">
          ☰
        </button>
        <Link href="/" class="font-display font-bold tracking-widest uppercase text-accent text-[13px]">
          DevolpsTV
        </Link>
      </div>

      {/* backdrop do drawer (mobile) */}
      {open && <div class="md:hidden fixed inset-0 z-40 bg-black/60" onClick={() => setOpen(false)} />}

      <aside
        class={
          "fixed top-0 left-0 z-50 h-screen w-[210px] flex flex-col bg-bg border-r border-border " +
          "transition-transform duration-200 md:translate-x-0 " +
          (open ? "translate-x-0" : "-translate-x-full")
        }
      >
        <Link
          href="/"
          class="font-display font-bold tracking-widest uppercase text-accent text-[15px] px-4 py-4 drop-shadow-[0_0_10px_rgba(0,217,255,.5)]"
        >
          DevolpsTV
        </Link>
        <nav class="flex-1 flex flex-col gap-1 px-2 overflow-y-auto no-scrollbar">
          {NAV.map(([h, l, i]) => item(h, l, i))}
        </nav>
        <div class="px-2 py-3 border-t border-border flex flex-col gap-1">
          {item("/filmes", "Buscar", "🔍", false)}
          {isAdmin && item("/admin", "Admin", "⚙", false)}
          <button
            onClick={async () => {
              await adminApi.logout();
              onLogout?.();
              navigate("/");
            }}
            class="flex items-center gap-3 rounded-md px-3 py-2.5 text-[15px] text-muted hover:text-danger hover:bg-card/60 transition-colors"
          >
            <span class="w-5 text-center text-sm">⏻</span>
            <span>Sair</span>
          </button>
        </div>
      </aside>
    </>
  );
}
