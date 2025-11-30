# bot.py – MEGA ASEAN & WORLD NEWS BOT 2026 (Optimized)
# Fixed: Gemini model, FB API version, RSS retry, image timeout

import os
import asyncio
import json
import hashlib
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
from typing import Optional, Dict
import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from aiohttp import web
import aiosqlite

# =========================== CONFIG ===========================
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TG_LINK_FOR_FB = os.getenv("TG_LINK_FOR_FB", "https://t.me/YourChannel")

FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
FB_LINK_FOR_TG = os.getenv("FB_LINK_FOR_TG", "https://www.facebook.com/profile.php?id=61584116626111")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"  # FIX: Stable model
FB_API_VERSION = "v21.0"  # FIX: Latest version
CHECK_INTERVAL = 900
GEMINI_DELAY = 6
IMAGE_TIMEOUT = 20  # FIX: Increased from 10s

ICT = pytz.timezone('Asia/Phnom_Penh')
DB_FILE = "posted_articles.db"
db_lock = asyncio.Lock()
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL_INSTANCE = genai.GenerativeModel(GEMINI_MODEL)
else:
    GEMINI_MODEL_INSTANCE = None
    logger.warning("⚠️ GEMINI_API_KEY not set")

telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

stats = {
    'total_posts': 0, 'facebook_posts': 0, 'telegram_posts': 0,
    'translations': 0, 'errors': 0, 'boost_triggers': 0, 
    'start_time': datetime.now(ICT).isoformat()
}

# =========================== 70+ NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey", "rss": "https://thmeythmey.com/feed", "url": "https://thmeythmey.com"},
        {"name": "Fresh News", "rss": "https://freshnewsasia.com/index.php/en/rss.html", "url": "https://freshnewsasia.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed", "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "DAP News", "rss": "https://www.dap-news.com/feed", "url": "https://www.dap-news.com"},
        {"name": "Khmer Times", "rss": "https://www.khmertimeskh.com/feed/", "url": "https://www.khmertimeskh.com"},
        {"name": "Rasmei News", "rss": "https://www.rasmeinews.com/feed", "url": "https://www.rasmeinews.com"},
    ],
    "vietnam": [
        {"name": "VNExpress", "rss": "https://vnexpress.net/rss/tin-moi-nhat.rss", "url": "https://vnexpress.net"},
        {"name": "Tuoi Tre", "rss": "https://tuoitre.vn/rss/home.rss", "url": "https://tuoitre.vn"},
    ],
    "thailand": [
        {"name": "Khaosod", "rss": "https://www.khaosod.co.th/rss", "url": "https://www.khaosod.co.th"},
        {"name": "Bangkok Post", "rss": "https://www.bangkokpost.com/rss", "url": "https://www.bangkokpost.com"},
    ],
    "international": [
        {"name": "BBC", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "url": "https://www.bbc.com"},
        {"name": "Reuters", "rss": "https://www.reuters.com/tools/rss", "url": "https://www.reuters.com"},
        {"name": "Al Jazeera", "rss": "https://www.aljazeera.com/xml/rss/all.xml", "url": "https://www.aljazeera.com"},
    ]
}

BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "ស្លាប់"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead"]
HIGH_PRIORITY_SOURCES = {"Reuters", "BBC", "VNExpress", "Khaosod", "Fresh News", "Thmey Thmey"}

# =========================== CORE FUNCTIONS ===========================
def get_current_slot():
    h = datetime.now(ICT).hour + datetime.now(ICT).minute / 60
    if 5 <= h < 8: return {"max": 6}
    if 8 <= h < 11.5: return {"max": 4}
    if 11.5 <= h < 13.5: return {"max": 6}
    if 13.5 <= h < 17: return {"max": 4}
    if 17 <= h < 21: return {"max": 5}
    if 21 <= h < 23: return {"max": 3}
    return {"max": 1}

