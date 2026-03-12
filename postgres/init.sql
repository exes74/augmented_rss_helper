-- ============================================================
-- Initialisation de la base de données RSS Veille
-- ============================================================

-- Extension pour les UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Index de recherche full-text
CREATE EXTENSION IF NOT EXISTS "unaccent";

-- Commentaire sur la base
COMMENT ON DATABASE rssveille IS 'Base de données de l application RSS Veille';
