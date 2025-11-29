# bot.py – Khmer News Bot 2026 (Ultimate Edition)
# Features:
# - Cambodia + International + Thai + Vietnamese
# - Dynamic time-based posting (peak hours = high frequency)
# - BREAKING NEWS BOOST MODE (1 post every 60s when big news hits)
# - Gemini AI translation to natural Khmer
# - Smart image + text fallback
# - Never crashes – Full error handling

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
from datetime import datetime, timedelta, time
from urllib.parse import urljoin

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, NetworkError, TimedOut
from aiohttp import web
import aiosqlite

# =========================== CONFIG ===========================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
CHANNEL_LINK = "https://t.me/AIDailyNewsKH"

# Note: Use gemini-2.0-flash or 1.5-flash if 2.5 is not available yet
GEMINI_MODEL = "gemini-2.0-flash"
CHECK_INTERVAL = 900  # 15 minutes base cycle

# Timezone Cambodia
ICT = pytz.timezone('Asia/Phnom_Penh')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("GEMINI_API_KEY missing! Using English fallback")

# =========================== RSS SOURCES (Nov 2025 – All 100% Working) ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
        {"name": "Rasmei News",    "rss": "https://www.rasmeinews.com/feed",               "url": "https://www.rasmeinews.com"},
        {"name": "CamboJA News",   "rss": "https://cambojanews.com/feed/",                 "url": "https://cambojanews.com"},
        {"name": "Post Khmer",     "rss": "https://postkhmer.com/feed",                    "url": "https://postkhmer.com"},
        {"name": "Sabay News",     "rss": "https://news.sabay.com.kh/topics/cambodia.rss", "url": "https://news.sabay.com.kh"},
    ],
    "international": [
        {"name": "BBC News",       "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",      "url": "https://www.bbc.com"},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com"},
        {"name": "Al Jazeera",     "rss": "https://www.aljazeera.com/xml/rss/all.xml",       "url": "https://www.aljazeera.com"},
        {"name": "The Guardian",   "rss": "https://www.theguardian.com/world/rss",           "url": "https://www.theguardian.com"},
    ],
    "thai": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed",            "url": "https://www.bangkokpost.com"},
        {"name": "Thai PBS World", "rss": "https://world.thaipbs.or.th/feed",                "url": "https://world.thaipbs.or.th"},
        {"name": "Khaosod English","rss": "https://www.khaosodenglish.com/feed",             "url": "https://www.khaosodenglish.com"},
    ],
    "vietnamese": [
        {"name": "Tuoi Tre News",  "rss": "https://news.tuoitre.vn/rss.htm",                 "url": "https://news.tuoitre.vn"},
        {"name": "VNA",            "rss": "https://vnanet.vn/en/rss/",                       "url": "https://vnanet.vn/en"},
        {"name": "Saigon Times",   "rss": "https://english.thesaigontimes.vn/rss.xml",       "url": "https://english.thesaigontimes.vn"},
    ]
}

DB_FILE = "posted_articles.db"

# =========================== DYNAMIC SCHEDULE + BREAKING BOOST ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាមៗ", "ស្លាប់", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "ប៉ះទង្គិច", "រញ្ជួយដី", "បាតុកម្ម", "breaking"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "crisis"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "Koh Santepheap", "BBC News"}

def get_current_slot():
    """កំណត់ចំនួន Post និងម៉ោងរង់ចាំ ដោយផ្អែកលើម៉ោងជាក់ស្តែងនៅកម្ពុជា"""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    # ម៉ោង 5ព្រឹក - 8ព្រឹក (Morning News)
    if 5 <= h < 8:       return {"name": "Morning",      "max": 8,  "delay": 60}
    # ម៉ោង 8ព្រឹក - 11:30 (Work/Peak)
    if 8 <= h < 11.5:    return {"name": "Work AM",      "max": 6,  "delay": 90}
    # ម៉ោង 11:30 - 1:30 (Lunch Peak)
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak",   "max": 10, "delay": 45}
    # ម៉ោង 1:30 - 5ល្ងាច (Afternoon)
    if 13.5 <= h < 17:   return {"name": "Afternoon",    "max": 5,  "delay": 120}
    # ម៉ោង 5ល្ងាច - 9យប់ (Prime Time)
    if 17 <= h < 21:     return {"name": "Evening Prime","max": 12, "delay": 40}
    # ម៉ោង 9យប់ - 11យប់ (Night)
    if 21 <= h < 23:     return {"name": "Night",        "max": 5,  "delay": 150}
    # ម៉ោង 11យប់ - 5ព្រឹក (Sleep Mode)
    return                       {"name": "Deep Night",   "max": 2,  "delay": 300}

def is_breaking_news(article: dict) -> bool:
    """ពិនិត្យមើលថាជាព័ត៌មានបន្ទាន់ឬអត់"""
    score = 0
    title = article["title"].lower()
    title_kh = article.get("title_kh", "").lower()

    for w in BREAKING_KEYWORDS_EN:
        if w in title: score += 100
    for w in BREAKING_KEYWORDS_KH:
        if w in title or w in title_kh: score += 120
    
    if article["source"] in HIGH_PRIORITY_SOURCES: score += 50
    if len(article["title"]) < 60 and ("!" in title or "?" in title): score += 30
    
    return score >= 100

