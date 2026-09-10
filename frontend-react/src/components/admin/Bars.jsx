// fileira de barras horizontais (gráfico simples, sem lib)
export function Bars({ rows, labelKey, valueKey, onRowClick }) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey]));
  return (
    <div class="space-y-1.5">
      {rows.map((r) => {
        const clickable = onRowClick && r._clickable;
        return (
          <div
            class={"flex items-center gap-2.5 text-xs " + (clickable ? "cursor-pointer group" : "")}
            onClick={clickable ? () => onRowClick(r) : undefined}
          >
            <div class={"w-32 shrink-0 truncate " + (clickable ? "text-muted group-hover:text-accent" : "text-muted")}>
              {r[labelKey]}
            </div>
            <div class="flex-1 h-2.5 bg-white/5 rounded overflow-hidden">
              <div class="h-full bg-gradient-to-r from-accent2 to-accent" style={`width:${(r[valueKey] / max) * 100}%`} />
            </div>
            <div class="w-10 text-right text-text shrink-0">{r[valueKey]}</div>
          </div>
        );
      })}
    </div>
  );
}
