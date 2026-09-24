-- Sessão "só de reprodução": criada pelo bilhete de uso único quando o site
-- HTTPS manda o usuário pro play.exposite.com.br (HTTP puro). Como o cookie
-- desse domínio trafega sem criptografia, a sessão não pode ter poder de admin.
ALTER TABLE admin_sessions
    ADD COLUMN play_only BOOLEAN NOT NULL DEFAULT FALSE;
