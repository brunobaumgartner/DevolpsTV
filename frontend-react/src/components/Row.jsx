import { useRef, useEffect, useState, useCallback } from "preact/hooks";

// fileira horizontal com setas ‹ ›. Só chama load() (1 request) quando entra
// na viewport (IntersectionObserver).
export function Row({ title, load, renderItem, onSeeAll }) {
  const wrapRef = useRef(null);
  const scrollRef = useRef(null);
  const [seen, setSeen] = useState(false);
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(false);
  const [nav, setNav] = useState({ left: false, right: false });

  // lazy: observa o wrapper
  useEffect(() => {
    if (seen || !wrapRef.current) return;
    const io = new IntersectionObserver(
      (e) => e.some((x) => x.isIntersecting) && (setSeen(true), io.disconnect()),
      { rootMargin: "300px" }
    );
    io.observe(wrapRef.current);
    return () => io.disconnect();
  }, [seen]);

  useEffect(() => {
    if (!seen) return;
    let alive = true;
    load()
      .then((d) => alive && setItems(d))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, [seen]);

  const updateNav = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setNav({ left: el.scrollLeft > 8, right: el.scrollLeft < max - 8 });
  }, []);

  useEffect(() => {
    updateNav();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateNav, { passive: true });
    window.addEventListener("resize", updateNav);
    return () => {
      el.removeEventListener("scroll", updateNav);
      window.removeEventListener("resize", updateNav);
    };
  }, [items, updateNav]);

  const scrollBy = (dir) => {
    const el = scrollRef.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: "smooth" });
  };

  if (seen && !err && items && items.length === 0) return null;

  return (
    <section ref={wrapRef} class="py-3 group/row">
      <div class="flex items-baseline gap-3 px-4 md:px-8 mb-2">
        <h2 class="text-[13px] uppercase tracking-wide text-muted">{title}</h2>
        {onSeeAll && (
          <button onClick={onSeeAll} class="text-[11px] text-accent/70 hover:text-accent">
            ver tudo →
          </button>
        )}
      </div>

      <div class="relative">
        {nav.left && (
          <button
            aria-label="anterior"
            onClick={() => scrollBy(-1)}
            class="flex absolute left-0 top-0 bottom-0 z-10 w-9 md:w-11 items-center justify-center
                   bg-gradient-to-r from-bg via-bg/80 to-transparent text-accent text-3xl
                   opacity-80 hover:opacity-100 transition-opacity"
          >
            ‹
          </button>
        )}
        {nav.right && (
          <button
            aria-label="próximo"
            onClick={() => scrollBy(1)}
            class="flex absolute right-0 top-0 bottom-0 z-10 w-9 md:w-11 items-center justify-center
                   bg-gradient-to-l from-bg via-bg/80 to-transparent text-accent text-3xl
                   opacity-80 hover:opacity-100 transition-opacity"
          >
            ›
          </button>
        )}

        <div ref={scrollRef} class="row-scroll">
          {!items && !err &&
            Array.from({ length: 8 }).map(() => (
              <div class="card-poster animate-pulse !border-border/40" />
            ))}
          {err && <div class="text-[12px] text-muted px-1">falhou ao carregar</div>}
          {items && items.map((it) => renderItem(it))}
        </div>
      </div>
    </section>
  );
}
