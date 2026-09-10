import { useState, useEffect } from "preact/hooks";
import { Link, useLocation } from "../lib/router.jsx";

const NAV = [
  ["/", "Início"],
  ["/tv", "TV ao vivo"],
  ["/filmes", "Filmes"],
  ["/series", "Séries"],
  ["/animes", "Anime"],
];

export function Header({ isAdmin }) {
  const { path } = useLocation();
  const [solid, setSolid] = useState(false);

  useEffect(() => {
    const on = () => setSolid(window.scrollY > 12);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <header
      class={
        "sticky top-0 z-40 flex items-center gap-4 px-4 md:px-8 py-3 transition-colors " +
        (solid ? "bg-bg/95 backdrop-blur border-b border-border" : "bg-bg/80 backdrop-blur-sm")
      }
    >
      <Link href="/" class="font-display font-bold tracking-widest uppercase text-accent text-[15px] drop-shadow-[0_0_10px_rgba(0,217,255,.5)]">
        DevolpsTV
      </Link>
      <nav class="hidden md:flex items-center gap-4 text-[13px]">
        {NAV.map(([href, label]) => (
          <Link
            href={href}
            class={
              (path === href ? "text-accent" : "text-muted hover:text-text") + " transition-colors"
            }
          >
            {label}
          </Link>
        ))}
      </nav>
      <div class="ml-auto flex items-center gap-3 text-[13px]">
        {isAdmin && (
          <Link href="/admin" class="text-muted hover:text-accent">
            admin
          </Link>
        )}
      </div>
    </header>
  );
}
