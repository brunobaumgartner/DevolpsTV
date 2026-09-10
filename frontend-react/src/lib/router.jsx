import { useState, useEffect, useCallback } from "preact/hooks";

// --- roteador hash minúsculo (sem dependência) -------------------------------
// URL fica /iptv/#/filmes?q=batman  -> path "/filmes", query {q:"batman"}

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path, qs = ""] = raw.split("?");
  const query = Object.fromEntries(new URLSearchParams(qs));
  return { path: path || "/", query };
}

export function navigate(to, { replace = false } = {}) {
  const hash = "#" + (to.startsWith("/") ? to : "/" + to);
  if (replace) window.location.replace(hash);
  else window.location.hash = hash;
}

export function useLocation() {
  const [loc, setLoc] = useState(parseHash);
  useEffect(() => {
    const on = () => setLoc(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return loc;
}

// combina "/titulo/:id" com "/titulo/42" -> { id: "42" } ; null se não bate
function matchPattern(pattern, path) {
  const pp = pattern.split("/").filter(Boolean);
  const xp = path.split("/").filter(Boolean);
  if (pattern.endsWith("/*")) {
    // prefixo: "/admin/*"
    const base = pp.slice(0, -1);
    if (xp.length < base.length) return null;
    for (let i = 0; i < base.length; i++) if (base[i] !== xp[i]) return null;
    return {};
  }
  if (pp.length !== xp.length) return null;
  const params = {};
  for (let i = 0; i < pp.length; i++) {
    if (pp[i].startsWith(":")) params[pp[i].slice(1)] = decodeURIComponent(xp[i]);
    else if (pp[i] !== xp[i]) return null;
  }
  return params;
}

// <Route path="/titulo/:id" component={TitleDetail} />
export function Route({ path, component: Comp, render }) {
  const { path: current, query } = useLocation();
  const params = matchPattern(path, current);
  if (!params) return null;
  if (render) return render({ params, query });
  return <Comp params={params} query={query} />;
}

// primeiro Route que casar; fallback opcional
export function Switch({ children, fallback = null }) {
  const { path: current } = useLocation();
  const arr = Array.isArray(children) ? children.flat() : [children];
  for (const child of arr) {
    if (child?.props?.path && matchPattern(child.props.path, current)) return child;
  }
  return fallback;
}

export function Link({ href, class: cls, className, children, ...rest }) {
  const onClick = useCallback(
    (e) => {
      e.preventDefault();
      navigate(href);
    },
    [href]
  );
  return (
    <a href={"#" + href} class={cls || className} onClick={onClick} {...rest}>
      {children}
    </a>
  );
}
