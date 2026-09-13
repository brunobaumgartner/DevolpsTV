-- Índices que faltavam e derrubavam a performance da importação em massa —
-- achado real em 2026-09-13: vod_titles não tinha NENHUM índice além da PK,
-- então toda checagem de "esse título já existe?" (feita em toda importação)
-- era varredura completa da tabela (já com 140mil+ linhas). vod_streams e
-- streams tinham índice composto (item_id/channel_id, url) mas nada em url
-- sozinho, usado pra achar duplicata/global-uniqueness.
--
-- Numa VPS já em produção, aplicar manualmente via docker exec (ALGORITHM=
-- INPLACE, LOCK=NONE não bloqueia leitura/escrita — seguro rodar com o
-- sistema no ar).

-- title é VARCHAR(500); SEM prefixo de propósito (não title(255)) — índice
-- de prefixo nunca serve pra otimizar ORDER BY (um prefixo compartilhado não
-- garante a ordem do valor completo), e o catálogo pagina ordenando por
-- title. Com utf8mb4 (4 bytes/char) o índice completo ainda cabe dentro do
-- limite de 3072 bytes do InnoDB, então não precisa cortar. idx_genre_title/
-- idx_genre_id existem pra listagem por gênero (catálogo) e pra home (que
-- ordena por id).
--
-- MySQL 8.0 não suporta "ADD INDEX IF NOT EXISTS" (isso é extensão do
-- MariaDB) — numa instalação já rodando essa migração antes, remova a
-- linha do índice já existente pra não dar erro de duplicata.
ALTER TABLE vod_titles
  ADD INDEX idx_type_title (type, title),
  ADD INDEX idx_genre_title (genre, title),
  ADD INDEX idx_genre_id (genre, id),
  ALGORITHM=INPLACE, LOCK=NONE;
ALTER TABLE vod_streams ADD INDEX idx_url (url(255)), ALGORITHM=INPLACE, LOCK=NONE;
ALTER TABLE streams ADD INDEX idx_url (url(255)), ALGORITHM=INPLACE, LOCK=NONE;