def is_breaking_news(article: Dict) -> bool:
    title = article['title'].lower()
    score = sum(100 for w in BREAKING_KEYWORDS_EN + BREAKING_KEYWORDS_KH if w in title)
    score += 30 if article['source'] in HIGH_PRIORITY_SOURCES else 0
    score += 10 if "!" in title else 0
    return score >= 100

async def init_db():
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
    logger.info("✅ Database ready")

async def is_posted(aid: str) -> bool:
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE) as db:
                cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
                return await cur.fetchone() is not None
    except:
        return False

async def mark_as_posted(aid: str, cat: str, source: str):
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?, ?, ?)",
                    (aid, cat, source)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"DB error: {e}")

async def fetch_rss(url: str):
    """FIX: Added retry logic"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MegaASEANBot/2026)"}
    
    for attempt in range(3):  # 3 retries
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        return feedparser.parse(await r.text())
        except Exception as e:
            if attempt == 2:
                logger.warning(f"RSS failed after 3 attempts: {url}")
            await asyncio.sleep(2)
    return None

def get_image(entry, base_url: str) -> Optional[str]:
    """Enhanced image extraction"""
    try:
        # Media content
        if hasattr(entry, "media_content") and entry.media_content:
            for m in entry.media_content:
                if m.get("url"): 
                    return m["url"]
        
        # Media thumbnail
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            for m in entry.media_thumbnail:
                if m.get("url"): 
                    return m["url"]
        
        # Enclosures
        if hasattr(entry, "enclosures"):
            for e in entry.enclosures:
                if hasattr(e, 'type') and e.type and "image" in e.type and e.url:
                    return e.url
        
        # HTML parsing
        html = entry.get("summary", "") or entry.get("description", "") or ""
        if html:
            soup = BeautifulSoup(html, "html.parser")
            img = soup.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if src:
                    return urljoin(base_url, src)
    except Exception as e:
        logger.debug(f"Image extraction error: {e}")
    return None

async def get_article_id(t: str, l: str) -> str:
    return hashlib.md5(f"{t}{l}".encode()).hexdigest()

async def translate(article: Dict) -> Dict:
    """Gemini AI translation"""
    if not GEMINI_MODEL_INSTANCE:
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        return article
    
    prompt = f"""Translate to natural Khmer for news. Return ONLY valid JSON.

Title: {article['title']}
Content: {article['summary'][:2000]}

