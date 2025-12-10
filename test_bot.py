# bot.py — Khmer News Bot 2026 (Ultimate Edition - IMPROVED)
# Features:
# - Cambodia + International + Thai + Vietnamese
# - Dynamic time-based posting (peak hours = high frequency)
# - BREAKING NEWS BOOST MODE (1 post every 60s when big news hits)
# - Gemini AI translation to natural Khmer
# - Smart image + text fallback with size validation
# - Exponential backoff retry logic
# - Statistics tracking & monitoring
# - Never crashes — Full error handling

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
from datetime import datetime, timedelta, time
from urllib.parse import urljoin
from dataclasses import dataclass, field
from typing import Optional, Dict, List

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

GEMINI_MODEL = "gemini-2.5-flash"  # ✅ លឿន + ថោក + គុណភាពល្អ
CHECK_INTERVAL = 900  # 15 minutes base cycle (fallback)

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

# =========================== STATISTICS TRACKING ===========================
@dataclass
class BotStats:
    posted_today: int = 0
    failed_posts: int = 0
    breaking_news_count: int = 0
    gemini_failures: int = 0
    rss_failures: Dict[str, int] = field(default_factory=dict)
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())
    
    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logging.info(f"📊 Daily Stats: Posted={self.posted_today}, Failed={self.failed_posts}, Breaking={self.breaking_news_count}, Gemini Fails={self.gemini_failures}")
            self.posted_today = 0
            self.failed_posts = 0
            self.breaking_news_count = 0
            self.gemini_failures = 0
            self.rss_failures.clear()
            self.last_reset = today
    
    def log_summary(self):
        logging.info(f"📈 Stats: Posts={self.posted_today} | Fails={self.failed_posts} | Breaking={self.breaking_news_count}")

stats = BotStats()

# =========================== DYNAMIC SCHEDULE + BREAKING BOOST ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "សន្ធឹក", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "ប៉ះទង្គិច", "រញ្ជួយដី", "បាតុកម្ម", "breaking"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "dies", "killed", "crisis", "attack", "fire", "disaster"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "Koh Santepheap", "BBC News", "Al Jazeera"}

def get_current_slot() -> Dict:
    """កំណត់ចំនួន Post និងមោងរង់ចាំដោយផ្អែកលើម៉ោងជាក់ស្តែងនៅកម្ពុជា"""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    # ម៉ោង 5ព្រឹក - 8ព្រឹក (Morning News)
    if 5 <= h < 8:       return {"name": "Morning",      "max": 8,  "delay": 60}
    # ម៉ោង 8ព្រឹក - 11:30 (Work/Peak)
    if 8 <= h < 11.5:    return {"name": "Work AM",      "max": 6,  "delay": 90}
    # ម៉ោង 11:30 - 1:30 (Lunch Peak)
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak",   "max": 10, "delay": 45}
    # ម៉ោង 1:30 - 5លាៀច (Afternoon)
    if 13.5 <= h < 17:   return {"name": "Afternoon",    "max": 5,  "delay": 120}
    # ម៉ោង 5លាៀច - 9យប់ (Prime Time)
    if 17 <= h < 21:     return {"name": "Evening Prime","max": 12, "delay": 40}
    # ម៉ោង 9យប់ - 11យប់ (Night)
    if 21 <= h < 23:     return {"name": "Night",        "max": 5,  "delay": 150}
    # ម៉ោង 11យប់ - 5ព្រឹក (Sleep Mode)
    return                       {"name": "Deep Night",   "max": 2,  "delay": 300}

