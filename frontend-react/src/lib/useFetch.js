import { useState, useEffect, useRef } from "preact/hooks";

// cache em memória por chave + dedupe de requisições simultâneas.
// não é offline nem persistente — só evita rebaixar a mesma coisa ao
// navegar entre telas na mesma sessão.
const cache = new Map(); // key -> { data, ts }
const inflight = new Map(); // key -> Promise
const TTL = 60_000; // 1 min: depois disso revalida em background

export function invalidate(prefix = "") {
  for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k);
}

export function useFetch(key, fetcher, { enabled = true } = {}) {
  const [state, setState] = useState(() => {
    const hit = key && cache.get(key);
    return { data: hit?.data ?? null, error: null, loading: enabled && !hit };
  });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled || !key) return;
    let alive = true;

    const hit = cache.get(key);
    const fresh = hit && Date.now() - hit.ts < TTL;
    if (hit) setState({ data: hit.data, error: null, loading: false });
    if (fresh) return;

    let p = inflight.get(key);
    if (!p) {
      p = Promise.resolve()
        .then(() => fetcherRef.current())
        .then((data) => {
          cache.set(key, { data, ts: Date.now() });
          inflight.delete(key);
          return data;
        })
        .catch((e) => {
          inflight.delete(key);
          throw e;
        });
      inflight.set(key, p);
    }
    if (!hit) setState((s) => ({ ...s, loading: true }));
    p.then((data) => alive && setState({ data, error: null, loading: false })).catch(
      (error) => alive && setState((s) => ({ ...s, error, loading: false }))
    );

    return () => {
      alive = false;
    };
  }, [key, enabled]);

  return state;
}
