import { getToken } from "./api.js";

// carrega hls.js só quando precisa (fora do bundle inicial)
let _Hls = null;

// alguns provedores (Pluto) servem o manifesto com CORS restrito -> passa
// pelo nosso proxy (só o manifesto; os segmentos vão direto do CDN).
function viaProxy(url) {
  const t = getToken();
  return t ? `/iptv/p/${encodeURIComponent(t)}/hls?url=${encodeURIComponent(url)}` : url;
}

export async function attachHls(video, url, onFatal) {
  detachHls(video);
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
        if (data.fatal && onFatal) onFatal();
      });
      video._hls = hls;
      return;
    }
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = viaProxy(url); // Safari/iOS toca HLS nativo
      video.onerror = onFatal || null;
      return;
    }
  }
  // arquivo direto (.mp4/.ts) ou sem suporte a MSE
  video.src = url;
  video.onerror = onFatal || null;
}

export function detachHls(video) {
  if (video?._hls) {
    try {
      video._hls.destroy();
    } catch {}
    video._hls = null;
  }
  video?.removeAttribute?.("src");
}