Format: {{"title_kh": "...", "body_kh": "..."}}"""
    
    try:
        resp = await asyncio.to_thread(GEMINI_MODEL_INSTANCE.generate_content, prompt)
        text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
        data = json.loads(text)
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        stats['translations'] += 1
        await asyncio.sleep(GEMINI_DELAY)
    except Exception as e:
        logger.error(f"Translation error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
    return article

async def post_to_facebook(article: Dict, emoji: str) -> bool:
    """Post to Facebook Page"""
    if not (FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN): 
        return False
    
    message = (
        f"{emoji} {article['title_kh']}\n\n"
        f"{article['body_kh']}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {article['source']}\n"
        f"Telegram: {TG_LINK_FOR_FB}\n"
        f"អានបន្ថែម: {article['link']}"
    )
    
    try:
        # Try photo post first
        if article.get("image_url"):
            url = f"https://graph.facebook.com/{FB_API_VERSION}/{FACEBOOK_PAGE_ID}/photos"
            async with aiohttp.ClientSession() as s:
                async with s.post(url, data={
                    "url": article["image_url"],
                    "message": message,
                    "access_token": FACEBOOK_ACCESS_TOKEN
                }) as r:
                    result = await r.json()
                    if result.get("id"):
                        stats['facebook_posts'] += 1
                        logger.info(f"📸 FB photo posted")
                        return True
        
        # Fallback to link post
        url = f"https://graph.facebook.com/{FB_API_VERSION}/{FACEBOOK_PAGE_ID}/feed"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data={
                "link": article["link"],
                "message": message,
                "access_token": FACEBOOK_ACCESS_TOKEN
            }) as r:
                result = await r.json()
                if result.get("id"):
                    stats['facebook_posts'] += 1
                    logger.info(f"📝 FB link posted")
                    return True
                
    except Exception as e:
        logger.error(f"FB error: {e}")
        stats['errors'] += 1
    return False

async def post_to_telegram(article: Dict, emoji: str) -> bool:
    """Post to Telegram Channel"""
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
        # Try photo post
        if article.get("image_url"):
            async with aiohttp.ClientSession() as s:
                async with s.get(article["image_url"], timeout=IMAGE_TIMEOUT) as r:  # FIX: 20s timeout
                    if r.status == 200:
                        await telegram_bot.send_photo(
                            TELEGRAM_CHANNEL_ID,
                            photo=await r.read(),
                            caption=caption[:1024],
                            parse_mode=ParseMode.HTML,
                            reply_markup=buttons
                        )
                        stats['telegram_posts'] += 1
                        logger.info(f"📸 TG photo posted")
                        return True
        
        # Fallback to text
        await telegram_bot.send_message(
            TELEGRAM_CHANNEL_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=False
        )
        stats['telegram_posts'] += 1
        logger.info(f"📝 TG text posted")
        return True
        
    except RetryAfter as e:
        logger.warning(f"⏳ Rate limit, waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after + 1)
    except Exception as e:
        logger.error(f"TG error: {e}")
        stats['errors'] += 1
    return False

# =========================== MAIN WORKER ===========================
async def worker():
    """Main worker loop"""
    await init_db()
    logger.info("🚀 MEGA ASEAN & WORLD NEWS BOT 2026 STARTED!")
    
    boost_until = None
    
    while True:
        try:
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            # Boost mode check
            if boost_until and now < boost_until:
                max_posts = 18
                delay = 60
                logger.info("🔥 BOOST MODE ACTIVE")
            else:
                max_posts = max(1, slot["max"] // 3)
                delay = CHECK_INTERVAL
                boost_until = None
            
            posted_count = 0
            categories = [
                ("cambodia", "🇰🇭"),
                ("vietnam", "🇻🇳"),
                ("thailand", "🇹🇭"),
                ("international", "🌍")
            ]
            
            for cat, flag in categories:
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
                        
                        # Extract article
                        article = {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": BeautifulSoup(
                                entry.get("summary", "") or entry.get("description", ""),
                                "html.parser"
                            ).get_text(strip=True)[:1000],
                            "image_url": get_image(entry, src["url"]),
                            "source": src["name"]
                        }
                        
                        # Breaking news check
                        emoji = flag
                        if is_breaking_news(article) and not boost_until:
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + flag
                            stats['boost_triggers'] += 1
                            logger.info("🚨 BREAKING NEWS! Boost activated")
                        
                        # Translate
                        article = await translate(article)
                        
                        # Post to both platforms
                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji)
                        
                        if fb_ok or tg_ok:
                            await mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            stats['total_posts'] += 1
                            logger.info(f"✅ Posted ({posted_count}/{max_posts}): {article['title_kh'][:40]}")
                            await asyncio.sleep(5 if boost_until else 15)
                        
                    except Exception as e:
                        logger.error(f"❌ Error {src['name']}: {str(e)[:100]}")
                        stats['errors'] += 1
            
            logger.info(f"✅ Cycle done: {posted_count} posts | Next in {delay}s\n")
            await asyncio.sleep(delay)
            
        except Exception as e:
            logger.critical(f"🔴 Worker crash: {e}")
            await asyncio.sleep(60)

# =========================== WEB SERVER ===========================
async def health(request):
    """Health check endpoint with stats"""
    return web.json_response({
        "status": "✅ ALIVE",
        "bot": "MEGA ASEAN NEWS BOT 2026",
        "uptime": stats['start_time'],
        "stats": stats,
        "timestamp": datetime.now(ICT).isoformat()
    })

async def ping(request):
    """Simple ping endpoint"""
    return web.Response(text="OK")

async def web_server():
    """Start web server"""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/ping", ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    logger.info(f"🌐 Web server live on port {PORT}")

async def main():
    """Main entry point"""
    await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")