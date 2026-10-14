-- Search by meaning now scans every chunk instead of using the HNSW index.
--
-- HNSW is approximate: it looks at a limited number of candidates and
-- applies any filter afterwards. With a filter on `kind` it sometimes
-- returned fewer rows than asked for, or none. The knowledge base is a
-- few hundred chunks and is planned to stay in the thousands, where an
-- exact scan takes milliseconds and always gives the true nearest rows.
--
-- Bring an index back, in a new migration, if the table grows past some
-- tens of thousands of rows.

drop index if exists kb_chunks_embedding_idx;
