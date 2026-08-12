"""Command-line interface for DharmaPostAI Bot."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import ConfigurationError, load_settings
from .server import serve
from .service import DharmaPostService

LOGGER = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dharma-post-ai",
        description="Generate Khmer Dharma reflections, render posters, store them in Supabase, and publish to Facebook.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    once = subparsers.add_parser("once", help="Generate one Dharma poster and save it as a review record.")
    once.add_argument("--topic", default="សតិ និងសេចក្តីមេត្តា", help="Khmer or English topic for the reflection.")
    once.add_argument(
        "--publish",
        action="store_true",
        help="Immediately publish the new post to Facebook; this bypasses the normal review queue.",
    )

    approved = subparsers.add_parser("publish-approved", help="Publish records approved in Supabase.")
    approved.add_argument("--limit", type=int, default=None, help="Maximum approved records to publish.")

    approve = subparsers.add_parser("approve", help="Approve one pending Supabase record by UUID.")
    approve.add_argument("post_id", help="UUID of a record with pending_review status.")

    subparsers.add_parser("serve", help="Run the daily scheduler plus a /health endpoint.")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    _configure_logging(settings.log_level)
    service = DharmaPostService(settings)

    if args.command == "once":
        result = await service.generate(topic=args.topic, publish_immediately=args.publish)
        print(f"record_id={result.post.id}")
        print(f"status={'published' if result.was_published else result.post.status}")
        print(f"poster={result.poster.output_path}")
        return 0

    if args.command == "publish-approved":
        if args.limit is not None and args.limit < 1:
            raise ConfigurationError("--limit must be at least 1.")
        count = await service.publish_approved(limit=args.limit)
        print(f"published_count={count}")
        return 0

    if args.command == "approve":
        await service.approve(args.post_id)
        print(f"approved_record_id={args.post_id}")
        return 0

    if args.command == "serve":
        await serve(settings)
        return 0

    raise ConfigurationError(f"Unsupported command: {args.command}")


def main() -> None:
    args = _parser().parse_args()
    try:
        code = asyncio.run(_run(args))
    except (ConfigurationError, RuntimeError, ValueError) as error:
        logging.basicConfig(format="%(asctime)s %(levelname)s - %(message)s")
        LOGGER.error("DharmaPostAI stopped: %s", error)
        code = 2
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
