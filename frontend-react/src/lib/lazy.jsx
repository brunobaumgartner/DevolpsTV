import { useState, useEffect } from "preact/hooks";

// carrega um módulo sob demanda (code-splitting) sem preact/compat.
// uso: const Admin = lazy(() => import("../pages/admin/AdminApp.jsx"), "AdminApp")
export function lazy(loader, exportName = "default") {
  return function LazyComponent(props) {
    const [Comp, setComp] = useState(null);
    useEffect(() => {
      let alive = true;
      loader().then((m) => alive && setComp(() => m[exportName] || m.default));
      return () => { alive = false; };
    }, []);
    if (!Comp) return <div class="p-8 text-muted text-sm">Carregando…</div>;
    return <Comp {...props} />;
  };
}
