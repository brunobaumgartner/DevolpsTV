# IPTV-BR

Backend pessoal que agrega canais de TV brasileiros públicos, valida os streams
periodicamente e expõe um link de playlist (M3U) + um painel web simples pra teste.

Veja [ARQUITETURA.md](./ARQUITETURA.md) pro desenho completo, decisões e pesquisa de
projetos de referência.

## Rodando localmente (teste)

1. Copie o `.env.example` para `.env` e troque as senhas:

   ```bash
   cp .env.example .env
   ```

2. Suba tudo:

   ```bash
   docker compose up --build
   ```

3. Na primeira subida, o worker demora alguns segundos pra popular o banco (busca os
   canais/streams do Brasil e depois roda o primeiro health-check). Acompanhe os logs:

   ```bash
   docker compose logs -f worker
   ```

4. A API gera um **token de teste automaticamente** na primeira subida (só se não
   houver nenhum token cadastrado ainda) — ele aparece nos logs:

   ```bash
   docker compose logs api | grep -A2 "Token de teste"
   ```

5. Abra `http://localhost:7678/` no navegador, cole o token no campo do topo e clique
   em "Carregar canais".

6. Pra usar num app de IPTV de verdade (TV, celular), a playlist fica em:

   ```
   http://localhost:7678/p/<SEU_TOKEN>/playlist.m3u8
   ```

## Estrutura

```
api/       — FastAPI: gera a playlist/JSON e serve o frontend
worker/    — Python + APScheduler: busca canais/streams e roda o health-check
frontend/  — painel web simples (HTML puro + hls.js), só pra testar o backend
mysql/     — schema inicial (rodado automaticamente na primeira subida do container)
```

## Próximos passos (fora do escopo deste v1)

- Migrar exposição pública de IP direto para domínio + Cloudflare Tunnel + TLS
- Separar usuários MySQL por privilégio mínimo (api: leitura; worker: escrita) — hoje
  usa um único usuário pra simplificar o setup local
- Health-check granular (geo-bloqueado / DRM / só-áudio)
- Rate limiting na API
- Ver seção 11 do `ARQUITETURA.md` para a lista completa
