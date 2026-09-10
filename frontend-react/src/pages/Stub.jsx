// telas ainda não migradas (passos 2–4 do plano)
export function Stub({ params }) {
  return (
    <div class="p-8 text-center text-muted">
      <div class="text-4xl mb-3 opacity-40">🛠️</div>
      <p class="text-sm">Esta tela entra nos próximos passos da migração.</p>
      {params?.nome && <p class="text-xs mt-2 text-accent">{params.nome}</p>}
    </div>
  );
}
