-- Idioma do título de VOD (filme/série/anime), mesmo formato da coluna
-- `language` de `channels` (código curto: pt, en, es...). Preenchido pelo
-- admin (dropdown no catálogo) ou pela coluna `language` do CSV de
-- importação. Ver api/app/languages.py pra lista válida.
ALTER TABLE vod_titles
  ADD COLUMN language VARCHAR(8),
  ADD INDEX ix_vod_titles_language (language);
