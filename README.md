# DharmaPostAI Bot

**DharmaPostAI Bot** is a production-oriented Python service that generates a Khmer Dharma reflection with Gemini, renders a polished 1200 × 1200 JPEG poster, stores the content lifecycle in Supabase, and publishes an approved poster to a Facebook Page. It is designed to make sharing wholesome content reliable while keeping human review available before public posting.

> **Source-integrity policy:** Gemini is instructed never to invent a Pali Canon citation or describe generated text as a verbatim Buddhavacana. If an exact canonical source is not certain, the post is labelled `គតិធម៌សម្រាប់ពិចារណា`. Human review remains essential before public publication.

## System workflow

```text
Gemini API → validated Khmer Dharma JSON → Pillow poster (1200×1200 JPEG)
    → Supabase draft/review record → Facebook Page photo post → Supabase publication status
```

| Component | Responsibility | Key protection |
|---|---|---|
| Gemini content engine | Produces structured Khmer Dharma content with a source-integrity instruction | API key stays in environment variables only. |
| Poster renderer | Creates a square, double-gold-bordered JPEG using the bundled Khmer font | Text is measured and wrapped before rendering. |
| Supabase repository | Stores draft, approval, failure, and publication state | The server-only service-role key must never be exposed to a browser. |
| Facebook publisher | Uploads the JPEG and caption to `/{page_id}/photos` | Page token is loaded only from the server environment. |
| Scheduler | Runs a daily job at the configured Cambodia time | Daily limit and single-instance protections reduce duplicate posts. |

## Project layout

```text
.
├── src/dharma_post_ai/
│   ├── cli.py                 # Commands: generate, approve, publish, serve
│   ├── config.py              # Validated environment settings
│   ├── gemini_engine.py       # Gemini structured-output generation
│   ├── poster.py              # Standard poster renderer
│   ├── repository.py          # Supabase data operations
│   ├── facebook.py            # Meta Page photo publishing
│   ├── service.py             # End-to-end business workflow
│   └── server.py              # Scheduler and /health service
├── supabase/migrations/
│   └── 001_create_dharma_posts.sql
├── tests/                     # Automated unit tests
├── .env.example               # Secret-free configuration template
├── render.yaml                # Daily Cron deployment at 07:00 Cambodia time
└── render-web.yaml            # Optional always-on scheduler deployment
```

## Prerequisites

You need Python 3.11 or newer, a Google Gemini API key, a Supabase project, and a Meta Page access token authorized to publish to your Page. Meta documents the Page Photos publishing edge at `POST /{page_id}/photos`; the token must be associated with a person who can perform the required Page task and permissions.[^meta]

The project uses the current `google-genai` library, which Google lists as its production-ready Python SDK.[^gemini]

## Initial setup

### 1. Create the Supabase table

Open **Supabase Dashboard → SQL Editor**, paste the complete contents of [`supabase/migrations/001_create_dharma_posts.sql`](supabase/migrations/001_create_dharma_posts.sql), and run it. The migration creates the `dharma_posts` table, its lifecycle statuses, indexes, timestamp trigger, and a safe failure-recording function.

### 2. Configure secrets

Copy the template and fill in your own secrets. Do not commit the resulting `.env` file.

```bash
cp .env.example .env
```

| Variable | Purpose | Required for |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API authentication | Every content generation run |
| `SUPABASE_URL` | Supabase project URL | Every content generation run |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side database access | Every content generation run |
| `FACEBOOK_PAGE_ID` | Target Facebook Page | Publishing only |
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Page token with publishing permissions | Publishing only |
| `POST_TIME` | Daily `HH:MM` schedule in `TIMEZONE` | Always-on scheduler only |
| `AUTO_PUBLISH` | Enables direct publishing without an approval queue | Automatic publishing only |
| `REQUIRE_APPROVAL` | Keeps generated content in review before Facebook publication | Safer default mode |

### 3. Install and validate

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

## Daily editorial workflow

The default settings are deliberately safe: `AUTO_PUBLISH=false` and `REQUIRE_APPROVAL=true`. The command below generates content, renders a poster in `output/`, and stores the record in Supabase with status `pending_review`. It does **not** publish to Facebook.

```bash
python -m dharma_post_ai once --topic "សតិ និងសេចក្តីមេត្តា"
```

Review the title, source label, quote/reflection, explanation, and poster in Supabase. After correcting or verifying the content, change its `status` from `pending_review` to `approved` in Supabase Table Editor. Then publish the approved record:

```bash
python -m dharma_post_ai publish-approved --limit 1
```

For a deliberate one-time direct Facebook publishing test, use the explicit `--publish` flag. This bypasses the review queue and should only be used after confirming the Page token and post format.

```bash
python -m dharma_post_ai once --topic "មេត្តាករុណា" --publish
```

## Automatic publishing choices

Both choices below run automatically without keeping your personal computer open. Deploy **only one**; deploying both would create duplicate daily work.

| Approach | Tradeoffs | Cost | Setup complexity |
|---|---|---|---|
| **Daily scheduled run** using [`render.yaml`](render.yaml) | Starts, generates one post at 07:00 Cambodia time, publishes, then stops. It has no permanent health URL. This is best for one predictable daily post. | Depends on the selected hosting provider’s cron-job pricing. | Lower; configure the secrets once. |
| **Always-on bot service** using [`render-web.yaml`](render-web.yaml) | Keeps the scheduler in memory and exposes `/health`. It is useful when you need an uptime endpoint or intend to add an admin API later. | Depends on the selected always-on hosting plan. | Higher; the process must remain continuously hosted. |

The included default `render.yaml` is configured for a direct daily post at **07:00 Asia/Phnom_Penh**, which is **00:00 UTC**. The long-running `serve` mode can also be run on any host that keeps a Python process alive:

```bash
python -m dharma_post_ai serve
# GET http://localhost:8080/health
```

## Commands

| Command | Result |
|---|---|
| `python -m dharma_post_ai once` | Generates a review draft and its poster. |
| `python -m dharma_post_ai once --topic "..."` | Generates a review draft for a specific theme. |
| `python -m dharma_post_ai once --publish` | Generates and immediately publishes one post. |
| `python -m dharma_post_ai approve <UUID>` | Changes a pending record to `approved`. |
| `python -m dharma_post_ai publish-approved --limit 1` | Publishes approved records subject to the daily limit. |
| `python -m dharma_post_ai serve` | Starts the in-process scheduler and health endpoint. |

## Safety and operational notes

The bot logs status messages but never logs API keys or access tokens. Keep `.env` local and set production secrets in the hosting provider’s encrypted environment-variable panel. The Supabase service-role key bypasses row-level security and must never be inserted in website JavaScript, a mobile app, screenshots, or GitHub commits.

Gemini output is validated for required fields, image rendering enforces a standard square size, Facebook uploads have a timeout and a 10 MB size guard, and every publishing failure is written back to Supabase. Before enabling unattended posts, manually review several generated posts to confirm Khmer language quality and doctrinal/source accuracy for your Page.

## References

[^gemini]: [Google GenAI SDK libraries documentation](https://ai.google.dev/gemini-api/docs/libraries)
[^meta]: [Meta Graph API: Page Photos reference](https://developers.facebook.com/docs/graph-api/reference/page/photos/)
