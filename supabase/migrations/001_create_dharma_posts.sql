-- DharmaPostAI Bot - Supabase database schema
-- Run this file in Supabase Dashboard > SQL Editor before running the bot.

create extension if not exists pgcrypto;

do $$
begin
  if not exists (
    select 1 from pg_type where typname = 'dharma_post_status'
  ) then
    create type public.dharma_post_status as enum (
      'pending_review',
      'approved',
      'published',
      'failed',
      'rejected'
    );
  end if;
end;
$$;

create table if not exists public.dharma_posts (
  id uuid primary key default gen_random_uuid(),
  topic text not null default 'សតិ និងសេចក្តីមេត្តា',
  title text not null check (char_length(title) between 1 and 1300),
  pali_source text not null check (char_length(pali_source) between 1 and 2000),
  buddhavacana text not null check (char_length(buddhavacana) between 1 and 6000),
  explanation text not null check (char_length(explanation) between 1 and 8000),
  reflection_question text not null check (char_length(reflection_question) between 1 and 2000),
  hashtags text not null check (char_length(hashtags) between 1 and 2000),
  status public.dharma_post_status not null default 'pending_review',
  facebook_posted boolean not null default false,
  facebook_post_id text unique,
  poster_path text,
  poster_checksum text,
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  scheduled_for timestamptz,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint published_post_requires_timestamp check (
    status <> 'published' or (facebook_posted = true and published_at is not null)
  )
);

create index if not exists dharma_posts_status_created_at_idx
  on public.dharma_posts (status, created_at asc);

create index if not exists dharma_posts_published_at_idx
  on public.dharma_posts (published_at desc);

create or replace function public.set_dharma_posts_updated_at()
returns trigger
language plpgsql
security invoker
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_dharma_posts_updated_at on public.dharma_posts;
create trigger set_dharma_posts_updated_at
before update on public.dharma_posts
for each row execute function public.set_dharma_posts_updated_at();

create or replace function public.record_dharma_post_failure(
  post_uuid uuid,
  failure_message text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.dharma_posts
  set status = 'failed',
      facebook_posted = false,
      attempts = attempts + 1,
      last_error = left(coalesce(failure_message, 'Unknown publishing error'), 1500)
  where id = post_uuid;
end;
$$;

-- The bot uses SUPABASE_SERVICE_ROLE_KEY on the server. Keep RLS enabled so public clients
-- cannot read or write this content. Do not expose the service role key to a browser or repository.
alter table public.dharma_posts enable row level security;

revoke all on table public.dharma_posts from anon, authenticated;
revoke all on function public.record_dharma_post_failure(uuid, text) from public, anon, authenticated;
grant execute on function public.record_dharma_post_failure(uuid, text) to service_role;