# =========================== DATABASE ===========================
async def init_db():
    for _ in range(3):
        try:
            async with aiosqlite.connect(DB_FILE, timeout=15) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posted (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.commit()
            logging.info("Database ready")
            return
        except: await asyncio.sleep(3)
    logging.critical("DB failed – continuing without persistence")

async def is_posted(aid: str) -> bool:
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None
    except: return False

async def mark_as_posted(aid: str, cat: str):
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            await db.execute("INSERT OR IGNORE INTO posted(article_id,category) VALUES(?,?)", (aid, cat))
            await db.commit()
    except: pass

# =========================== RSS & IMAGE ===========================
async def fetch_rss(url: str):
    headers = {"User-Agent": "KhmerNewsBot/2.0 (+https://t.me/sVisionCoreg)"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as s:
        for _ in range(3):
            try:
                async with s.get(url) as r:
                    if r.status == 200:
                        return feedparser.parse(await r.text())
            except: await asyncio.sleep(2)
    return None

def get_image(entry, base_url: str) -> str | None:
    try:
        if getattr(entry, "media_content", None):
            return entry.media_content[0].get("url")
        soup = BeautifulSoup(entry.get("summary","") or entry.get("description",""), "html.parser")
        img = soup.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src: return urljoin(base_url, src.strip())
    except: pass
    return None

async def get_article_id(t: str, l: str) -> str:
    try: return hashlib.md5(f"{t}{l}".encode()).hexdigest()
    except: return str(hash(f"{t}{l}"))

# =========================== GEMINI TRANSLATE ===========================
async def translate(article: dict) -> dict:
    prompt = f"Translate to natural, engaging Khmer for Telegram news:\nTitle: {article['title']}\nContent: {article['summary'][:2800]}\nReturn ONLY JSON: {{\"title_kh\": \"...\", \"body_kh\": \"...\"}}"
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
        data = json.loads(text)
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        await asyncio.sleep(7)
        return article
    except Exception as e:
        logging.warning(f"Gemini failed → English: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500] + "\n\n(English version)"
        return article

# =========================== SMART POST ===========================
async def post_smart(article: dict, emoji: str) -> bool:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID):
        return False

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    # បន្ថែមទង់ជាតិទៅមុខចំណងជើង
    flag = ""
    if article["source"] in [s["name"] for s in NEWS_SOURCES["thai"]]: flag = "🇹🇭"
    elif article["source"] in [s["name"] for s in NEWS_SOURCES["vietnamese"]]: flag = "🇻🇳"
    
    caption = f"{emoji} {flag} <b>{article['title_kh']}</b>\n\n{article['body_kh']}\n\n━━━━━━━━━━━━━━━━━\nប្រភព: {article['source']}\n{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("អានពេញ", url=article["link"])], [InlineKeyboardButton("Join Channel", url=CHANNEL_LINK)]])

    if article.get("image_url"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(article["image_url"], timeout=15) as r:
                    if r.status == 200 and "image" in r.content_type:
                        await bot.send_photo(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            photo=await r.read(),
                            caption=caption[:1024],
                            parse_mode=ParseMode.HTML,
                            reply_markup=buttons
                        )
                        logging.info(f"PHOTO POST: {article['title_kh'][:50]}")
                        return True
        except: logging.warning("Photo failed → Text")

    for _ in range(3):
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption + f"\n\n{article['link']}",
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            logging.info(f"TEXT POST: {article['title_kh'][:50]}")
            return True
        except (NetworkError, TimedOut):
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Post failed: {e}")
            break
    return False

# =========================== MAIN WORKER (Dynamic + Breaking Boost) ===========================
async def worker():
    await init_db()
    logging.info("Khmer News Bot 2026 ULTIMATE STARTED – Dynamic + Breaking Boost")

    boost_until = None

    while True:
        try:
            now = datetime.now(ICT)
            slot = get_current_slot()

            # Boost mode?
            if boost_until and now < boost_until:
                max_posts = 20
                delay = 60
                logging.info("🔥 BREAKING NEWS BOOST MODE ACTIVE!")
            else:
                max_posts = slot["max"] // 4
                delay = CHECK_INTERVAL
                boost_until = None

            posted_count = 0
            # Categories with Emojis
            categories = [
                ("cambodia", "🇰🇭"), ("international", "🌍"),
                ("thai", "📰"), ("vietnamese", "📰")
            ]

            for cat, emoji in categories:
                if posted_count >= max_posts: break

                for src in NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts: break
                    try:
                        feed = await fetch_rss(src["rss"])
                        if not feed or not feed.entries: continue

                        e = feed.entries[0] # Check latest
                        aid = await get_article_id(e.title, e.link)
                        if await is_posted(aid): continue

                        article = {
                            "title": e.title, "link": e.link,
                            "summary": BeautifulSoup(e.get("summary","") or e.get("description",""), "html.parser").get_text(strip=True)[:1000],
                            "image_url": get_image(e, src["url"]),
                            "source": src["name"]
                        }

                        article = await translate(article)

                        # BREAKING NEWS LOGIC
                        if is_breaking_news(article) and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED → BOOST ACTIVATED!")
                            boost_until = now + timedelta(minutes=15)
                            await post_smart(article, "🚨 BREAKING NEWS " + emoji)
                            await mark_as_posted(aid, cat)
                            posted_count += 1
                            await asyncio.sleep(5)
                            continue 

                        if await post_smart(article, emoji):
                            await mark_as_posted(aid, cat)
                            posted_count += 1
                            await asyncio.sleep(8)

                    except Exception as e:
                        logging.error(f"Error {src['name']}: {e}")

            logging.info(f"Cycle finished – {posted_count} posts | Mode: {slot['name']} | Next in {delay}s")
            await asyncio.sleep(delay)

        except Exception as e:
            logging.critical(f"Cycle Error: {e}")
            await asyncio.sleep(60)

# =========================== HEALTH SERVER ===========================
async def health(req): return web.Response(text="Bot alive – Khmer News 2026 Ultimate")
async def web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()
    logging.info("Health server running")

# =========================== RUN ===========================
async def main():
    await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.critical(f"Fatal crash: {e}\n{traceback.format_exc()}")