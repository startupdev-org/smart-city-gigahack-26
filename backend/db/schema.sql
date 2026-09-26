-- CivicAI schema extras (works without pgvector; install later via scripts/install_pgvector.ps1)
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE INDEX IF NOT EXISTS idx_chunks_tsv_gin
  ON chunks USING gin (tsv);

CREATE OR REPLACE FUNCTION chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
  NEW.tsv :=
    setweight(to_tsvector('simple', unaccent(coalesce(NEW.section, ''))), 'A') ||
    setweight(to_tsvector('simple', unaccent(coalesce(NEW.content, ''))), 'B');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_tsv ON chunks;
CREATE TRIGGER trg_chunks_tsv
  BEFORE INSERT OR UPDATE OF content, section ON chunks
  FOR EACH ROW EXECUTE FUNCTION chunks_tsv_trigger();

-- Backfill tsv for existing rows
UPDATE chunks
SET content = content
WHERE tsv IS NULL;
