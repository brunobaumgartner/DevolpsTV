import { createContext } from "preact";
import { useContext, useRef, useState, useCallback, useEffect } from "preact/hooks";
import { api } from "../lib/api.js";
import { attachHls, detachHls } from "../lib/hls.js";

const PlayerCtx = createContext(null);
export const usePlayer = () => useContext(PlayerCtx);

export function PlayerProvider({ children }) {
  const videoRef = useRef(null);
  const [state, setState] = useState({ open: false, title: "", status: "", langs: [], lang: null, channel: null });
  const reqId = useRef(0);

  const playUrl = useCallback((url, title) => {
    const v = videoRef.current;
    if (!v) return;
    setState((s) => ({ ...s, open: true, title, status: `Reproduzindo: ${title}` }));
    attachHls(v, url, () => setState((s) => ({ ...s, status: `Falha ao reproduzir "${title}".` })));
    v.play?.().catch(() => {});
  }, []);

  const playChannel = useCallback(
    async (channel, lang) => {
      const my = ++reqId.current;
      const langs = channel.languages || [];
      const chosen = lang || (langs.find((g) => g.label === "Português") || langs[0])?.label || null;
      setState({
        open: true,
        title: channel.name,
        status: `Verificando "${channel.name}"${chosen && langs.length > 1 ? " (" + chosen + ")" : ""}...`,
        langs,
        lang: chosen,
        channel,
      });
      try {
        const { url } = await api.resolve(channel.tvg_id, langs.length > 1 ? chosen : null);
        if (my !== reqId.current) return;
        playUrl(url, channel.name);
        setState((s) => ({ ...s, langs, lang: chosen, channel }));
      } catch (e) {
        if (my !== reqId.current) return;
        setState((s) => ({ ...s, status: e.message || `"${channel.name}" indisponível agora.` }));
      }
    },
    [playUrl]
  );

  const close = useCallback(() => {
    detachHls(videoRef.current);
    setState({ open: false, title: "", status: "", langs: [], lang: null, channel: null });
  }, []);

  useEffect(() => () => detachHls(videoRef.current), []);

  return (
    <PlayerCtx.Provider value={{ playUrl, playChannel, close }}>
      <div
        class={
          "sticky top-0 z-20 bg-black transition-[height] duration-200 overflow-hidden " +
          (state.open ? "h-[38vw] max-h-[62vh] min-h-[200px]" : "h-0")
        }
      >
        <video ref={videoRef} class="h-full w-full bg-black" controls autoplay playsinline />
      </div>
      {state.open && (
        <div class="px-4 md:px-8 py-2 border-b border-border">
          <div class="flex items-center gap-3 flex-wrap">
            <span class="text-[12px] text-muted flex-1 min-w-[180px]">{state.status}</span>
            <button class="btn-ghost text-[11px] rounded px-2 py-1 border border-border" onClick={close}>
              fechar
            </button>
          </div>
          {state.langs.length > 1 && (
            <div class="flex items-center gap-1.5 flex-wrap mt-2">
              <span class="text-[11px] uppercase tracking-wide text-muted mr-1">Idioma:</span>
              {state.langs.map((g) => (
                <button
                  class={"chip " + (g.label === state.lang ? "active" : "")}
                  onClick={() => state.channel && playChannel(state.channel, g.label)}
                >
                  {g.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {children}
    </PlayerCtx.Provider>
  );
}
