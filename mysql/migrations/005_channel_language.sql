-- Idioma do CONTEÚDO de cada canal (pt/en/es/tr/ru/ar/zh/...), recuperado dos
-- dados originais de importação (nome/categoria antes das limpezas de
-- normalização terem apagado essa informação -- ver
-- api/app/recover_channel_language.py). Usado pelo seletor de idioma da tela
-- de TV ao vivo, pedido do produto em 2026-09-13.
ALTER TABLE channels
  ADD COLUMN language VARCHAR(8),
  ADD INDEX ix_channels_language (language);
