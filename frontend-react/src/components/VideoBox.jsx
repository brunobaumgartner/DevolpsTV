import { useRef, useEffect } from "preact/hooks";
import { attachHls, detachHls } from "../lib/hls.js";

// <video> + hls.js (carregado sob demanda). Troca de `url` recarrega; desmontar
// para o vídeo (é o comportamento certo pra tela de "assistir").
export function VideoBox({ url, onFatal, class: cls }) {
  const ref = useRef(null);

  useEffect(() => {
    const v = ref.current;
    if (!v || !url) return;
    attachHls(v, url, onFatal);
    v.play?.().catch(() => {});
    return () => detachHls(v);
  }, [url]);

  return (
    <video
      ref={ref}
      class={cls || "w-full aspect-video bg-black"}
      controls
      autoplay
      playsinline
    />
  );
}
