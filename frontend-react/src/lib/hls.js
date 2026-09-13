import { getToken } from "./api.js";

// carrega hls.js só quando precisa (fora do bundle inicial)
let _Hls = null;

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
    if (retries < DIRECT_RETRY_ATTEMPTS) {
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
  if (video) video.onerror = null;
  video?.removeAttribute?.("src");
}
