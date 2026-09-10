import { useState } from "preact/hooks";

const EMOJI = { movie: "🎬", series: "📺", channel: "📡" };

// pôster (VOD) ou logo de canal
export function Card({ kind, title, image, subtitle, badge, onClick }) {
  const [broken, setBroken] = useState(false);
  const showImg = image && !broken;

  if (kind === "channel") {
    return (
      <button
        onClick={onClick}
        class="shrink-0 snap-start w-[150px] md:w-[172px] rounded-md border border-border bg-card
               hover:border-accent hover:-translate-y-0.5 transition-transform text-left overflow-hidden"
      >
        <div class="h-[92px] grid place-items-center bg-card-hover p-3">
          {showImg ? (
            <img
              src={image}
              alt=""
              loading="lazy"
              decoding="async"
              class="max-h-full max-w-full object-contain"
              onError={() => setBroken(true)}
            />
          ) : (
            <span class="text-2xl opacity-50">{EMOJI.channel}</span>
          )}
        </div>
        <div class="p-2">
          <div class="text-[13px] font-semibold truncate">{title}</div>
          <div class="text-[11px] text-muted truncate">
            {subtitle ? <span class="text-accent">▶ {subtitle}</span> : " "}
          </div>
        </div>
      </button>
    );
  }

  return (
    <button onClick={onClick} class="card-poster">
      {showImg ? (
        <img
          src={image}
          alt=""
          loading="lazy"
          decoding="async"
          class="h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : (
        <div class="h-full w-full grid place-items-center text-3xl opacity-50 bg-card-hover">
          {EMOJI[kind] || "🎬"}
        </div>
      )}
      {badge && (
        <span class="absolute top-1 left-1 text-[10px] uppercase tracking-wide bg-bg/80 text-accent rounded px-1.5 py-0.5">
          {badge}
        </span>
      )}
      <span class="absolute inset-x-0 bottom-0 p-2 pt-6 text-[12px] font-semibold leading-tight bg-gradient-to-t from-bg to-transparent">
        {title}
      </span>
    </button>
  );
}
