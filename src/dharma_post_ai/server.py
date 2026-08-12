"""Optional long-running scheduler and health-check HTTP service."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .service import DharmaPostService

LOGGER = logging.getLogger(__name__)


def _build_app(settings: Settings, scheduler: AsyncIOScheduler) -> web.Application:
    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "service": "DharmaPostAI",
                "time": datetime.now(settings.timezone).isoformat(),
                "timezone": settings.timezone_name,
                "scheduled_time": settings.post_time,
                "approval_required": settings.require_approval,
                "scheduler_running": scheduler.running,
            }
        )

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="DharmaPostAI Bot is running. Use /health for status.")

    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    return app


async def serve(settings: Settings) -> None:
    """Run the scheduler and a lightweight health endpoint until the process is stopped."""
    settings.validate_for_generation()
    if not settings.require_approval:
        settings.validate_for_publishing()

    service = DharmaPostService(settings)
    hour, minute = settings.post_hour_and_minute
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        service.scheduled_cycle,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily-dharma-post",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()

    app = _build_app(settings, scheduler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()

    LOGGER.info(
        "DharmaPostAI scheduler is running. Daily job: %02d:%02d %s; health endpoint port %s.",
        hour,
        minute,
        settings.timezone_name,
        settings.port,
    )
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
