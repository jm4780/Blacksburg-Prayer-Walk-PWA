-- Blacksburg Prayer Walk - shared coverage schema
--
-- Runs on Postgres 16 + PostGIS 3.4. Nothing here is Supabase-specific, and
-- nothing here is local-specific: the same file applies unchanged to a Supabase
-- project. Hosting is a deployment choice, not an architectural one.
--
-- PRIVACY, enforced by the shape of the schema rather than by policy text:
-- there is no table in which an individual location can be stored. No trace, no
-- fix, no coordinate is ever written. A walk records which segments a person
-- confirmed, and nothing else. What the town sees is an aggregate over those
-- confirmations.

create extension if not exists postgis;

-- ---------------------------------------------------------------------------
-- the network (immutable between builds)
-- ---------------------------------------------------------------------------
create table if not exists segment (
    seg_id      integer primary key,
    name        text        not null,
    ref         text,
    class       text        not null,
    length_m    double precision not null check (length_m > 0),
    node_a      text        not null,
    node_b      text        not null,
    -- Homes stay null until an authoritative address source is wired in. The
    -- counter is built and plumbed; it simply has nothing truthful to show yet,
    -- so it shows nothing. A number we cannot stand behind is worse than a gap.
    homes       integer,
    geom        geometry(LineString, 4326) not null
);

create index if not exists segment_geom_idx on segment using gist (geom);
create index if not exists segment_name_idx on segment (name);

-- ---------------------------------------------------------------------------
-- who walked (no accounts, no passwords)
-- ---------------------------------------------------------------------------
create table if not exists device (
    device_id   uuid primary key,
    -- Optional. Someone who never types a name is a full participant.
    display_name text,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- a walk, once the walker has confirmed it
-- ---------------------------------------------------------------------------
create table if not exists walk (
    walk_id       uuid primary key,
    device_id     uuid not null references device (device_id),
    -- The client mints this before the walk and reuses it on every retry, so a
    -- walk queued in airplane mode and flushed three times still commits once.
    client_walk_id text not null,
    started_at    timestamptz,
    confirmed_at  timestamptz not null default now(),
    unique (device_id, client_walk_id)
);

create table if not exists walk_segment (
    walk_id uuid    not null references walk (walk_id) on delete cascade,
    seg_id  integer not null references segment (seg_id),
    primary key (walk_id, seg_id)
);

-- ---------------------------------------------------------------------------
-- coverage: the shared map
-- ---------------------------------------------------------------------------
-- One row per segment that has ever been prayed over. The primary key is what
-- makes "every street counts exactly once, ever" true by construction: a second
-- walker covering the same street inserts nothing. Their walk still records
-- that they walked it; the town's total does not move twice.
create table if not exists coverage (
    seg_id           integer primary key references segment (seg_id),
    first_walk_id    uuid not null references walk (walk_id),
    first_covered_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- commit a confirmed walk, atomically and idempotently
-- ---------------------------------------------------------------------------
create or replace function commit_walk(
    p_device_id      uuid,
    p_client_walk_id text,
    p_display_name   text,
    p_started_at     timestamptz,
    p_seg_ids        integer[]
) returns uuid
language plpgsql
as $$
declare
    v_walk_id uuid;
begin
    insert into device (device_id, display_name)
    values (p_device_id, nullif(p_display_name, ''))
    on conflict (device_id) do update
        set display_name = coalesce(excluded.display_name, device.display_name);

    -- Replaying the same client_walk_id returns the original walk untouched.
    select walk_id into v_walk_id
    from walk
    where device_id = p_device_id and client_walk_id = p_client_walk_id;

    if v_walk_id is not null then
        return v_walk_id;
    end if;

    v_walk_id := gen_random_uuid();
    insert into walk (walk_id, device_id, client_walk_id, started_at)
    values (v_walk_id, p_device_id, p_client_walk_id, p_started_at);

    insert into walk_segment (walk_id, seg_id)
    select v_walk_id, s.seg_id
    from unnest(p_seg_ids) as s(seg_id)
    where exists (select 1 from segment where segment.seg_id = s.seg_id)
    on conflict do nothing;

    insert into coverage (seg_id, first_walk_id)
    select seg_id, v_walk_id from walk_segment where walk_id = v_walk_id
    on conflict (seg_id) do nothing;

    return v_walk_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- what the town sees
-- ---------------------------------------------------------------------------
-- Percent complete is weighted by street length, not by segment count, so a
-- long road counts for more than a cul-de-sac.
create or replace view progress as
select
    (select count(*) from coverage)                                    as segments_covered,
    (select count(*) from segment)                                     as segments_total,
    (select coalesce(sum(s.length_m), 0)
       from coverage c join segment s using (seg_id))                  as covered_m,
    (select sum(length_m) from segment)                                as total_m,
    (select coalesce(sum(s.homes), 0)
       from coverage c join segment s using (seg_id))                  as homes_covered,
    (select sum(homes) from segment)                                   as homes_total;
