import { useRef, useEffect, useState, useCallback } from "preact/hooks";

// barra horizontal de chips com setas ‹ › (mesmo padrão do Row.jsx).
// items: [{ value, label }]  ·  active: value selecionado  ·  onSelect(value|null)
export function ChipBar({ items, active, onSelect }) {
  const scrollRef = useRef(null);
  const [nav, setNav] = useState({ left: false, right: false });

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
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: "smooth" });
  };

  if (!items || items.length === 0) return null;

  return (
    <div class="relative px-4 md:px-8 py-3">
      {nav.left && (
        <button
          aria-label="anterior"
          onClick={() => scrollBy(-1)}
          class="flex absolute left-4 md:left-8 top-0 bottom-0 z-10 w-9 items-center justify-center
                 bg-gradient-to-r from-bg via-bg/85 to-transparent text-accent text-2xl
                 opacity-90 hover:opacity-100"
        >
          ‹
        </button>
      )}
      {nav.right && (
        <button
          aria-label="próximo"
          onClick={() => scrollBy(1)}
          class="flex absolute right-4 md:right-8 top-0 bottom-0 z-10 w-9 items-center justify-center
                 bg-gradient-to-l from-bg via-bg/85 to-transparent text-accent text-2xl
                 opacity-90 hover:opacity-100"
        >
          ›
        </button>
      )}

      <div ref={scrollRef} class="flex gap-2 overflow-x-auto no-scrollbar scroll-px-4">
        {items.map((it) => (
          <button
            class={"chip shrink-0 " + (active === it.value ? "active" : "")}
            onClick={() => onSelect(active === it.value ? null : it.value)}
          >
            {it.label}
          </button>
        ))}
      </div>
    </div>
  );
}
