-- First schema: accounts and history, the knowledge base, and markets.
-- See .claude/ARCHITECTURE.md section 6.

create extension if not exists vector;

-- Accounts and history (filled from stage 7 on)

create table users (
    id uuid primary key default gen_random_uuid(),
    email text not null,
    name text not null,
    password_hash text not null,
    created_at timestamptz not null default now()
);
create unique index users_email_key on users (lower(email));

create table conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users (id) on delete cascade,
    mode text not null check (mode in ('write', 'review', 'fix')),
    market_id text,
    timeframe text,
    title text not null default '',
    created_at timestamptz not null default now()
);
create index conversations_user_idx on conversations (user_id, created_at desc);

create table messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations (id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null default '',
    code text,
    findings jsonb,
    created_at timestamptz not null default now()
);
create index messages_conversation_idx on messages (conversation_id, created_at);

-- One row for each pipeline run.
create table runs (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null references messages (id) on delete cascade,
    status text not null,
    attempts integer not null default 0,
    checks jsonb,
    tokens_in integer not null default 0,
    tokens_out integer not null default 0,
    cost_usd numeric(10, 6) not null default 0,
    latency_ms integer,
    model_versions jsonb,
    kb_version integer,
    created_at timestamptz not null default now()
);
create index runs_message_idx on runs (message_id);
create index runs_created_idx on runs (created_at);

create table feedback (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null references messages (id) on delete cascade,
    user_id uuid not null references users (id) on delete cascade,
    rating smallint not null check (rating in (-1, 1)),
    comment text,
    created_at timestamptz not null default now(),
    unique (message_id, user_id)
);

-- Knowledge base. Every row is written by the indexer from the files in
-- /kb; nothing else writes these tables.

create table kb_functions (
    name text primary key,
    key text generated always as (lower(name)) stored unique,
    params jsonb not null,
    is_variadic boolean not null default false,
    returns text not null,
    description text,
    doc_url text not null,
    category text not null,
    since text,
    kb_version integer not null
);

create table kb_builtins (
    name text primary key,
    kind text not null,
    type text not null,
    description text not null,
    aliases text[] not null default '{}',
    kb_version integer not null
);

create table markets (
    id text primary key,
    name text not null,
    exchange text not null,
    timezone text not null,
    sessions jsonb not null,
    dst_rules jsonb not null,
    last_verified date,
    kb_version integer not null
);

-- The text that retrieval searches. The embedding column is sized for
-- text-embedding-3-small; changing the model means a new migration.
create table kb_chunks (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('function', 'concept', 'example', 'mistake', 'error')),
    ref text not null,
    title text not null,
    content text not null,
    tags text[] not null default '{}',
    meta jsonb not null default '{}',
    content_hash text not null,
    embedding vector(1536) not null,
    embedding_model text not null,
    tsv tsvector generated always as (
        setweight(to_tsvector('english', title), 'A')
        || setweight(to_tsvector('english', content), 'B')
    ) stored,
    kb_version integer not null,
    unique (kind, ref)
);
create index kb_chunks_tsv_idx on kb_chunks using gin (tsv);
create index kb_chunks_embedding_idx on kb_chunks using hnsw (embedding vector_cosine_ops);

-- One row: which version of /kb the tables hold.
create table kb_state (
    singleton boolean primary key default true check (singleton),
    kb_version integer not null,
    indexed_at timestamptz not null default now()
);