def is_breaking_news(article: Dict) -> bool:
    """ពិនិត្យមើលថាជាព័ត៌មានបន្ទាន់ឬអត់ (កែលម្អ - ពិនិត្យទាំង title និង summary)"""
    score = 0
    title = article["title"].lower()
    title_kh = article.get("title_kh", "").lower()
    summary = article.get("summary", "").lower()
    
    # រួមបញ្ចូលទាំង title និង summary
    full_text = f"{title} {title_kh} {summary}"
    
    for w in BREAKING_KEYWORDS_EN:
        if w in full_text: score += 100
    for w in BREAKING_KEYWORDS_KH:
        if w in full_text: score += 120
    
    if article["source"] in HIGH_PRIORITY_SOURCES: score += 50
    
    # ពិនិត្យម៉ោងផ្សាយ (ប្រសិនបើថ្មីៗណាស់)
    pub_date = article.get("published_parsed")
    if pub_date:
        try:
            pub_datetime = datetime(*pub_date[:6])
            age_minutes = (datetime.now() - pub_datetime).total_seconds() / 60
            if age_minutes < 30: score += 30  # ថ្មី < 30 នាទី
        except:
            pass
    
    # ពិនិត្យ title length និង punctuation
    if len(article["title"]) < 60 and ("!" in title or "?" in title): 
        score += 30
    
    return score >= 100

