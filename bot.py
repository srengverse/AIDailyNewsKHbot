# bot.py – Khmer News Bot 2026 (Improved Version)
# Improvements:
# - Better async handling
# - Rate limit protection
# - Memory optimization
# - Enhanced error handling
# - Keep-alive endpoint

import os
import asyncio
import json
import hashlib
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
from typing import Optional, Dict, List

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter
from aiohttp import web
import aiosqlite

# =========================== CONFIG ===========================
load_dotenv()

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TG_LINK_FOR_FB = "https://t.me/AIDailyNewsKH"

# Facebook Settings
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
FB_LINK_FOR_TG = "https://www.facebook.com/profile.php?id=61584116626111"

# AI Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash-exp"
CHECK_INTERVAL = 900  # 15 minutes

# System
ICT = pytz.timezone('Asia/Phnom_Penh')
DB_FILE = "posted_articles.db"
db_lock = asyncio.Lock()
PORT = int(os.environ.get("PORT", 8080))

# Rate limiting
GEMINI_CALLS_PER_MINUTE = 10
GEMINI_DELAY = 6  # seconds between calls

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL_INSTANCE = genai.GenerativeModel(GEMINI_MODEL)
else:
    GEMINI_MODEL_INSTANCE = None
    logger.warning("⚠️ GEMINI_API_KEY not set!")

# Initialize Telegram Bot (singleton)
telegram_bot: Optional[Bot] = None
if TELEGRAM_BOT_TOKEN:
    telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Stats
stats = {
    'total_posts': 0,
    'facebook_posts': 0,
    'telegram_posts': 0,
    'translations': 0,
    'errors': 0,
    'boost_triggers': 0
}

# =========================== RSS SOURCES ===========================
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
    ]
}

# Breaking news keywords
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "រញ្ជួយដី", "breaking", "ស្លាប់"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "crisis", "dead", "emergency"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "BBC News"}

# =========================== SCHEDULE & BREAKING LOGIC ===========================

def get_current_slot() -> Dict:
    """Get current time slot configuration."""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    if 5 <= h < 8:       return {"name": "Morning",      "max": 6}
    if 8 <= h < 11.5:    return {"name": "Work AM",      "max": 4}
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak",   "max": 6}
    if 13.5 <= h < 17:   return {"name": "Afternoon",    "max": 4}
    if 17 <= h < 21:     return {"name": "Evening Prime","max": 5}
    if 21 <= h < 23:     return {"name": "Night",        "max": 3}
    return                       {"name": "Deep Night",   "max": 1}


def is_breaking_news(article: Dict) -> bool:
    """Check if news is urgent."""
    score = 0
    title = article['title'].lower()
    
    # Check Keywords
    for w in BREAKING_KEYWORDS_EN:
        if w in title: 
            score += 100
            
    for w in BREAKING_KEYWORDS_KH:
        if w in title: 
            score += 100
    
    # Check Source Importance
    if article['source'] in HIGH_PRIORITY_SOURCES: 
        score += 20
    
    # Check Punctuation
    if "!" in title: 
        score += 10
    
    return score >= 100


# =========================== DATABASE ===========================

async def init_db() -> None:
    """Initialize SQLite database."""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posted (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        source TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.commit()
                logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ DB init error: {e}")


async def is_posted(aid: str) -> bool:
    """Check if article already posted."""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE) as db:
                cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
                return await cur.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ DB read error: {e}")
        return False


async def mark_as_posted(aid: str, cat: str, source: str) -> None:
    """Mark article as posted."""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?, ?, ?)", 
                    (aid, cat, source)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"❌ DB write error: {e}")


# =========================== RSS & CONTENT FETCHING ===========================

