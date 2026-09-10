import { useSession } from "./lib/session.js";
import { Switch, Route } from "./lib/router.jsx";
import { Header } from "./components/Header.jsx";
import { PlayerProvider } from "./components/Player.jsx";
import { TokenGate } from "./components/TokenGate.jsx";
import { Home } from "./pages/Home.jsx";
import { TitleDetail } from "./pages/TitleDetail.jsx";
import { Stub } from "./pages/Stub.jsx";

export function App() {
  const session = useSession();

  if (!session.ready) {
    return <div class="min-h-[100dvh] grid place-items-center text-muted text-sm">Carregando…</div>;
  }
  if (!session.token) {
    return <TokenGate onSave={session.saveToken} />;
  }

  return (
    <PlayerProvider>
      <Header isAdmin={session.isAdmin} />
      <main>
        <Switch fallback={<Stub />}>
          <Route path="/" component={Home} />
          <Route path="/titulo/:id" component={TitleDetail} />
          <Route path="/tv" component={Stub} />
          <Route path="/filmes" component={Stub} />
          <Route path="/series" component={Stub} />
          <Route path="/animes" component={Stub} />
          <Route path="/genero/:nome" component={Stub} />
          <Route path="/admin/*" component={Stub} />
        </Switch>
      </main>
    </PlayerProvider>
  );
}
