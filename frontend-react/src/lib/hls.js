import { getToken } from "./api.js";

// carrega hls.js/mpegts.js só quando precisa (fora do bundle inicial)
let _Hls = null;
let _Mpegts = null;

// alguns provedores (Pluto) servem o manifesto com CORS restrito -> passa
// pelo nosso proxy (só o manifesto; os segmentos vão direto do CDN).
function viaProxy(url) {
  const t = getToken();
  return t ? `/iptv/p/${encodeURIComponent(t)}/hls?url=${encodeURIComponent(url)}` : url;
}

// "mixed content": página https + link http do provedor -> o navegador tenta
// upgrade automático pra https, e a origem real (depois do redirect do
// provedor pra um IP direto) não tem certificado válido -> ERR_CONNECTION_RESET
// (achado real em 2026-09-11, via log do Chrome). Só nesse caso específico
// passa pelo nosso proxy de mídia; link https ou página http não precisam.
function viaMediaProxyIfNeeded(url) {
  if (location.protocol !== "https:" || !/^http:\/\//i.test(url)) return url;
  const t = getToken();
  return t ? `/iptv/p/${encodeURIComponent(t)}/media?url=${encodeURIComponent(url)}` : url;
}

// .ts cru (transport stream ao vivo, sem manifesto .m3u8) precisa ser lido
// byte a byte em JavaScript (mpegts.js) pra virar algo que o <video> entenda
// -- isso exige ler a resposta entre origens, o que os provedores quase nunca
// autorizam via CORS. Por isso sempre passa pelo NOSSO domínio (mesma origem
// da página, então CORS nem entra em jogo), igual o .m3u8 já fazia -- não dá
// pra condicionar a "só se https" como o mp4 faz.
function viaMediaProxyAlways(url) {
  const t = getToken();
  if (!t) return url;
  // absoluta, não relativa: o mpegts.js busca dados de dentro de um Web
  // Worker (enableWorker), e o worker (rodando a partir de um blob: URL)
  // não consegue resolver caminho relativo -- "Failed to parse URL from
  // /iptv/p/...". Achado em 2026-09-13 direto no console do navegador.
  return `${location.origin}/iptv/p/${encodeURIComponent(t)}/media?url=${encodeURIComponent(url)}`;
}

// Quanto tempo esperar por QUALQUER dado do link antes de desistir dele.
// Achado em 2026-09-13 inspecionando o player no navegador: link "pendurado"
// (TCP aceito mas nenhum byte chega) deixa o <video> em networkState=LOADING
// e readyState=0 pra SEMPRE, sem disparar onerror nem erro fatal do hls.js --
// como o fallback de mirror só era acionado por erro, o player ficava preso
// no primeiro link ruim e nunca tentava os outros. Era isso que fazia
// "nenhum filme/canal funcionar", não os links em si.
const LOAD_TIMEOUT_MS = 12000;

// quantas vezes recarrega o MESMO link antes de passar pro próximo mirror --
// antes de existir fallback automático, o navegador tinha esse tempo pra
// tentar sozinho (usuário relatou "demorava 5-10s mas abria").
const DIRECT_RETRY_ATTEMPTS = 2;
const DIRECT_RETRY_DELAY_MS = 5000;

// garante que o fallback de mirror aconteça no máximo 1x por link, venha de
// onde vier (onerror, erro fatal do hls.js ou watchdog de tempo)
function onceFatal(video, onFatal) {
  let done = false;
  return () => {
    if (done) return;
    done = true;
    clearLoadWatchdog(video);
    onFatal?.();
  };
}

function clearLoadWatchdog(video) {
  if (video?._loadWatchdog) {
    clearTimeout(video._loadWatchdog);
    video._loadWatchdog = null;
  }
  if (video?._loadWatchdogCleanup) {
    video._loadWatchdogCleanup();
    video._loadWatchdogCleanup = null;
  }
}

function startLoadWatchdog(video, fatalOnce) {
  clearLoadWatchdog(video);
  // qualquer sinal de que o vídeo REALMENTE começou a chegar cancela o
  // watchdog (readyState >= HAVE_CURRENT_DATA ou começou a tocar)
  const ok = () => clearLoadWatchdog(video);
  video.addEventListener("loadeddata", ok);
  video.addEventListener("canplay", ok);
  video.addEventListener("playing", ok);
  video._loadWatchdogCleanup = () => {
    video.removeEventListener("loadeddata", ok);
    video.removeEventListener("canplay", ok);
    video.removeEventListener("playing", ok);
  };
  video._loadWatchdog = setTimeout(() => {
    if (video.readyState < 2) fatalOnce();
  }, LOAD_TIMEOUT_MS);
}

function attachDirectRetry(video, fatalOnce) {
  let retries = 0;
  video.onerror = () => {
    // MEDIA_ERR_NETWORK (2) é transitório -> vale insistir no mesmo link.
    // MEDIA_ERR_DECODE (3) e MEDIA_ERR_SRC_NOT_SUPPORTED (4) são definitivos:
    // o servidor devolveu HTML de erro/403 ou algo que não é vídeo, e
    // retentar só queima tempo. Achado em 2026-09-13 instrumentando o player
    // no navegador: um mirror morto dava erro 4 em ~1s, mas o retry cego
    // segurava 10s+ nele enquanto um mirror BOM (que abre em 2,3s) esperava
    // atrás na fila -- era isso que fazia parecer que "nada funciona".
    const code = video.error?.code;
    const vaisTentarDeNovo = code === 2 && retries < DIRECT_RETRY_ATTEMPTS;
    if (vaisTentarDeNovo) {
      retries += 1;
      setTimeout(() => {
        if (video.isConnected) {
          video.load();
          startLoadWatchdog(video, fatalOnce); // cada retry ganha prazo próprio
        }
      }, DIRECT_RETRY_DELAY_MS);
      return;
    }
    fatalOnce();
  };
}

export async function attachHls(video, url, onFatal) {
  detachHls(video);
  const fatalOnce = onceFatal(video, onFatal);
  startLoadWatchdog(video, fatalOnce);

  const isM3u8 = /\.m3u8(\?|$)/i.test(url) || /\/hls\?url=/.test(url);
  // achado em 2026-09-13: canal com link .ts cru (sem .m3u8) tocava 0% das
  // vezes mesmo quando o servidor confirmava o link saudável (200, bytes de
  // vídeo de verdade) -- o <video src="...ts"> do Chrome/Firefox não sabe
  // decodificar transport stream cru, só m3u8/mp4. Precisa do mpegts.js pra
  // remuxar em algo que o MSE aceite, igual o hls.js faz pro .m3u8. Muita
  // fonte desse tipo (padrão Xtream Codes) nem usa extensão ".ts" na URL --
  // é só um caminho numérico opaco (ex: ".../192324/192324/4404") -- por
  // isso a checagem é "não é m3u8 nem extensão de arquivo direto conhecida",
  // não só "termina em .ts". Arquivo de VOD (filme/série) sempre tem
  // extensão reconhecida, então continua indo pelo <video src> normal.
  const hasDirectFileExt = /\.(mp4|mkv|avi|mov|webm|m4v)(\?|$)/i.test(url);
  const isRawTs = !isM3u8 && !hasDirectFileExt;

  if (isRawTs) {
    if (!_Mpegts) {
      // mpegts.js é um pacote CJS (`module.exports = ...`, sem export
      // nomeado "default") -- o Rollup sintetiza um ".default" ao empacotar,
      // mas no build de produção, pra esse chunk carregado por import()
      // dinâmico, ele expôs o valor real sob uma propriedade minificada
      // diferente (ex: "m") em vez de "default". Pegar o 1º valor do módulo
      // funciona nos dois casos, sem depender do nome exato.
      const mod = await import("mpegts.js");
      _Mpegts = mod.default ?? Object.values(mod)[0];
    }
    if (_Mpegts.isSupported()) {
      const player = _Mpegts.createPlayer(
        { type: "mpegts", isLive: true, url: viaMediaProxyAlways(url) },
        { enableWorker: true }
      );
      player.attachMediaElement(video);
      player.on(_Mpegts.Events.ERROR, () => fatalOnce());
      player.load();
      player.play().catch(() => {});
      video._mpegts = player;
      return;
    }
  }

  if (isM3u8) {
    // Preferimos SEMPRE o hls.js quando há MSE (Chrome/Firefox/Android/desktop).
    // O canPlayType("...mpegurl") de alguns Chromium retorna "maybe" mas o
    // navegador não toca HLS de fato -> erro 4. Só caímos no player nativo
    // quando NÃO há MSE (Safari/iOS de verdade).
    if (!_Hls) _Hls = (await import("hls.js")).default;
    if (_Hls.isSupported()) {
      const hls = new _Hls({ maxBufferLength: 20 });
      hls.loadSource(viaProxy(url));
      hls.attachMedia(video);
      hls.on(_Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) fatalOnce();
      });
      video._hls = hls;
      return;
    }
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = viaProxy(url); // Safari/iOS toca HLS nativo
      attachDirectRetry(video, fatalOnce);
      return;
    }
  }
  // arquivo direto (.mp4/.ts) ou sem suporte a MSE
  video.src = viaMediaProxyIfNeeded(url);
  attachDirectRetry(video, fatalOnce);
}

export function detachHls(video) {
  clearLoadWatchdog(video);
  if (video?._hls) {
    try {
      video._hls.destroy();
    } catch {}
    video._hls = null;
  }
  if (video?._mpegts) {
    try {
      video._mpegts.destroy();
    } catch {}
    video._mpegts = null;
  }
  if (video) video.onerror = null;
  video?.removeAttribute?.("src");
}
