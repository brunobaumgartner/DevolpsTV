import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";
import { Link, useLocation, navigate } from "../../lib/router.jsx";
import { AdminLogin } from "./AdminLogin.jsx";
import { AdminDashboard } from "./AdminDashboard.jsx";
import { AdminGenres } from "./AdminGenres.jsx";
import { AdminCatalog } from "./AdminCatalog.jsx";

const TABS = [
  ["/admin", "Dashboard"],
  ["/admin/generos", "Gêneros"],
  ["/admin/cadastro", "Cadastro"],
];

export function AdminApp() {
  const { path } = useLocation();
  const [auth, setAuth] = useState("checking"); // checking | no | yes

  useEffect(() => {
    adminApi.me().then(
      () => setAuth("yes"),
      () => setAuth("no")
    );
  }, []);

  if (auth === "checking") return <div class="p-8 text-muted text-sm">…</div>;
  if (auth === "no" || path === "/admin/login") {
    return <AdminLogin onOk={() => { setAuth("yes"); navigate("/admin"); }} />;
  }

  const Page = path === "/admin/generos" ? AdminGenres : path === "/admin/cadastro" ? AdminCatalog : AdminDashboard;

  return (
    <div>
      <div class="flex items-center gap-4 px-4 md:px-8 py-3 border-b border-border text-sm">
        {TABS.map(([href, label]) => (
          <Link href={href} class={(path === href ? "text-accent" : "text-muted hover:text-text")}>
            {label}
          </Link>
        ))}
        <button
          class="ml-auto text-muted hover:text-danger text-xs"
          onClick={async () => {
            await adminApi.logout();
            setAuth("no");
          }}
        >
          sair
        </button>
      </div>
      <Page />
    </div>
  );
}
