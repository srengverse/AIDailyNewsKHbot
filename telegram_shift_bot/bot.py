"""
Telegram Shift Reminder Bot

ផ្ញើសាររំលឹកវេនប្រចាំថ្ងៃទៅ Telegram Group នៅម៉ោង 05:30
ដោយប្រើ python-telegram-bot និង APScheduler។
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID_TEXT = os.getenv("GROUP_CHAT_ID", "").strip()
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Phnom_Penh").strip()
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "5"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "30"))

if not BOT_TOKEN:
    raise RuntimeError("មិនទាន់មាន BOT_TOKEN ក្នុងឯកសារ .env")

try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception as exc:
    raise RuntimeError(f"TIMEZONE មិនត្រឹមត្រូវ៖ {TIMEZONE_NAME}") from exc

try:
    GROUP_CHAT_ID = int(GROUP_CHAT_ID_TEXT) if GROUP_CHAT_ID_TEXT else None
except ValueError as exc:
    raise RuntimeError("GROUP_CHAT_ID ត្រូវតែជាលេខ ដូចជា -1001234567890") from exc

# -----------------------------------------------------------------------------
# Weekly shift data
# Python weekday: Monday=0 ... Sunday=6
# -----------------------------------------------------------------------------

WEEKLY_SHIFTS: dict[int, dict[str, object]] = {
    0: {"day": "ចន្ទ", "names": ["ឈិន ទីប៉ា", "ឈិនត ពៅ"]},
    1: {"day": "អង្គារ", "names": ["ឡេង ឡៅស្រេង", "ធី គិមអិន", "កសិន ពីសាល"]},
    2: {"day": "ពុធ", "names": ["អឿន សុផល", "ឡាត់ វត្តនា", "ឆាន វិបុល"]},
    3: {"day": "ព្រហស្បតិ៍", "names": ["សុត្រ លីស៊ីប៉ាវ", "ឡេង វឌ្ឍនា", "ភាព ចិណ្ណា"]},
    4: {"day": "សុក្រ", "names": ["កុយ ធារិទ្ធ", "លីន សុភា"]},
    5: {"day": "សៅរ៍", "names": ["ចុន វណ្នី", "ស៊ាន ដានី"]},
    6: {"day": "អាទិត្យ", "names": ["សេង សីហា", "ឈិន ឆាយា", "ឈុត តុលា"]},
}

# Global scheduler instance. It is started after the Telegram application starts.
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("shift-reminder-bot")


# -----------------------------------------------------------------------------
# Message helpers
# -----------------------------------------------------------------------------


def format_names(names: list[str]) -> str:
    """បម្លែងបញ្ជីឈ្មោះទៅជាប្រយោគដែលអានងាយ។"""
    people = [f"ព្រះតេជគុណ {name}" for name in names]

    if len(people) == 1:
        return people[0]
    if len(people) == 2:
        return f"{people[0]} និង {people[1]}"
    return ", ".join(people[:-1]) + f" និង {people[-1]}"


def build_reminder_message(weekday: int) -> str:
    """បង្កើតសាររំលឹកសម្រាប់ថ្ងៃមួយ។"""
    shift = WEEKLY_SHIFTS[weekday]
    day = str(shift["day"])
    names = list(shift["names"])
    people_text = format_names(names)

    return (
        "អរុណសួស្តីព្រះតេជគុណ និងសមាជិកក្នុងក្រុមទាំងអស់។\n\n"
        f"សូមរំលឹកថា ថ្ងៃនេះគឺជាវេនរបស់ {people_text} "
        "សូមនិមន្តមកសម្អាតកុដិ តាមវេនដែលបានរៀបចំ។\n\n"
        "ព្រះតេជគុណដែលនៅក្បែរ សូមមេត្តាជួយជម្រាប និងក្រើនរំលឹក "
        "ព្រះតេជគុណដែលមានវេនផង។\n\n"
        "សូមអរព្រះគុណ។"
    )


def build_week_message() -> str:
    """បង្កើតតារាងវេនសម្រាប់ command /week។"""
    lines = ["តារាងវេនសម្អាតកុដិប្រចាំសប្ដាហ៍៖", ""]
    for weekday in range(7):
        shift = WEEKLY_SHIFTS[weekday]
        names = " និង ".join(str(name) for name in shift["names"])
        lines.append(f"{shift['day']} ០៥:៣០ ព្រឹក — {names}")
    return "\n".join(lines)


def get_current_weekday() -> int:
    return datetime.now(TIMEZONE).weekday()


# -----------------------------------------------------------------------------
# Scheduled job
# -----------------------------------------------------------------------------

async def send_daily_reminder(application: Application) -> None:
    """ផ្ញើសារទៅ Group មួយដងក្នុងមួយថ្ងៃ។"""
    if GROUP_CHAT_ID is None:
        logger.warning("មិនអាចផ្ញើសារ៖ GROUP_CHAT_ID មិនទាន់កំណត់")
        return

    weekday = get_current_weekday()
    message = build_reminder_message(weekday)

    try:
        await application.bot.send_message(chat_id=GROUP_CHAT_ID, text=message)
        logger.info("បានផ្ញើសាររំលឹកសម្រាប់ថ្ងៃ %s", WEEKLY_SHIFTS[weekday]["day"])
    except Exception:
        logger.exception("ផ្ញើសារទៅ Group មិនបានសម្រេច")


# -----------------------------------------------------------------------------
# Telegram commands
# -----------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "សួស្តី! ខ្ញុំជា Bot រំលឹកវេនសម្អាតកុដិ។\n\n"
        "Commands ដែលអាចប្រើបាន៖\n"
        "/today - មើលសារវេនថ្ងៃនេះ\n"
        "/week - មើលតារាងវេន ៧ ថ្ងៃ\n"
        "/test - សាកល្បងផ្ញើសាររំលឹក\n"
        "/chatid - មើល Chat ID របស់ Group នេះ"
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    weekday = get_current_weekday()
    await update.message.reply_text(build_reminder_message(weekday))


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(build_week_message())


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return

    chat_type = chat.type
    await update.message.reply_text(
        f"Chat ID: {chat.id}\n"
        f"Chat type: {chat_type}\n\n"
        "សូមយកលេខ Chat ID នេះទៅដាក់ក្នុង .env ជា GROUP_CHAT_ID។"
    )


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ផ្ញើសារសាកល្បងទៅ chat បច្ចុប្បន្ន។"""
    weekday = get_current_weekday()
    await update.message.reply_text(
        "សារសាកល្បង៖\n\n" + build_reminder_message(weekday)
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram update error: %s", context.error, exc_info=context.error)


# -----------------------------------------------------------------------------
# Application lifecycle
# -----------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    """ចាប់ផ្ដើម APScheduler បន្ទាប់ពី Telegram application បានត្រៀមរួច។"""
    scheduler.add_job(
        send_daily_reminder,
        trigger=CronTrigger(
            day_of_week="mon-sun",
            hour=REMINDER_HOUR,
            minute=REMINDER_MINUTE,
            timezone=TIMEZONE,
        ),
        args=[application],
        id="daily_shift_reminder",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: every day at %02d:%02d (%s)",
        REMINDER_HOUR,
        REMINDER_MINUTE,
        TIMEZONE_NAME,
    )


async def post_shutdown(application: Application) -> None:
    """បិទ scheduler ឲ្យបានត្រឹមត្រូវពេល Bot ឈប់ដំណើរការ។"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def build_application() -> Application:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("chatid", chat_id_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    application = build_application()
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