async def fetch_rss(url: str) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse RSS feed."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KhmerNewsBot/2.0)"}
    timeout = aiohttp.ClientTimeout(total=20)
    
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    text = await response.text()
                    return feedparser.parse(text)
    except asyncio.TimeoutError:
        logger.warning(f"⏱️ Timeout fetching: {url}")
    except Exception as e:
        logger.error(f"❌ RSS fetch error ({url}): {e}")
    
    return None


def get_image(entry, base_url: str) -> Optional[str]:
    """Extract image URL from RSS entry."""
    try:
        # Try media:content
        if hasattr(entry, "media_content") and entry.media_content:
            return entry.media_content[0].get("url")
        
        # Try parsing HTML
        html = entry.get("summary", "") or entry.get("description", "")
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        
        if img and img.get("src"):
            return urljoin(base_url, img.get("src"))
    except Exception as e:
        logger.error(f"Image extraction error: {e}")
    
    return None


async def get_article_id(title: str, link: str) -> str:
    """Generate unique article ID."""
    return hashlib.md5(f"{title}{link}".encode()).hexdigest()


# =========================== AI TRANSLATION ===========================

async def translate(article: Dict) -> Dict:
    """Translate article to Khmer using Gemini."""
    if not GEMINI_MODEL_INSTANCE:
        logger.warning("⚠️ Gemini not available, using original text")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        return article
    
    prompt = f"""Translate to natural Khmer. Respond ONLY with valid JSON, no markdown:

Title: {article['title']}
Content: {article['summary'][:2000]}

Return format:
{{"title_kh": "...", "body_kh": "..."}}"""

    try:
        # Run in thread to avoid blocking
        response = await asyncio.to_thread(
            GEMINI_MODEL_INSTANCE.generate_content, 
            prompt
        )
        
        text = response.text.strip()
        
        # Clean markdown formatting
        text = re.sub(r"^```json\s*|```$", "", text, flags=re.MULTILINE)
        text = text.strip()
        
        data = json.loads(text)
        
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        
        stats['translations'] += 1
        
        # Rate limiting
        await asyncio.sleep(GEMINI_DELAY)
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parse error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        stats['errors'] += 1
        
    except Exception as e:
        logger.error(f"❌ Translation error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        stats['errors'] += 1
    
    return article


# =========================== POSTING LOGIC ===========================

async def post_to_facebook(article: Dict, emoji: str) -> bool:
    """Post article to Facebook."""
    if not (FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN):
        return False
    
    message = (
        f"{emoji} {article['title_kh']}\n\n"
        f"{article['body_kh']}\n\n"
        f"__________________\n"
        f"ប្រភព: {article['source']}\n"
        f"👉 តាមដាន Telegram: {TG_LINK_FOR_FB}\n"
        f"អានបន្ថែម: {article['link']}"
    )
    
    try:
        # Try with photo first
        if article.get("image_url"):
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
            params = {
                "url": article["image_url"],
                "message": message,
                "access_token": FACEBOOK_ACCESS_TOKEN,
                "published": "true"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=params) as response:
                    result = await response.json()
                    if result.get("id"):
                        stats['facebook_posts'] += 1
                        return True
        
        # Fallback to link post
        url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
        params = {
            "link": article["link"],
            "message": message,
            "access_token": FACEBOOK_ACCESS_TOKEN,
            "published": "true"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=params) as response:
                result = await response.json()
                if result.get("id"):
                    stats['facebook_posts'] += 1
                    return True
                    
    except Exception as e:
        logger.error(f"❌ Facebook post error: {e}")
        stats['errors'] += 1
    
    return False


async def post_to_telegram(article: Dict, emoji: str) -> bool:
    """Post article to Telegram."""
    if not (telegram_bot and TELEGRAM_CHANNEL_ID):
        return False
    
    caption = (
        f"{emoji} <b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {article['source']}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📰", url=article["link"])],
        [InlineKeyboardButton("Facebook Page 📘", url=FB_LINK_FOR_TG)]
    ])
    
    try:
        # Try with photo first
        if article.get("image_url"):
            async with aiohttp.ClientSession() as session:
                async with session.get(article["image_url"], timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        photo_data = await response.read()
                        await telegram_bot.send_photo(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            photo=photo_data,
                            caption=caption[:1024],
                            parse_mode=ParseMode.HTML,
                            reply_markup=buttons
                        )
                        stats['telegram_posts'] += 1
                        return True
        
        # Fallback to text
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=False
        )
        stats['telegram_posts'] += 1
        return True
        
    except RetryAfter as e:
        logger.warning(f"⏳ Rate limited, waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        stats['errors'] += 1
        
    except TelegramError as e:
        logger.error(f"❌ Telegram error: {e}")
        stats['errors'] += 1
        
    except Exception as e:
        logger.error(f"❌ Telegram post error: {e}")
        stats['errors'] += 1
    
    return False


# =========================== MAIN WORKER ===========================

async def worker():
    """Main news processing loop."""
    await init_db()
    logger.info("🚀 News Bot Started (FB + TG + Breaking Boost)")
    
    boost_until = None
    
    while True:
        try:
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            # Check boost mode
            if boost_until and now < boost_until:
                max_posts = 15
                delay = 60
                logger.info("🔥 BOOST MODE ACTIVE")
            else:
                max_posts = max(1, slot["max"] // 4)
                delay = CHECK_INTERVAL
                boost_until = None
            
            posted_count = 0
            categories = [("cambodia", "🇰🇭"), ("international", "🌏")]
            
            for cat, emoji in categories:
                if posted_count >= max_posts:
                    break
                
                for src in NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts:
                        break
                    
                    try:
                        feed = await fetch_rss(src["rss"])
                        if not feed or not feed.entries:
                            continue
                        
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        if await is_posted(aid):
                            continue
                        
                        # Build article
                        article = {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": BeautifulSoup(
                                entry.get("summary", ""), 
                                "html.parser"
                            ).get_text(strip=True)[:1000],
                            "image_url": get_image(entry, src["url"]),
                            "source": src["name"]
                        }
                        
                        # Check breaking news BEFORE translation
                        if is_breaking_news(article) and not boost_until:
                            logger.info("🚨 BREAKING NEWS -> Boost Mode!")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji
                            stats['boost_triggers'] += 1
                        
                        # Translate
                        article = await translate(article)
                        
                        # Post to both platforms
                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji)
                        
                        if fb_ok or tg_ok:
                            await mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            stats['total_posts'] += 1
                            
                            logger.info(
                                f"✅ Posted: {article['title_kh'][:40]}... "
                                f"[FB: {fb_ok}, TG: {tg_ok}]"
                            )
                            
                            # Delay between posts
                            if boost_until:
                                await asyncio.sleep(5)
                            else:
                                await asyncio.sleep(15)
                    
                    except Exception as e:
                        logger.error(f"❌ Error processing {src['name']}: {e}")
                        stats['errors'] += 1
            
            logger.info(
                f"✓ Cycle done. Posted: {posted_count}/{max_posts}. "
                f"Next check: {delay}s"
            )
            
            await asyncio.sleep(delay)
        
        except Exception as e:
            logger.error(f"❌ Worker loop error: {e}")
            stats['errors'] += 1
            await asyncio.sleep(60)


# =========================== WEB SERVER ===========================

async def health(request):
    """Health check endpoint."""
    return web.json_response({
        'status': 'alive',
        'timestamp': datetime.now(ICT).isoformat(),
        'stats': stats
    })


async def ping(request):
    """Lightweight ping for keep-alive."""
    return web.json_response({
        'status': 'ok',
        'timestamp': datetime.now(ICT).isoformat()
    })


async def web_server():
    """Start web server."""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    logger.info(f"🌐 Web server started on port {PORT}")


async def main():
    """Main entry point."""
    await asyncio.gather(
        web_server(),
        worker()
    )


if __name__ == "__main__":
    asyncio.run(main())