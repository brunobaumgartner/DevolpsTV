-- Schema inicial do IPTV-BR
-- Executado automaticamente pelo container mysql na primeira subida (docker-entrypoint-initdb.d)

CREATE TABLE IF NOT EXISTS channels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tvg_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    logo_url VARCHAR(500) NULL,
    category VARCHAR(50) NULL,
    is_broadcast_tv BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_tvg_id (tvg_id),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS streams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id INT NOT NULL,
    url VARCHAR(1000) NOT NULL,
    referrer VARCHAR(500) NULL,
    user_agent VARCHAR(500) NULL,
    quality VARCHAR(20) NULL,
    is_healthy BOOLEAN NULL,
    consecutive_failures INT NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    -- reportado pelo navegador do usuário quando o player falha de verdade,
    -- mesmo depois do /resolve ter aprovado (ver ARQUITETURA.md secao 8.2)
    client_failed_at DATETIME NULL,
    client_failure_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_stream_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    UNIQUE KEY uniq_channel_url (channel_id, url(255)),
    KEY idx_healthy (is_healthy)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS programs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id INT NOT NULL,
    title VARCHAR(500) NOT NULL,
    subtitle VARCHAR(500) NULL,
    description TEXT NULL,
    category VARCHAR(200) NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_program_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    KEY idx_channel_time (channel_id, start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS access_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(64) NOT NULL,
    label VARCHAR(100) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME NULL,
    UNIQUE KEY uniq_token (token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NOTA (segurança): neste v1 local, api e worker usam o mesmo usuário MySQL
-- (definido via MYSQL_USER/MYSQL_PASSWORD no .env) para simplificar o setup de teste.
-- Antes de ir pra VPS/produção, criar usuários separados com privilégio mínimo:
--   iptv_api: SELECT em channels/streams, SELECT+UPDATE em access_tokens
--   iptv_worker: SELECT/INSERT/UPDATE/DELETE em channels/streams
-- Ver ARQUITETURA.md secao 9.
