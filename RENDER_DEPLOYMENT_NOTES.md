# Render deployment notes

Render Cron Jobs run periodic commands that must exit when each run completes. Their schedule uses a cron expression and all schedule times are UTC. Render guarantees no more than one active run of the same cron job; a later scheduled run is delayed until a current run completes. Cron Jobs do not provide a persistent disk or an HTTP health-check endpoint.

Render Web Services can receive HTTP GET health checks at a configured path. A `/health` response with HTTP 2xx or 3xx within five seconds is considered healthy. This is applicable to the optional `python -m dharma_post_ai serve` command, which keeps the in-process scheduler alive and exposes `/health`.

For DharmaPostAI, deploy exactly one automatic publisher. Use the Cron Job configuration for the single daily run, or use the persistent Web Service scheduler—not both. The database daily limit remains a second-line safeguard, but it is not a substitute for avoiding two schedulers.

Sources:
- https://render.com/docs/cronjobs
- https://render.com/docs/health-checks
