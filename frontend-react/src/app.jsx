import { useSession } from "./lib/session.js";
import { Switch, Route } from "./lib/router.jsx";
import { Header } from "./components/Header.jsx";
import { TokenGate } from "./components/TokenGate.jsx";
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
    return <div class="min-h-[100dvh] grid place-items-center text-muted text-sm">Carregando…</div>;
  }
  if (!session.token) {
    return <TokenGate onSave={session.saveToken} />;
  }

  return (
    <>
      <Header isAdmin={session.isAdmin} />
      <main>
        <Switch fallback={<Stub />}>
          <Route path="/" component={Home} />
          <Route path="/assistir/:tipo/:id" component={Watch} />
          <Route path="/tv" component={LiveTV} />
          <Route path="/filmes" render={() => <VodList mode="movie" />} />
          <Route path="/series" render={() => <VodList mode="series" />} />
          <Route path="/animes" render={() => <VodList mode="anime" />} />
          <Route path="/genero/:nome" render={({ params }) => <VodList mode="genre" params={params} />} />
          <Route path="/admin/*" component={AdminApp} />
        </Switch>
      </main>
    </>
  );
}
