-- Schema inicial do IPTV-BR
-- Executado automaticamente pelo container mysql na primeira subida (docker-entrypoint-initdb.d)

CREATE TABLE IF NOT EXISTS channels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tvg_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    logo_url VARCHAR(500) NULL,
    -- imagem de fundo/"capa" (16:9), vem do dataset mjh.nz pros canais FAST
    backdrop_url VARCHAR(600) NULL,
    description TEXT NULL,
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
    -- idioma do stream (do feeds.json do iptv-org); NULL = tratado como
    -- "Português" no frontend. feed_id só rastreia a origem no iptv-org.
    feed_id VARCHAR(60) NULL,
    lang_label VARCHAR(40) NULL,
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

-- Catálogo sob demanda (filmes/séries), a preencher manualmente conforme
-- autorização for obtida — fica vazio por padrão, nunca populado automaticamente.
-- Ver ARQUITETURA.md secao 10.
CREATE TABLE IF NOT EXISTS vod_titles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type ENUM('movie','series') NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT NULL,
    poster_url VARCHAR(500) NULL,
    genre VARCHAR(100) NULL,
    year INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vod_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title_id INT NOT NULL,
    season_number INT NULL,
    episode_number INT NULL,
    episode_title VARCHAR(500) NULL,
    stream_url VARCHAR(1000) NULL,
    -- espelham as colunas equivalentes de streams (canais ao vivo) — o
    -- health-check manual/automático testa VOD junto com TV ao vivo
    is_healthy BOOLEAN NULL,
    consecutive_failures INT NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_vod_item_title FOREIGN KEY (title_id) REFERENCES vod_titles(id) ON DELETE CASCADE,
    KEY idx_title (title_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 1 linha por job do worker, sempre atualizada (nao e historico) -- ultima
-- execucao de fetch_channels/healthcheck/fetch_epg, pro dashboard.
CREATE TABLE IF NOT EXISTS worker_runs (
    job_name VARCHAR(50) PRIMARY KEY,
    last_run_at DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL,
    summary VARCHAR(500) NULL,
    duration_seconds INT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS genre_keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    genre VARCHAR(100) NOT NULL,
    keyword VARCHAR(200) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_genre (genre)
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
