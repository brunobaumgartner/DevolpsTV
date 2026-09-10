// carrega hls.js só quando precisa (fora do bundle inicial)
let _Hls = null;

export async function attachHls(video, url, onFatal) {
  detachHls(video);
  const isM3u8 = /\.m3u8(\?|$)/i.test(url);

  if (isM3u8 && video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = url; // Safari/iOS toca HLS nativo
    video.onerror = onFatal || null;
    return;
  }
  if (isM3u8) {
    if (!_Hls) _Hls = (await import("hls.js")).default;
    if (_Hls.isSupported()) {
      const hls = new _Hls({ maxBufferLength: 20 });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(_Hls.Events.ERROR, (_e, data) => {
        if (data.fatal && onFatal) onFatal();
      });
      video._hls = hls;
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
