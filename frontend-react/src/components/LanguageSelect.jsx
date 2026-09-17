import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../lib/api.js";

// a lista é fixa (vem de app/languages.py) — busca uma vez por sessão e
// compartilha entre todas as telas que montam o select
let _cache = null;
let _pending = null;

function loadLanguages() {
  if (_cache) return Promise.resolve(_cache);
  if (!_pending) {
    _pending = adminApi
      .languages()
      .then((d) => {
        _cache = d.languages || [];
        return _cache;
      })
      .catch(() => []);
  }
  return _pending;
}

export function LanguageSelect({ value, onChange, class: cls }) {
  const [options, setOptions] = useState(_cache || []);

  useEffect(() => {
    if (!_cache) loadLanguages().then(setOptions);
  }, []);

  return (
    <select
      value={value || ""}
      onChange={(e) => onChange(e.currentTarget.value || null)}
      class={cls || "bg-[#081019] border border-border rounded px-2 py-1.5 text-xs text-text"}
    >
      <option value="">sem idioma</option>
      {options.map((o) => (
        <option value={o.code}>{o.label}</option>
      ))}
    </select>
  );
}
