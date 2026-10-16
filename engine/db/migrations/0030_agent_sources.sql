-- Agents bring sources (docs/SOURCES.md). Every source records what kind it is, how it got here (its provenance),
-- where it came from, who added it and when it was fetched. The papers already stored are Europe PMC records
-- resolved from a registry.
ALTER TABLE sources
    ADD COLUMN kind         text NOT NULL DEFAULT 'europepmc' CHECK (kind IN ('europepmc', 'sec', 'url', 'upload')),
    ADD COLUMN provenance   text NOT NULL DEFAULT 'registry' CHECK (provenance IN ('registry', 'fetched', 'uploaded')),
    ADD COLUMN url          text,
    ADD COLUMN content_type text,
    ADD COLUMN added_by     bigint REFERENCES agents(id),
    ADD COLUMN fetched_at   timestamptz;

-- a URL is stored once: adding it again returns the stored source, whose text never changes under claims
CREATE UNIQUE INDEX sources_url ON sources (url) WHERE url IS NOT NULL;
