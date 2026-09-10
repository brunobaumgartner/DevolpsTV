import { useState, useEffect } from "preact/hooks";
import { adminApi, setToken } from "./api.js";

const LS_TOKEN = "devolpstv:token";

// descobre o token de acesso:
//  - admin logado -> pega o 1º token da conta automaticamente
//  - senão -> token salvo no navegador (colado pelo usuário)
export function useSession() {
  const [s, setS] = useState({ ready: false, isAdmin: false, token: null });

  useEffect(() => {
    let alive = true;
    (async () => {
      let isAdmin = false;
      let token = null;
      try {
        await adminApi.me();
        isAdmin = true;
        const { tokens } = await adminApi.tokens();
        token = tokens?.[0]?.token || null;
      } catch {
        try {
          token = localStorage.getItem(LS_TOKEN);
        } catch {}
      }
      if (!alive) return;
      if (token) setToken(token);
      setS({ ready: true, isAdmin, token });
    })();
    return () => {
      alive = false;
    };
  }, []);

  return {
    ...s,
    saveToken(t) {
      try {
        localStorage.setItem(LS_TOKEN, t);
      } catch {}
      setToken(t);
      setS((p) => ({ ...p, token: t }));
    },
  };
}
