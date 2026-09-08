# IPTV-BR — Documento de Arquitetura

> Status: **planejamento** (nenhum código/infra criado ainda)
> Última atualização: 2026-09-04

## 1. Objetivo do projeto

Um backend pessoal que:

1. Coleta canais de TV **brasileiros** públicos disponíveis na internet
2. Valida os streams periodicamente (remove/oculta o que está quebrado)
3. Organiza os canais por **categoria/tipo de conteúdo** (desenho, filmes, séries, TV aberta, canais de loop de 1 programa, etc.)
4. Expõe isso como **links prontos** (`playlist.m3u8` + EPG) que podem ser colados em qualquer app de IPTV (TV, celular, VLC, Kodi, etc.) — sem precisar de site/app próprio pra assistir

O app web (se vier a existir) é **secundário**: o produto principal é o link.

## 2. Fontes de dados avaliadas

### Fonte principal: ecossistema `iptv-org`
- [`iptv-org/iptv`](https://github.com/iptv-org/iptv) — playlists M3U por país
- [`iptv-org/api`](https://github.com/iptv-org/api) — **API JSON estática** (preferível a parsear M3U na mão):
  - `channels.json` — nome, categorias, país, logo
  - `streams.json` — url, `referrer`, `user_agent`, `quality`, `label` (ex: "Geo-blocked")
  - `categories.json` — lista oficial de categorias
  - `guides.json` — mapeamento de EPG por canal (majoritariamente **sem** XML pronto — ver seção 4)
- [`iptv-org/database`](https://github.com/iptv-org/database) — dados brutos por trás da API
- [`iptv-org/epg`](https://github.com/iptv-org/epg) — ferramenta **Node.js** de scraping de grade de programação por site (não é um arquivo pronto pra baixar)

**Levantamento real (checado ao vivo em 2026-09-04):**
- 796 canais brasileiros cadastrados no `channels.json`
- Distribuição por categoria (top): general 209, sem categoria 264, entertainment 50, news 43, sports 40, education 32, religious 32, movies 28, kids 22, legislative 18, animation 14, series 13, music 13

### Fontes BR adicionais (redundância de mirrors + curadoria local)
| Repositório | Uso proposto |
|---|---|
| [`iptv-com/iptv`](https://github.com/iptv-com/iptv) | Curadoria BR em PT-BR baseada no iptv-org — fonte extra de canais/mirrors |
| [`iptv-com/epg`](https://github.com/iptv-com/epg) | **`brazil.xml`** — EPG real (título/horário/descrição) de canais BR, gerado 100% em **Python** (`fetch_epg.py`) via GitHub Actions diariamente. Resolve o problema de grade de programação sem precisar do scraper Node do iptv-org. Link: `https://raw.githubusercontent.com/iptv-com/epg/main/guides/brazil.xml` |
| [`Free-TV/IPTV`](https://github.com/Free-TV/IPTV) | Fonte extra de canais BR (`playlists/playlist_brazil.m3u8`) |
| [`joaoguidugli/FTA-IPTV-Brasil`](https://github.com/joaoguidugli/FTA-IPTV-Brasil) | Referência de validação de canais free-to-air BR |

**Estratégia:** agregar canais de múltiplas fontes, deduplicar por nome/tvg-id, manter múltiplos mirrors por canal para aumentar a chance de ter sempre um stream saudável.

## 3. Classificação dos canais ("separar por programação")

Esclarecimento importante: "por programação" = **por tipo de conteúdo que o canal transmite** (não grade horária). Ex: canais que só passam desenho, só filme, só série, TV aberta, ou 1 programa em loop.

Isso é resolvido via `categories` do `channels.json`, mais duas camadas manuais:

1. **Categorias oficiais** (`animation`, `movies`, `series`, `kids`, `news`, `sports`, `religious`, `music`, `general`, etc.) — usadas direto
2. **"TV aberta"** — não é uma categoria da API (é tipo de distribuição, não gênero). Solução: lista fixa e curta no código (Globo, SBT, Record, Band, RedeTV, etc.) marcando esses canais com uma tag adicional
3. **"Canal de loop de 1 programa"** — vem do campo `label` em `streams.json` (ex: tag equivalente a `[Not 24/7]` vista nos `.m3u` brutos) — tratado como tag própria, não como categoria de gênero
4. **Sem categoria** (264 canais) — agrupados em "Outros / Não categorizado", sem travar o restante

## 4. EPG / Grade de programação — histórico da decisão

- Investigação inicial: `guides.json` do iptv-org tem 273 mapeamentos de EPG pra canais BR, mas **quase todos com `sources: []`** (sem XML pronto) — de 180 mil mapeamentos globais, só 2 têm fonte hospedada direta
- Conclusão inicial: grade completa por horário exigiria rodar o scraper Node do `iptv-org/epg` (scrapers específicos por site) — decisão adiada pra fase 2
- **Atualização:** o repositório [`iptv-com/epg`](https://github.com/iptv-com/epg) já resolve isso para canais BR — gera um `brazil.xml` diário, 100% em Python, sem dependência de Node
- **Decisão atual:** usar `brazil.xml` do iptv-com/epg como fonte de EPG (ou o script `fetch_epg.py` deles como referência para uma versão própria adaptada às categorias do projeto)

## 5. Infraestrutura (VPS existente)

VPS já em uso para outros projetos — levantamento feito em 2026-09-04:

- **Specs:** 4 vCPUs, 7.8GB RAM (~4.8GB disponível), 112GB disco livre de 145GB, load average ~0.40 (ociosa)
- **Serviços já rodando:** Airflow (webserver+scheduler, projeto `whatpromo`), MariaDB, Redis, Evolution API (WhatsApp), app PHP com MySQL + nginx (projeto `exposite`)
- **Rede Docker:** dois stacks isolados por `docker network` — `whatpromo_rede_whatpromo` e `exposite_rede_exposite`
- **Portas já ocupadas:** 22 e 443 (SSH, non-standard), 80 (nginx exposite), 8080/8081 (Evolution/Airflow webserver)
- **Segurança da VPS (estado atual):** fail2ban ativo, unattended-upgrades ativo, ufw com default-deny. Ponto de atenção (fora do escopo deste projeto): `PermitRootLogin yes` e `PasswordAuthentication` não desabilitado explicitamente no `sshd_config`

**Decisão:** projeto novo **isolado**, sem mexer em nenhum stack existente:
- Diretório próprio `/srv/iptv/`
- Rede Docker própria (`iptv_rede_iptv`)
- MySQL dedicado (não reaproveita bancos existentes) — RAM sobra, e evita qualquer risco cruzado entre projetos
- **Sem Airflow dedicado** — reaproveitar o Airflow do `whatpromo` foi descartado por decisão explícita (não misturar pastas/projetos), e subir uma segunda instância de Airflow só pra 3 jobs simples foi considerado over-engineering. Agendamento fica embutido no próprio worker Python (ex: APScheduler)

## 6. Stack técnica definida

| Componente | Tecnologia | Observação |
|---|---|---|
| API | **Python** (FastAPI provável) | Gera `playlist.m3u8` e EPG dinamicamente a partir do MySQL |
| Worker | **Python** (APScheduler) | Roda os jobs periódicos: fetch de canais/streams, health-check, fetch de EPG |
| Banco | MySQL 8 dedicado | Container próprio, volume próprio |
| Exposição pública | **Proxy reverso via nginx do `exposite` (porta 80)**, path `/iptv/` | Ver nota abaixo — porta 7678 direta não é alcançável de fora |

Todo o backend (API + worker) em **Python**, por decisão explícita — evita misturar linguagens/runtimes no stack (ex: nada de Node.js pro EPG).

**Descoberta em 2026-09-08 ao tentar expor a porta 7678 direto:** o `ufw` da VPS liberava a porta normalmente, mas o tráfego nunca chegava de fora — confirmado comparando com a porta 8081 (Airflow), que também está "aberta" no `ufw` mas **também não é alcançável externamente**. Ou seja: existe um firewall em nível de provedor (fora do SO), que hoje só deixa passar 22/80/443. Portas abertas só no `ufw` não bastam.

**Solução aplicada:** proxy reverso via o nginx que já existe pro projeto `exposite` (único a rodar na porta 80, que é a única porta HTTP que passa pelo firewall externo). Como não há domínio ainda, o roteamento é por path: um bloco `location /iptv/` foi adicionado ao `nginx.conf` do `exposite`, encaminhando pra `iptv-api-1:7678` — o container da API foi conectado também à rede Docker do `exposite` (`docker network connect exposite_rede_exposite iptv-api-1`) pra isso funcionar.

- Link de playlist agora é: `http://144.91.70.44/iptv/p/<token>/playlist.m3u8`
- Porta `7678` fechada de novo no `ufw` (só acessível internamente, entre containers)
- Frontend ajustado pra usar caminhos relativos (sem `/` no início), já que agora roda sob um subpath
- Sem TLS por padrão (HTTP puro) — funciona na maioria dos apps de IPTV, mas fica pendente pra quando tiver domínio
- Rate limiting não pode ficar na borda (Cloudflare) — implementado dentro da própria API (ex: `slowapi`) — ainda não feito
- Token no path da playlist/EPG é a principal proteção contra uso indevido enquanto não há domínio/HTTPS

**Achado à parte (infra do `exposite`, não deste projeto):** o container `exposite_nginx` estava com o bind mount do `nginx.conf` "congelado" desde 19/08 — alguma edição anterior no host trocou o arquivo via `mv`/rename em vez de editar in-place, o que quebra bind mounts de arquivo único no Docker (o container fica preso ao inode antigo). Precisei reiniciar o `exposite_nginx` (com autorização do usuário) pra ele voltar a ler a config atual — o que também corrigiu esse problema pré-existente pro `exposite`. Fica registrado: qualquer edição futura nesse `nginx.conf` deve usar escrita in-place (ex: `cat > arquivo`, editor comum) e nunca ferramentas que fazem replace via rename (`sed -i` inclusive faz isso por padrão), ou vai quebrar de novo.

## 7. Modelo de dados (rascunho)

```sql
channels (
  id, tvg_id UNIQUE, name, logo_url, category, is_broadcast_tv (bool),
  is_single_program_loop (bool), is_active, created_at, updated_at
)

streams (
  id, channel_id FK, url, referrer, user_agent, quality,
  is_healthy, health_status (ok | offline | geo_blocked | drm | audio_only),
  consecutive_failures, last_checked_at
)

programs (               -- populado a partir do brazil.xml (iptv-com/epg)
  id, channel_tvg_id, title, description, start_time, end_time
)

access_tokens (
  id, token UNIQUE, label, is_active, created_at, last_used_at
)
```

## 8. Endpoints previstos

- `GET /p/{token}/playlist.m3u8` — playlist só com canais BR ativos e com pelo menos 1 stream saudável, um por canal (o melhor mirror disponível)
- `GET /p/{token}/channels.json` — mesma lista em JSON, com até 3 mirrors saudáveis por canal (`stream_urls`), usado pelo frontend
- `GET /p/{token}/channels/{tvg_id}/resolve` — **verificação ao vivo** (não usa o cache do health-check): testa os mirrors saudáveis desse canal na hora e devolve o primeiro que responder de verdade agora, ou 503 se nenhum responder. Ver seção 9.1
- `GET /p/{token}/epg.xml` — EPG (XMLTV) filtrado pros canais presentes na playlist (ainda não implementado)
- `GET /health` — healthcheck simples, sem token, pra monitoramento

### 8.1 Por que existe verificação ao vivo além do health-check periódico

Descoberto em 2026-09-08 testando o painel: fontes públicas de IPTV são instáveis a ponto de cair **dentro da janela de 15 minutos** entre uma rodada do health-check e a outra (confirmado em 3 redes independentes com o mesmo canal). Um canal marcado como "saudável" no banco pode já estar fora do ar quando o usuário realmente clica.

Solução: o `/resolve` faz a checagem no exato momento do clique (paralelo, ~4s de timeout, testa os mirrors conhecidos e devolve o primeiro vivo). O frontend chama esse endpoint antes de entregar a URL pro player — só mostra "indisponível" depois de confirmar que **nenhum** mirror respondeu agora, em vez de confiar num status de minutos atrás. O player também mantém fallback pros outros mirrors conhecidos caso o mirror confirmado caia nos segundos entre a checagem e o play efetivo.

Isso não elimina 100% a instabilidade (é característica da fonte, não bug), mas reduz bastante os casos de "carrega e nunca abre".

### 8.2 Quando até a verificação ao vivo não é suficiente: feedback do navegador real

Caso real investigado em 2026-09-08 (canal ESPN.br): o `/resolve` aprovava o mirror, e uma investigação profunda confirmou que o **servidor de origem estava genuinamente funcionando** (bytes de vídeo reais validados via `curl` da VPS, CORS liberado, cadeia de manifestos íntegra) — mas o navegador real do usuário mesmo assim não conseguia tocar. A causa exata nesse caso específico não foi 100% isolada (token de sessão de vida curtíssima na origem, possíveis diferenças de rede/roteamento entre a VPS e o cliente final), mas o ponto central é: **nenhuma checagem feita pelo servidor — por mais profunda que seja — garante 100% que o navegador real do usuário final vai conseguir tocar**. CORS aberto e bytes chegando via `curl` não é a mesma coisa que o `hls.js` do navegador do usuário conseguir montar o player.

**Decisão de produto (a pedido do usuário): "se não está funcionando, não deve aparecer".** Em vez de continuar tentando adivinhar/replicar todo tipo de falha client-side no servidor, o navegador virou a fonte de verdade final:

- Quando o player esgota todos os mirrors conhecidos de um canal (`tryMirror` chega ao fim), o frontend chama `POST /p/{token}/channels/{tvg_id}/report-failure` com a URL que falhou
- O backend marca esse stream com `client_failed_at` / incrementa `client_failure_count`
- Streams com falha reportada recentemente (`CLIENT_FAILURE_SUPPRESS_MINUTES = 30`, em `playlist_builder.py`) são **excluídos** de `channels.json`, `playlist.m3u8` e `/resolve` — mesmo que o health-check do worker continue achando saudável
- Depois de 30 min sem novo reporte, volta a ser oferecido normalmente (a supressão é temporal, não permanente — essas fontes se recuperam sozinhas com frequência)
- O frontend também remove o canal da lista visível **imediatamente**, sem esperar o próximo carregamento

Isso fecha o loop: servidor valida o que consegue (bem mais rigoroso que antes, seção 8.1), e o cliente real reporta a palavra final sobre o que realmente tocou.

Token no path em vez de rota fixa — evita que o link seja "adivinhável"; revogável/gerável de novo se vazar.

### 8.3 EPG / Grade de programação (implementado em 2026-09-08)

Retomando a decisão da seção 4: **implementado**, usando [`limaalef/BrazilTVEPG`](https://github.com/limaalef/BrazilTVEPG) como fonte (atualizada 5x/dia, mantida ativamente — confirmado commit de 2 dias antes da integração).

**Particularidade da fonte:** o `channel id` do XMLTV é o **nome de exibição** do canal na operadora (ex: `"ESPN"`, `"BAND HD"`), não o `tvg-id` no padrão iptv-org. O cruzamento com `channels.name` é feito por **igualdade exata de nome normalizado** (minúsculo, sem acento, sem sufixo de qualidade como HD/4K/UHD) — sem fuzzy matching, pra não arriscar mesclar programação no canal errado. Canal cujo nome não bate fica sem EPG, e tudo bem.

**Taxa de casamento real medida** (não estimada): dos ~347 canais únicos encontrados nas 5 fontes usadas (`epg.xml`, `globo.xml`, `claro.xml`, `vivoplay.xml`, `xsports.xml` — ficaram de fora `globo-internacional.xml`, público dos EUA, e `maissbt.xml`, serviço ainda não lançado segundo o próprio README da fonte), **198 casamentos canal×fonte** resultaram em **38.390 programas** inseridos no primeiro ciclo.

**Bug real encontrado e corrigido antes de ir pro ar:** o XMLTV vem com offset de fuso explícito (`-0300`, Brasília). A primeira versão gravava os campos numéricos como vieram, sem converter — o banco ficaria com horário local guardado como se fosse UTC (defasagem de até 3h). Corrigido convertendo pra UTC (`.astimezone(timezone.utc)`) antes de persistir, consistente com o resto do sistema. Validado comparando um programa marcado como "passando agora" contra o horário real (17:33 UTC = 14:33 Brasília, "Melhor da Tarde" da Band de fato no ar nesse horário).

**O que foi construído:**
- `worker/app/epg_sources.py` — download + parse streaming (`iterparse`, não carrega o XML inteiro na memória — os arquivos passam de 6MB) das 5 fontes, normalização de nome
- `worker/app/jobs/fetch_epg.py` — cruza com o catálogo, substitui a programação dos canais casados a cada ciclo (mais simples e correto que diff incremental num dado que já é uma janela rolante)
- Roda a cada 3h (`EPG_FETCH_INTERVAL_MIN`), consistente com a frequência de atualização da fonte
- Tabela `programs` (channel_id, title, subtitle, description, category, start_time, end_time — todos em UTC)
- `GET /p/{token}/channels.json` agora inclui `now_playing` (título + hora de término) por canal, quando disponível
- `GET /p/{token}/channels/{tvg_id}/epg` — próximas ~12h de programação de um canal
- Frontend: "▶ [programa]" embaixo do nome na lista, e painel de programação ao selecionar um canal

## 9. Catálogo sob demanda (filmes/séries) — decisão e escopo

Em 2026-09-08 o usuário pediu pra incluir filmes e séries **sob demanda** (escolher episódio/filme específico), além dos canais lineares de TV que já existiam.

**Fontes descartadas nessa investigação** (todas via gists de um único usuário, "sempreconceito"): listas antigas (2014-2017, uma delas se autodeclarando "Atualizado: 20/04/2017") e, mais importante, uma delas (`lista joabe.m3u`) não era nem lista de canais — era hospedagem direta de **episódios individuais de série** (Mr. Robot dublado) num CDN de pirataria dedicado (`netcine-bucket`). Isso é uma categoria diferente da agregação de TV aberta que o projeto já fazia:

- **TV ao vivo (já implementado):** streams que o iptv-org alega serem disponibilizados publicamente pelos próprios detentores de direito — linha defensável
- **VOD de CDN de pirataria:** cópia de obra protegida sem nenhuma alegação de autorização — sem margem de interpretação, mesmo pra uso pessoal (a legislação brasileira de direitos autorais não tem exceção de uso pessoal pra isso)

**Decisão:** a funcionalidade de catálogo sob demanda foi construída, mas **sem nenhum conteúdo/link**. As tabelas `vod_titles` e `vod_items` ficam vazias por padrão — nenhum worker as popula, nenhuma fonte externa é consultada pra elas. O usuário adiciona manualmente título por título conforme for conseguindo autorização real (licença do detentor dos direitos, obra em domínio público/Creative Commons, ou produção própria) — ver README.md "Adicionando títulos ao catálogo VOD" pros comandos SQL.

**O que foi construído:**
- `vod_titles` (filme/série, metadados) + `vod_items` (1 item por filme, 1 por episódio de série — `stream_url` NULL até ser preenchido)
- `GET /p/{token}/vod` — lista títulos com um `available: true/false` (se tem pelo menos 1 item com link)
- `GET /p/{token}/vod/{id}` — detalhe com os episódios (pra série) e o status de cada um
- Frontend: aba "Filmes e Séries" com grid de pôsteres; título sem link mostra badge "sem link ainda"; série abre lista de episódios, só os com link são clicáveis
- Testado com dados temporários (inseridos, verificados, removidos) — catálogo real começa e permanece vazio

## 10. Segurança

1. **Exposição:** por ora, **IP direto da VPS na porta 7678** (decisão temporária, sem domínio ainda — ver seção 6). Plano original era Cloudflare Tunnel (sem porta pública aberta); migrar pra isso quando houver domínio definido
2. **Link não adivinhável:** token aleatório no path da playlist/EPG, revogável — enquanto não há Cloudflare/TLS na frente, esse token é a principal barreira contra acesso indevido
3. **Privilégio mínimo no MySQL:** usuário da API só com `SELECT`; usuário do worker só com `INSERT/UPDATE/DELETE` nas tabelas do projeto; nenhum dos dois é root nem acessa bancos de outros projetos
4. **Segredos fora do código:** `.env` próprio do projeto, fora do git, permissão restrita, nunca dentro da imagem Docker
5. **Containers:** versões de imagem fixadas (sem `latest`), processo roda como usuário não-root, MySQL sem porta publicada pro host
6. **Validação de dados:** parsing de M3U/JSON/XML externos sem `eval`/execução de conteúdo; queries sempre parametrizadas (proteção contra injection)
7. **Rate limiting:** regra no Cloudflare na rota da playlist, contra abuso/polling agressivo
8. *(Observação fora do escopo do projeto, registrada durante o levantamento da VPS: revisar `PermitRootLogin`/`PasswordAuthentication` do SSH em algum momento — não faz parte deste projeto)*

## 11. Ideias de projetos de referência (pesquisa de mercado)

Pesquisa feita em repositórios GitHub de IPTV pra buscar boas práticas e funcionalidades a incorporar:

| Projeto | Ideia relevante |
|---|---|
| [`euzu/tuliprox`](https://github.com/euzu/tuliprox) (Rust) | Serve a mesma lista também em **formato Xtream Codes** (usuário/senha), além de M3U; emulação de **HDHomeRun** pra Plex/Emby/Jellyfin reconhecerem automaticamente como "tuner"; regras de filtro/renomeação configuráveis |
| [`kristofferR/IPTVChecker-Python`](https://github.com/kristofferR/IPTVChecker-Python) | Health-check granular: distingue **geo-bloqueado, DRM, e stream só-áudio**, não só "online/offline" |
| [`Romaxa55/world_ip_tv`](https://github.com/Romaxa55/world_ip_tv) | Roda o job pesado de coleta/validação **gratuitamente no GitHub Actions**, publicando só o resultado estático — reduz carga na própria infraestrutura |
| [`iptv-com/epg`](https://github.com/iptv-com/epg) | Ver seção 4 — EPG BR pronto, em Python |

**Melhorias a considerar (não decididas ainda):**
- Health-check granular (geo-bloqueado / DRM / só-áudio) em vez de só saudável/quebrado
- Avaliar formato Xtream Codes como saída alternativa ao M3U (decisão pendente — complexidade extra a avaliar)
- Avaliar usar GitHub Actions pra parte do processamento pesado, aliviando a VPS

## 12. Decisões em aberto

- [ ] Confirmar se vale adicionar saída em Xtream Codes além de M3U
- [ ] Decidir se health-check vai ser granular (geo-bloqueado/DRM/áudio) desde o v1 ou só up/down inicialmente
- [ ] Definir se GitHub Actions assume parte do processamento (coleta/validação) ou se fica 100% no worker da VPS
- [ ] Confirmar app web secundário — escopo e prioridade (fica pra depois do backend estar funcionando)
- [ ] Definir domínio/subdomínio e migrar exposição de IP direto para Cloudflare Tunnel + TLS
- [ ] Decidir se o código do projeto vai pra um repositório GitHub (privado) ou fica só local/VPS

## 13. Decisões fechadas para o v1 (2026-09-08)

Pra destravar o início da implementação, ficou definido:

- Health-check **simples** no v1 (saudável/quebrado); granularidade (geo-bloqueado/DRM/áudio) fica pra depois
- **Sem** Xtream Codes no v1 — só M3U + EPG
- Coleta/validação roda no **worker da própria VPS** (não GitHub Actions) no v1
- App web fica pra depois — foco total no backend/link primeiro
- Exposição via **IP direto da VPS, porta 7678**, sem domínio/Cloudflare por enquanto (ver seção 6)
