import { useLocation, Link } from "../../lib/router.jsx";
import { AdminDashboard } from "./AdminDashboard.jsx";
import { AdminGenres } from "./AdminGenres.jsx";
import { AdminCadastroVod } from "./AdminCadastroVod.jsx";
import { AdminCadastroCanais } from "./AdminCadastroCanais.jsx";
import { AdminVodCatalog } from "./AdminVodCatalog.jsx";
import { AdminChannelCatalog } from "./AdminChannelCatalog.jsx";
import { AdminSystem } from "./AdminSystem.jsx";
import { AdminDb } from "./AdminDb.jsx";
import { AdminUsers } from "./AdminUsers.jsx";

const TABS = [
  ["/admin", "Dashboard"],
  ["/admin/generos", "Gêneros"],
  ["/admin/cadastro-vod", "Cadastrar VOD"],
  ["/admin/cadastro-canais", "Cadastrar Canais"],
  ["/admin/catalogo", "Catálogo"],
  ["/admin/canais", "Canais"],
  ["/admin/sistema", "Sistema"],
  ["/admin/banco", "Banco"],
  ["/admin/usuarios", "Usuários"],
];

// o login já aconteceu na entrada do site (App.jsx) — aqui só resta checar
// o PAPEL da conta: só "admin" pode ver o painel.
export function AdminApp({ role }) {
  const { path } = useLocation();

  if (role !== "admin") {
    return (
      <div class="p-8 text-sm text-muted">
        Essa conta não tem acesso ao painel de administração.{" "}
        <Link href="/" class="text-accent hover:underline">
          Voltar
        </Link>
      </div>
    );
  }

  const Page =
    path === "/admin/generos"
      ? AdminGenres
      : path === "/admin/cadastro-vod"
      ? AdminCadastroVod
      : path === "/admin/cadastro-canais"
      ? AdminCadastroCanais
      : path === "/admin/catalogo"
      ? AdminVodCatalog
      : path === "/admin/canais"
      ? AdminChannelCatalog
      : path === "/admin/sistema"
      ? AdminSystem
      : path === "/admin/banco"
      ? AdminDb
      : path === "/admin/usuarios"
      ? AdminUsers
      : AdminDashboard;

  return (
    <div>
      <div class="flex items-center gap-4 px-4 md:px-8 py-3 border-b border-border text-sm overflow-x-auto no-scrollbar">
        {TABS.map(([href, label]) => (
          <Link href={href} class={"shrink-0 " + (path === href ? "text-accent" : "text-muted hover:text-text")}>
            {label}
          </Link>
        ))}
      </div>
      <Page />
    </div>
  );
}
