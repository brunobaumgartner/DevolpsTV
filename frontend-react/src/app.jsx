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
