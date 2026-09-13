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

-- MySQL 8.0 não suporta "ADD INDEX IF NOT EXISTS" (isso é extensão do
-- MariaDB) — numa instalação já rodando essa migração antes, remova a
-- linha do índice já existente pra não dar erro de duplicata.
ALTER TABLE vod_titles ADD INDEX idx_type_title (type, title(255)), ALGORITHM=INPLACE, LOCK=NONE;
ALTER TABLE vod_streams ADD INDEX idx_url (url(255)), ALGORITHM=INPLACE, LOCK=NONE;
ALTER TABLE streams ADD INDEX idx_url (url(255)), ALGORITHM=INPLACE, LOCK=NONE;
