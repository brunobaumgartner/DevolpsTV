-- Mirrors por item VOD (mesmo papel que `streams` tem pra `channels`):
-- permite mais de um link por filme/episódio, com health-check e fallback
-- independentes por link, igual já funciona pra TV ao vivo.
--
-- IMPORTANTE: docker-entrypoint-initdb.d só roda na PRIMEIRA subida do
-- container mysql (volume vazio) — numa VPS já em produção com dados, este
-- arquivo precisa ser aplicado manualmente (CREATE TABLE + INSERT abaixo)
-- via `docker exec` antes do deploy do código que depende dele.

CREATE TABLE IF NOT EXISTS vod_streams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_id INT NOT NULL,
    url VARCHAR(1000) NOT NULL,
    is_healthy BOOLEAN NULL,
    consecutive_failures INT NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    client_failed_at DATETIME NULL,
    client_failure_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_vod_stream_item FOREIGN KEY (item_id) REFERENCES vod_items(id) ON DELETE CASCADE,
    UNIQUE KEY uniq_item_url (item_id, url(255)),
    KEY idx_vod_stream_healthy (is_healthy)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- backfill: 1 mirror por item que já tinha stream_url preenchido, carregando
-- o health-check que já existia em vod_items (evita perder o histórico e
-- recomeçar do zero no próximo ciclo do worker)
INSERT IGNORE INTO vod_streams (item_id, url, is_healthy, consecutive_failures, last_checked_at)
SELECT id, stream_url, is_healthy, consecutive_failures, last_checked_at
FROM vod_items
WHERE stream_url IS NOT NULL;
