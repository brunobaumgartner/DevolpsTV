-- Marca quais tokens de acesso (usuários do app) podem ver conteúdo adulto
-- (canais/filmes/séries/animes com category/genre = "Adulto"). Padrão FALSE
-- para todo token existente e novo -- só o admin liga isso manualmente pro
-- token que ele mesmo usa.
ALTER TABLE access_tokens
  ADD COLUMN sees_adult_content BOOLEAN NOT NULL DEFAULT FALSE;