# =========================== DATABASE ===========================
async def init_db():
    """Initialize database with retry logic"""
    for attempt in range(3):
        try:
            async with aiosqlite.connect(DB_FILE, timeout=15) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posted (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        source TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Add index for faster queries
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_posted_at ON posted(posted_at)
                """)
                await db.commit()
            logging.info("✅ Database ready")
            return
        except Exception as e:
            logging.warning(f"DB init attempt {attempt+1}/3 failed: {e}")
            await asyncio.sleep(3)
    logging.critical("❌ DB failed — continuing without persistence")

async def is_posted(aid: str) -> bool:
    """Check if article already posted"""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None
    except Exception as e:
        logging.warning(f"DB check error: {e}")
        return False

async def mark_as_posted(aid: str, cat: str, source: str):
    """Mark article as posted"""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            await db.execute(
                "INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?,?,?)", 
                (aid, cat, source)
            )
            await db.commit()
    except Exception as e:
        logging.warning(f"DB insert error: {e}")

async def cleanup_old_records():
    """Clean up records older than 30 days"""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=15) as db:
            cutoff = datetime.now(ICT) - timedelta(days=30)
            await db.execute(
                "DELETE FROM posted WHERE posted_at < ?", 
                (cutoff.isoformat(),)
            )
            await db.commit()
            logging.info("🧹 Cleaned up old database records")
    except Exception as e:
        logging.warning(f"DB cleanup error: {e}")

# =========================== RSS & IMAGE ===========================
async def fetch_rss(url: str, source_name: str) -> Optional[feedparser.FeedParserDict]:
    """Fetch RSS with retry and logging"""
    headers = {"User-Agent": "KhmerNewsBot/2.0 (+https://t.me/AIDailyNewsKH)"}
    
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=20)
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        text = await response.text()
                        feed = feedparser.parse(text)
                        if feed.entries:
                            return feed
                        else:
                            logging.warning(f"No entries in {source_name}")
                            return None
        except asyncio.TimeoutError:
            logging.warning(f"Timeout fetching {source_name} (attempt {attempt+1}/3)")
        except Exception as e:
            logging.warning(f"Error fetching {source_name}: {e}")
        
        if attempt < 2:
            await asyncio.sleep(2)
    
    stats.rss_failures[source_name] = stats.rss_failures.get(source_name, 0) + 1
    return None

def get_image(entry, base_url: str) -> Optional[str]:
    """Extract image URL from RSS entry"""
    try:
        # Try media_content first
        if getattr(entry, "media_content", None):
            return entry.media_content[0].get("url")
        
        # Parse HTML content
        html_content = entry.get("summary", "") or entry.get("description", "")
        soup = BeautifulSoup(html_content, "html.parser")
        img = soup.find("img")
        
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                return urljoin(base_url, src.strip())
    except Exception as e:
        logging.debug(f"Image extraction error: {e}")
    
    return None

async def get_article_id(title: str, link: str) -> str:
    """Generate unique article ID"""
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except:
        return str(hash(f"{title}{link}"))

# =========================== GEMINI TRANSLATE ===========================
async def translate(article: Dict, max_retries: int = 3) -> Dict:
    """Translate to Khmer using Gemini with exponential backoff"""
    prompt = (
        f"Translate to natural, engaging Khmer for Telegram news channel:\n\n"
        f"Title: {article['title']}\n"
        f"Content: {article['summary'][:2800]}\n\n"
        f"Requirements:\n"
        f"- Use conversational, modern Khmer\n"
        f"- Keep it engaging and clear\n"
        f"- Maximum 500 characters for body\n\n"
        f"Return ONLY valid JSON (no markdown, no extra text):\n"
        f'{{\"title_kh\": \"...\", \"body_kh\": \"...\"}}'
    )
    
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            
            # Clean up response
            text = resp.text.strip()
            text = re.sub(r"^```json\s*|```$", "", text, flags=re.M)
            
            # Parse JSON
            data = json.loads(text)
            
            article["title_kh"] = data.get("title_kh", article["title"])
            article["body_kh"] = data.get("body_kh", article["summary"][:500])
            
            # Rate limit
            await asyncio.sleep(7)
            return article
        
        except json.JSONDecodeError as e:
            logging.warning(f"Gemini JSON parse error (attempt {attempt+1}/{max_retries}): {e}")
        except Exception as e:
            logging.warning(f"Gemini error (attempt {attempt+1}/{max_retries}): {e}")
        
        # Exponential backoff
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt
            await asyncio.sleep(wait_time)
    
    # Final fallback: English
    stats.gemini_failures += 1
    logging.error("❌ Gemini failed after all retries → Using English")
    article["title_kh"] = article["title"]
    article["body_kh"] = article["summary"][:500] + "\n\n(English version)"
    return article

# =========================== SMART POST ===========================
async def post_smart(article: Dict, emoji: str) -> bool:
    """Post to Telegram with smart image handling and validation"""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID):
        logging.error("Missing Telegram credentials")
        return False

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Add flag emoji
    flag = ""
    if article["source"] in [s["name"] for s in NEWS_SOURCES["thai"]]: 
        flag = "🇹🇭"
    elif article["source"] in [s["name"] for s in NEWS_SOURCES["vietnamese"]]: 
        flag = "🇻🇳"
    
    caption = (
        f"{emoji} {flag} <b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"─────────────────\n"
        f"ប្រភព: {article['source']}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📖", url=article["link"])],
        [InlineKeyboardButton("Join Channel 📢", url=CHANNEL_LINK)]
    ])
    
    # Try posting with image
    if article.get("image_url"):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(article["image_url"], timeout=15) as response:
                    if response.status == 200 and "image" in response.content_type:
                        img_data = await response.read()
                        
                        # Validate image size (Telegram limit: 10MB)
                        img_size_mb = len(img_data) / (1024 * 1024)
                        if img_size_mb > 10:
                            logging.warning(f"Image too large ({img_size_mb:.2f}MB) → Text mode")
                        else:
                            await bot.send_photo(
                                chat_id=TELEGRAM_CHANNEL_ID,
                                photo=img_data,
                                caption=caption[:1024],
                                parse_mode=ParseMode.HTML,
                                reply_markup=buttons
                            )
                            logging.info(f"✅ PHOTO: {article['title_kh'][:50]}...")
                            return True
        except Exception as e:
            logging.warning(f"Photo send failed: {e} → Text fallback")
    
    # Fallback: Text message
    for attempt in range(3):
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption + f"\n\n🔗 {article['link']}",
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            logging.info(f"✅ TEXT: {article['title_kh'][:50]}...")
            return True
        
        except (NetworkError, TimedOut) as e:
            logging.warning(f"Network error (attempt {attempt+1}/3): {e}")
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"❌ Post failed: {e}")
            break
    
    stats.failed_posts += 1
    return False

# =========================== MAIN WORKER (Dynamic + Breaking Boost) ===========================
async def worker():
    """Main worker loop with dynamic scheduling and breaking news boost"""
    await init_db()
    logging.info("🚀 Khmer News Bot 2026 ULTIMATE STARTED — Dynamic + Breaking Boost")

    boost_until = None
    last_cleanup = datetime.now(ICT)
    
    while True:
        try:
            stats.reset_if_new_day()
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            # Boost mode check
            if boost_until and now < boost_until:
                max_posts = 20
                delay = 60
                logging.info("🔥 BREAKING NEWS BOOST MODE ACTIVE!")
            else:
                max_posts = slot["max"] // 4
                delay = slot["delay"]
                boost_until = None
            
            posted_count = 0
            categories = [
                ("cambodia", "🇰🇭"), 
                ("international", "🌍"),
                ("thai", "📰"), 
                ("vietnamese", "📰")
            ]
            
            for cat, emoji in categories:
                if posted_count >= max_posts: 
                    break
                
                for src in NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts: 
                        break
                    
                    try:
                        feed = await fetch_rss(src["rss"], src["name"])
                        if not feed or not feed.entries: 
                            continue
                        
                        # Process latest entry
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        if await is_posted(aid): 
                            continue
                        
                        # Extract article data
                        article = {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": BeautifulSoup(
                                entry.get("summary", "") or entry.get("description", ""),
                                "html.parser"
                            ).get_text(strip=True)[:1000],
                            "image_url": get_image(entry, src["url"]),
                            "source": src["name"],
                            "published_parsed": getattr(entry, "published_parsed", None)
                        }
                        
                        # Translate to Khmer
                        article = await translate(article)
                        
                        # Check for breaking news
                        if is_breaking_news(article) and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED → BOOST ACTIVATED!")
                            boost_until = now + timedelta(minutes=15)
                            stats.breaking_news_count += 1
                            
                            if await post_smart(article, "🚨 BREAKING NEWS " + emoji):
                                await mark_as_posted(aid, cat, src["name"])
                                stats.posted_today += 1
                                posted_count += 1
                                await asyncio.sleep(5)
                            continue
                        
                        # Regular post
                        if await post_smart(article, emoji):
                            await mark_as_posted(aid, cat, src["name"])
                            stats.posted_today += 1
                            posted_count += 1
                            await asyncio.sleep(8)
                    
                    except Exception as e:
                        logging.error(f"Error processing {src['name']}: {e}")
                        continue
            
            # Log cycle summary
            stats.log_summary()
            logging.info(f"📊 Cycle complete: {posted_count} posts | Mode: {slot['name']} | Next in {delay}s")
            
            # Periodic cleanup (once per day)
            if (now - last_cleanup).days >= 1:
                await cleanup_old_records()
                last_cleanup = now
            
            await asyncio.sleep(delay)
        
        except Exception as e:
            logging.critical(f"💥 Worker crashed: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(60)

# =========================== HEALTH SERVER ===========================
async def health(request):
    """Health check endpoint"""
    return web.Response(
        text=json.dumps({
            "status": "alive",
            "bot": "Khmer News 2026 Ultimate",
            "stats": {
                "posted_today": stats.posted_today,
                "failed_posts": stats.failed_posts,
                "breaking_news": stats.breaking_news_count,
                "gemini_failures": stats.gemini_failures
            },
            "timestamp": datetime.now(ICT).isoformat()
        }),
        content_type="application/json"
    )

async def web_server():
    """Start health check web server"""
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"🌐 Health server running on port {port}")

# =========================== TEST FUNCTION ===========================
async def test_sources():
    """Test all RSS sources"""
    logging.info("\n" + "="*50)
    logging.info("🧪 TESTING ALL RSS SOURCES")
    logging.info("="*50)
    
    for cat, sources in NEWS_SOURCES.items():
        logging.info(f"\n📂 Category: {cat.upper()}")
        for src in sources:
            feed = await fetch_rss(src["rss"], src["name"])
            if feed and feed.entries:
                logging.info(f"  ✅ {src['name']} - {len(feed.entries)} entries")
            else:
                logging.info(f"  ❌ {src['name']} - FAILED")
    
    logging.info("\n" + "="*50 + "\n")

# =========================== RUN ===========================
async def main():
    """Main entry point"""
    # Uncomment to test RSS sources
    # await test_sources()
    
    await asyncio.gather(
        web_server(),
        worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Bot stopped by user")
    except Exception as e:
        logging.critical(f"💥 Fatal crash: {e}\n{traceback.format_exc()}")