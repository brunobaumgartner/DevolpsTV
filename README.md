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

## Adicionando títulos ao catálogo VOD (filmes/séries)

As tabelas `vod_titles` e `vod_items` ficam **vazias por padrão** — nenhum worker
popula isso automaticamente, e nenhuma fonte externa é consultada. Você adiciona
manualmente, conforme for conseguindo autorização pra cada obra (ver
`ARQUITETURA.md` seção 9 pro porquê dessa decisão).

### Via CSV (recomendado — `api/app/import_vod.py`)

1. Copie `data/titulos.exemplo.csv` e edite com seus títulos. Colunas:

   ```
   type,title,description,poster_url,genre,year,season_number,episode_number,episode_title,stream_url
   ```

   - `type`: `movie` ou `series`
   - `title`: linhas com o mesmo `title`+`type` viram episódios do MESMO título
   - `season_number`/`episode_number`/`episode_title`: só pra `series`, deixe em branco pra `movie`
   - `stream_url`: pode deixar em branco se ainda não tem o link/autorização — dá pra rodar o script de novo depois só preenchendo essa coluna. **Uma célula em branco nunca apaga um link já salvo.**

2. Suba o arquivo pra VPS (o `docker-compose.yml` já monta `./data` dentro do container da API):

   ```bash
   scp -P 443 seus-titulos.csv root@144.91.70.44:/srv/iptv/data/
   ```

3. Rode a importação:

   ```bash
   ssh whatispromo "docker exec iptv-api-1 python -m app.import_vod /app/data/seus-titulos.csv"
   ```

   É idempotente — pode rodar quantas vezes quiser com o arquivo atualizado (títulos/links novos são adicionados, os já existentes são atualizados, nada duplica).

### Via SQL direto (alternativa)

```sql
-- Filme (1 título = 1 item, sem season/episode)
INSERT INTO vod_titles (type, title, description, poster_url, genre, year)
VALUES ('movie', 'Nome do Filme', 'Sinopse opcional', 'https://.../poster.jpg', 'Ação', 2020);
INSERT INTO vod_items (title_id, stream_url) VALUES (LAST_INSERT_ID(), 'https://.../filme.m3u8');

-- Série (1 título = vários episódios)
INSERT INTO vod_titles (type, title, poster_url, genre, year)
VALUES ('series', 'Nome da Série', 'https://.../poster.jpg', 'Drama', 2019);
SET @tid = LAST_INSERT_ID();
INSERT INTO vod_items (title_id, season_number, episode_number, episode_title, stream_url) VALUES
  (@tid, 1, 1, 'Piloto', 'https://.../s01e01.m3u8'),
  (@tid, 1, 2, 'Episódio 2', NULL); -- NULL = ainda sem link
```

Rodando direto na VPS: `docker exec -it iptv-mysql-1 mysql -uroot -p<senha> iptv`

## Próximos passos (fora do escopo deste v1)

- Migrar exposição pública de IP direto para domínio + Cloudflare Tunnel + TLS
- Separar usuários MySQL por privilégio mínimo (api: leitura; worker: escrita) — hoje
  usa um único usuário pra simplificar o setup local
- Health-check granular (geo-bloqueado / DRM / só-áudio)
- Rate limiting na API
- Ver seção 11 do `ARQUITETURA.md` para a lista completa
