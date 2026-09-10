import { useRef, useEffect, useState } from "preact/hooks";

// fileira horizontal. Só chama `load()` (1 request) quando entra na viewport.
export function Row({ title, load, renderItem, onSeeAll }) {
  const ref = useRef(null);
  const [seen, setSeen] = useState(false);
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (seen || !ref.current) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: "300px" }
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, [seen]);

  useEffect(() => {
    if (!seen) return;
    let alive = true;
    load()
      .then((data) => alive && setItems(data))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, [seen]);

  // fileira some se não tem nada
  if (seen && !err && items && items.length === 0) return null;

  return (
    <section ref={ref} class="py-3">
      <div class="flex items-baseline gap-3 px-4 md:px-8 mb-2">
        <h2 class="text-[13px] uppercase tracking-wide text-muted">{title}</h2>
        {onSeeAll && (
          <button onClick={onSeeAll} class="text-[11px] text-accent/70 hover:text-accent">
            ver tudo →
          </button>
        )}
      </div>
      <div class="row-scroll">
        {!items && !err &&
          Array.from({ length: 8 }).map(() => (
            <div class="card-poster animate-pulse !border-border/40" />
          ))}
        {err && <div class="text-[12px] text-muted px-1">falhou ao carregar</div>}
        {items && items.map((it) => renderItem(it))}
      </div>
    </section>
  );
}
