import { useRef, useEffect } from "preact/hooks";
import { attachHls, detachHls } from "../lib/hls.js";

// <video> + hls.js (carregado sob demanda). Troca de `url` recarrega; desmontar
// para o vídeo (é o comportamento certo pra tela de "assistir").
// - startAt: segundos pra retomar a reprodução
// - onTime(position, duration): chamado ~a cada 10s enquanto toca
// - onEnded(): fim do vídeo
export function VideoBox({ url, onFatal, onTime, onEnded, startAt, class: cls }) {
  const ref = useRef(null);
  const lastReport = useRef(0);
  const seeked = useRef(false);

  useEffect(() => {
    const v = ref.current;
    if (!v || !url) return;
    seeked.current = false;
    lastReport.current = 0;
    attachHls(v, url, onFatal);
    v.play?.().catch(() => {});
    return () => detachHls(v);
  }, [url]);

  const onLoaded = () => {
    const v = ref.current;
    if (v && startAt && !seeked.current && startAt < (v.duration || Infinity) - 5) {
      try {
        v.currentTime = startAt;
      } catch {}
    }
    seeked.current = true;
  };

  const onTimeUpdate = () => {
    const v = ref.current;
    if (!v || !onTime) return;
    const now = Date.now();
    if (now - lastReport.current < 10000) return; // no máx. 1 report / 10s
    lastReport.current = now;
    if (v.currentTime > 3) onTime(v.currentTime, v.duration || 0);
  };

  const handleEnded = () => {
    const v = ref.current;
    if (v && onTime) onTime(v.duration || 0, v.duration || 0); // garante o "finished"
    onEnded?.();
  };

  return (
    <video
      ref={ref}
      class={cls || "w-full aspect-video bg-black"}
      controls
      autoplay
      playsinline
      referrerpolicy="no-referrer"
      onLoadedMetadata={onLoaded}
      onTimeUpdate={onTimeUpdate}
      onEnded={handleEnded}
      onPause={onTimeUpdate}
    />
  );
}
