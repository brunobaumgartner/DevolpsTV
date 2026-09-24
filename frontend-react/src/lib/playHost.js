import { adminApi } from "./api.js";

// Link de vídeo http:// não toca numa página https:// ("conteúdo misto").
// play.exposite.com.br é o MESMO sistema em HTTP puro (registro DNS só-DNS no
// Cloudflare, sem HTTPS), então o vídeo toca direto do provedor pro navegador.
export const PLAY_HOST = "play.exposite.com.br";
export const SECURE_HOST = "iptv.exposite.com.br";

export const onPlayHost = () => location.protocol === "http:" && location.hostname === PLAY_HOST;

export function needsPlayHost(url) {
  return location.protocol === "https:" && /^http:\/\//i.test(url || "");
}

// leva a MESMA tela pro play, com um bilhete de uso único (60s) que lá vira
// uma sessão só de reprodução — o cookie não atravessa de um subdomínio pro outro
export async function goPlayHost() {
  const { ticket } = await adminApi.playTicket();
  location.href = `http://${PLAY_HOST}${location.pathname}?t=${encodeURIComponent(ticket)}${location.hash}`;
}

export function secureUrl() {
  return `https://${SECURE_HOST}${location.pathname}`;
}

// no play: troca o ?t=<bilhete> por sessão e limpa o bilhete da URL
export async function consumeTicketFromUrl() {
  const params = new URLSearchParams(location.search);
  const ticket = params.get("t");
  if (!ticket) return;
  params.delete("t");
  const qs = params.toString();
  history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  try {
    await adminApi.playLogin(ticket);
  } catch {
    // bilhete expirado/usado: cai na tela de login normal
  }
}
