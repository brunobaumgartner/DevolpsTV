import { useSession } from "./lib/session.js";
import { Switch, Route } from "./lib/router.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { Login } from "./components/Login.jsx";
import { lazy } from "./lib/lazy.jsx";
import { Home } from "./pages/Home.jsx";
import { Watch } from "./pages/Watch.jsx";
import { VodList } from "./pages/VodList.jsx";
import { LiveTV } from "./pages/LiveTV.jsx";
import { Stub } from "./pages/Stub.jsx";
import { onPlayHost, secureUrl } from "./lib/playHost.js";

const AdminApp = lazy(() => import("./pages/admin/AdminApp.jsx"), "AdminApp");

export function App() {
  const session = useSession();

  if (!session.ready) {
    return <div class="min-h-screen grid place-items-center text-muted text-sm">Carregando…</div>;
  }
  if (!session.authed) {
    return <Login onOk={session.refresh} />;
  }

  return (
    <>
      <Sidebar isAdmin={session.isAdmin} onLogout={session.refresh} />
      <main class="md:pl-[210px] min-h-screen">
        {onPlayHost() && (
          <div class="px-4 md:px-8 py-2 text-[12px] text-muted bg-card border-b border-border">
            Modo de reprodução (sem HTTPS).{" "}
            <a href={secureUrl()} class="text-accent underline">
              Voltar ao site seguro
            </a>
          </div>
        )}
        <Switch fallback={<Stub />}>
          <Route path="/" component={Home} />
          <Route path="/assistir/:tipo/:id" component={Watch} />
          <Route path="/tv" component={LiveTV} />
          <Route path="/filmes" render={() => <VodList mode="movie" />} />
          <Route path="/series" render={() => <VodList mode="series" />} />
          <Route path="/animes" render={() => <VodList mode="anime" />} />
          <Route path="/genero/:nome" render={({ params }) => <VodList mode="genre" params={params} />} />
          <Route path="/admin/*" render={() => <AdminApp role={session.role} />} />
        </Switch>
      </main>
    </>
  );
}
