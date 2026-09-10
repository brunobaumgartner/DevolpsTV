import { useState } from "preact/hooks";

const EMOJI = { movie: "🎬", series: "📺", channel: "📡" };

// pôster (VOD) ou logo de canal. `fill` = ocupa a célula toda (uso em grid)
export function Card({ kind, title, image, subtitle, badge, onClick, fill }) {
  const [broken, setBroken] = useState(false);
  const showImg = image && !broken;

  if (kind === "channel") {
    return (
      <button
        onClick={onClick}
        class={
          "snap-start rounded-md border border-border bg-card hover:border-accent hover:-translate-y-0.5 " +
          "transition-transform text-left overflow-hidden " +
          (fill ? "" : "shrink-0 w-[150px] md:w-[180px]")
        }
      >
        <div class="aspect-video grid place-items-center bg-card-hover p-2.5">
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
            <span class="text-xl opacity-40">{EMOJI.channel}</span>
          )}
        </div>
        <div class="px-2 py-1.5">
          <div class="text-[12px] font-semibold truncate leading-tight">{title}</div>
          {subtitle && <div class="text-[10px] text-accent truncate mt-0.5">▶ {subtitle}</div>}
        </div>
      </button>
    );
  }

  return (
    <button onClick={onClick} class={"card-poster" + (fill ? " !w-full" : "")}>
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
