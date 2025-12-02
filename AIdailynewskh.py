# main.py — Unified News Bot (Telegram + Twitter/X)
# Deploy to Render.com
# Features:
# - Single bot running both Telegram & Twitter
# - Cambodia + International + Thai + Vietnamese
# - Dynamic time-based posting
# - BREAKING NEWS BOOST MODE
# - Gemini AI translation
# - Smart image handling
# - Full error handling

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
from datetime import datetime, timedelta
from urllib.parse import urljoin
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, NetworkError, TimedOut
import tweepy
from aiohttp import web
import aiosqlite

# =========================== CONFIG ===========================
load_dotenv()

# Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_CHANNEL_LINK = os.getenv("TELEGRAM_CHANNEL_LINK", "https://t.me/AIDailyNewsKH")

# Twitter/X
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Enable/Disable platforms
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"

# Timezone Cambodia
ICT = pytz.timezone('Asia/Phnom_Penh')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Initialize APIs
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY missing!")

# Telegram Bot
telegram_bot = None
if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN:
    telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logging.info("✅ Telegram bot initialized")
else:
    logging.warning("⚠️ Telegram disabled or missing credentials")

# Twitter Client
twitter_client = None
twitter_api_v1 = None
if ENABLE_TWITTER and all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
    try:
        twitter_client = tweepy.Client(
            bearer_token=TWITTER_BEARER_TOKEN,
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
            wait_on_rate_limit=True
        )
        auth = tweepy.OAuth1UserHandler(
            TWITTER_API_KEY, TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
        )
        twitter_api_v1 = tweepy.API(auth)
        logging.info("✅ Twitter bot initialized")
    except Exception as e:
        logging.error(f"❌ Twitter init failed: {e}")
else:
    logging.warning("⚠️ Twitter disabled or missing credentials")

# =========================== RSS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
        {"name": "Rasmei News",    "rss": "https://www.rasmeinews.com/feed",               "url": "https://www.rasmeinews.com"},
    ],
    "international": [
        {"name": "BBC News",       "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",      "url": "https://www.bbc.com"},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com"},
        {"name": "Al Jazeera",     "rss": "https://www.aljazeera.com/xml/rss/all.xml",       "url": "https://www.aljazeera.com"},
    ],
    "thai": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed",            "url": "https://www.bangkokpost.com"},
        {"name": "Thai PBS World", "rss": "https://world.thaipbs.or.th/feed",                "url": "https://world.thaipbs.or.th"},
    ],
    "vietnamese": [
        {"name": "Tuoi Tre News",  "rss": "https://news.tuoitre.vn/rss.htm",                 "url": "https://news.tuoitre.vn"},
        {"name": "VNA",            "rss": "https://vnanet.vn/en/rss/",                       "url": "https://vnanet.vn/en"},
    ]
}

DB_FILE = "posted_articles.db"

HASHTAGS = {
    "cambodia": ["#Cambodia", "#KhmerNews", "#PhnomPenh"],
    "international": ["#WorldNews", "#Breaking"],
    "thai": ["#Thailand", "#Bangkok"],
    "vietnamese": ["#Vietnam", "#VietnamNews"]
}

# =========================== STATISTICS ===========================
@dataclass
class BotStats:
    telegram_posts: int = 0
    twitter_posts: int = 0
    failed_posts: int = 0
    breaking_news_count: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())
    
    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logging.info(f"📊 Daily Stats: Telegram={self.telegram_posts}, Twitter={self.twitter_posts}, Failed={self.failed_posts}, Breaking={self.breaking_news_count}")
            self.telegram_posts = 0
            self.twitter_posts = 0
            self.failed_posts = 0
            self.breaking_news_count = 0
            self.last_reset = today

stats = BotStats()

# =========================== BREAKING NEWS & SCHEDULING ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "breaking"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "killed", "crisis", "attack"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "BBC News", "Al Jazeera"}

def get_current_slot() -> Dict:
    """កំណត់ចំនួន Post និងមោងរង់ចាំ"""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    if 5 <= h < 8:       return {"name": "Morning",      "max": 8,  "delay": 60}
    if 8 <= h < 11.5:    return {"name": "Work AM",      "max": 6,  "delay": 90}
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak",   "max": 10, "delay": 45}
    if 13.5 <= h < 17:   return {"name": "Afternoon",    "max": 5,  "delay": 120}
    if 17 <= h < 21:     return {"name": "Evening Prime","max": 12, "delay": 40}
    if 21 <= h < 23:     return {"name": "Night",        "max": 5,  "delay": 150}
    return                       {"name": "Deep Night",   "max": 2,  "delay": 300}

def is_breaking_news(article: Dict) -> bool:
    """ពិនិត្យថាជាព័ត៌មានបន្ទាន់"""
    score = 0
    full_text = f"{article['title'].lower()} {article.get('title_kh', '').lower()} {article.get('summary', '').lower()}"
    
    for w in BREAKING_KEYWORDS_EN:
        if w in full_text: score += 100
    for w in BREAKING_KEYWORDS_KH:
        if w in full_text: score += 120
    
    if article["source"] in HIGH_PRIORITY_SOURCES: score += 50
    
    pub_date = article.get("published_parsed")
    if pub_date:
        try:
            pub_datetime = datetime(*pub_date[:6])
            age_minutes = (datetime.now() - pub_datetime).total_seconds() / 60
            if age_minutes < 30: score += 30
        except:
            pass
    
    return score >= 100

# =========================== DATABASE ===========================
async def init_db():
    for attempt in range(3):
        try:
            async with aiosqlite.connect(DB_FILE, timeout=15) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posted (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        source TEXT,
                        telegram_posted INTEGER DEFAULT 0,
                        twitter_posted INTEGER DEFAULT 0,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_posted_at ON posted(posted_at)")
                await db.commit()
            logging.info("✅ Database ready")
            return
        except Exception as e:
            logging.warning(f"DB init attempt {attempt+1}/3: {e}")
            await asyncio.sleep(3)

async def is_posted(aid: str, platform: str) -> bool:
    """Check if posted to specific platform"""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            column = "telegram_posted" if platform == "telegram" else "twitter_posted"
            cur = await db.execute(f"SELECT {column} FROM posted WHERE article_id=?", (aid,))
            result = await cur.fetchone()
            return result and result[0] == 1
    except:
        return False

async def mark_as_posted(aid: str, cat: str, source: str, platform: str):
    """Mark as posted to platform"""
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            column = "telegram_posted" if platform == "telegram" else "twitter_posted"
            await db.execute(f"""
                INSERT INTO posted(article_id, category, source, {column}) 
                VALUES(?,?,?,1)
                ON CONFLICT(article_id) DO UPDATE SET {column}=1
            """, (aid, cat, source))
            await db.commit()
    except Exception as e:
        logging.warning(f"DB error: {e}")

# =========================== RSS & IMAGE ===========================
async def fetch_rss(url: str, source_name: str) -> Optional[feedparser.FeedParserDict]:
    headers = {"User-Agent": "KhmerNewsBot/2.0"}
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        feed = feedparser.parse(await r.text())
                        if feed.entries:
                            return feed
        except Exception as e:
            logging.warning(f"RSS fetch {source_name}: {e}")
        if attempt < 2:
            await asyncio.sleep(2)
    return None

def get_image(entry, base_url: str) -> Optional[str]:
    try:
        if getattr(entry, "media_content", None):
            return entry.media_content[0].get("url")
        html = entry.get("summary", "") or entry.get("description", "")
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                return urljoin(base_url, src.strip())
    except:
        pass
    return None

async def get_article_id(title: str, link: str) -> str:
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except:
        return str(hash(f"{title}{link}"))

# =========================== GEMINI TRANSLATE ===========================
async def translate(article: Dict, platform: str = "telegram", max_retries: int = 3) -> Dict:
    """Translate for specific platform and language"""
    if platform == "twitter":
        # Twitter: Translate to English
        max_title = 100
        max_body = 200
        target_lang = "English"
        prompt = (
            f"Translate to natural, engaging English for Twitter/X:\n\n"
            f"Title: {article['title']}\n"
            f"Content: {article['summary'][:2800]}\n\n"
            f"Requirements:\n"
            f"- Use conversational, modern English\n"
            f"- Title: max {max_title} characters\n"
            f"- Body: max {max_body} characters (concise for Twitter)\n"
            f"- Make it engaging and shareable\n"
            f"- Focus on key facts\n\n"
            f"Return ONLY valid JSON:\n"
            f'{{\"title_en\": \"...\", \"body_en\": \"...\"}}'
        )
    else:
        # Telegram: Translate to Khmer
        max_title = 200
        max_body = 500
        target_lang = "Khmer"
        prompt = (
            f"Translate to natural, engaging Khmer for Telegram:\n\n"
            f"Title: {article['title']}\n"
            f"Content: {article['summary'][:2800]}\n\n"
            f"Requirements:\n"
            f"- Use conversational, modern Khmer\n"
            f"- Title: max {max_title} characters\n"
            f"- Body: max {max_body} characters\n"
            f"- Make it engaging and clear\n\n"
            f"Return ONLY valid JSON:\n"
            f'{{\"title_kh\": \"...\", \"body_kh\": \"...\"}}'
        )
    
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
            data = json.loads(text)
            
            if platform == "twitter":
                article["title_en"] = data.get("title_en", article["title"])[:max_title]
                article["body_en"] = data.get("body_en", article["summary"][:max_body])[:max_body]
            else:
                article["title_kh"] = data.get("title_kh", article["title"])[:max_title]
                article["body_kh"] = data.get("body_kh", article["summary"][:max_body])[:max_body]
            
            await asyncio.sleep(7)
            return article
        except Exception as e:
            logging.warning(f"Gemini error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    # Fallback
    if platform == "twitter":
        article["title_en"] = article["title"][:max_title]
        article["body_en"] = article["summary"][:max_body]
    else:
        article["title_kh"] = article["title"][:max_title]
        article["body_kh"] = article["summary"][:max_body]
    return article

# =========================== TELEGRAM POSTING ===========================
async def post_to_telegram(article: Dict, emoji: str, category: str) -> bool:
    """Post to Telegram"""
    if not telegram_bot:
        return False
    
    flag = ""
    if category == "thai": flag = "🇹🇭"
    elif category == "vietnamese": flag = "🇻🇳"
    elif category == "cambodia": flag = "🇰🇭"
    else: flag = "🌍"
    
    caption = (
        f"{emoji} {flag} <b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"─────────────────\n"
        f"ប្រភព: {article['source']}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📖", url=article["link"])],
        [InlineKeyboardButton("Join Channel 📢", url=TELEGRAM_CHANNEL_LINK)]
    ])
    
    # Try with image
    if article.get("image_url"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(article["image_url"], timeout=15) as r:
                    if r.status == 200 and "image" in r.content_type:
                        img_data = await r.read()
                        if len(img_data) <= 10 * 1024 * 1024:
                            await telegram_bot.send_photo(
                                chat_id=TELEGRAM_CHANNEL_ID,
                                photo=img_data,
                                caption=caption[:1024],
                                parse_mode=ParseMode.HTML,
                                reply_markup=buttons
                            )
                            logging.info(f"✅ Telegram PHOTO: {article['title_kh'][:40]}")
                            return True
        except Exception as e:
            logging.warning(f"Telegram photo failed: {e}")
    
    # Fallback: text
    for attempt in range(3):
        try:
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption + f"\n\n🔗 {article['link']}",
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            logging.info(f"✅ Telegram TEXT: {article['title_kh'][:40]}")
            return True
        except (NetworkError, TimedOut):
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Telegram error: {e}")
            break
    
    return False

# =========================== TWITTER POSTING ===========================
async def post_to_twitter(article: Dict, category: str, is_breaking: bool = False) -> bool:
    """Post to Twitter/X (English, Cambodia news only)"""
    if not twitter_client:
        return False
    
    # ✅ Twitter posts Cambodia news ONLY
    if category != "cambodia":
        return False
    
    flag = "🇰🇭"
    emoji = "🚨 BREAKING" if is_breaking else "📰"
    
    # Use English translation
    text = f"{emoji} {flag} {article.get('title_en', article['title'])}\n\n"
    if article.get('body_en'):
        text += f"{article['body_en']}\n\n"
    
    hashtags = ["#Cambodia", "#KhmerNews", "#PhnomPenh"][:2]
    text += " ".join(hashtags) + "\n\n"
    text += f"🔗 {article['link']}"
    
    # Truncate if too long
    if len(text) > 280:
        available = 280 - len(text) + len(article.get('body_en', ''))
        article['body_en'] = article.get('body_en', '')[:available-3] + "..."
        return await post_to_twitter(article, category, is_breaking)
    
    try:
        # Try with media
        media_id = None
        if article.get("image_url"):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(article["image_url"], timeout=15) as r:
                        if r.status == 200:
                            img_data = await r.read()
                            if len(img_data) <= 5 * 1024 * 1024:
                                media = await asyncio.to_thread(
                                    twitter_api_v1.media_upload,
                                    filename="image.jpg",
                                    file=img_data
                                )
                                media_id = media.media_id
            except:
                pass
        
        # Post tweet
        if media_id:
            response = await asyncio.to_thread(
                twitter_client.create_tweet,
                text=text,
                media_ids=[media_id]
            )
        else:
            response = await asyncio.to_thread(
                twitter_client.create_tweet,
                text=text
            )
        
        logging.info(f"✅ Twitter (EN): {article.get('title_en', article['title'])[:40]}")
        return True
    
    except Exception as e:
        logging.error(f"Twitter error: {e}")
        return False

# =========================== MAIN WORKER ===========================
async def worker():
    """Main worker loop - posts to both platforms"""
    await init_db()
    logging.info("🚀 Unified News Bot Started (Telegram + Twitter)")
    logging.info(f"   Telegram: {'✅ Enabled' if ENABLE_TELEGRAM else '❌ Disabled'}")
    logging.info(f"   Twitter: {'✅ Enabled' if ENABLE_TWITTER else '❌ Disabled'}")

    boost_until = None
    
    while True:
        try:
            stats.reset_if_new_day()
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            if boost_until and now < boost_until:
                max_posts = 20
                delay = 60
                logging.info("🔥 BREAKING NEWS BOOST MODE!")
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
                        
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        # Check if already posted to both platforms
                        telegram_posted = await is_posted(aid, "telegram") if ENABLE_TELEGRAM else True
                        twitter_posted = await is_posted(aid, "twitter") if ENABLE_TWITTER else True
                        
                        if telegram_posted and twitter_posted:
                            continue
                        
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
                        
                        breaking = is_breaking_news(article)
                        if breaking and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED!")
                            boost_until = now + timedelta(minutes=15)
                            stats.breaking_news_count += 1
                        
                        # Post to Telegram
                        if ENABLE_TELEGRAM and not telegram_posted:
                            article_tg = await translate(article.copy(), "telegram")
                            if await post_to_telegram(article_tg, "🚨 BREAKING " + emoji if breaking else emoji, cat):
                                await mark_as_posted(aid, cat, src["name"], "telegram")
                                stats.telegram_posts += 1
                                posted_count += 1
                                await asyncio.sleep(5)
                        
                        # Post to Twitter (Cambodia news ONLY, translate to English)
                        if ENABLE_TWITTER and not twitter_posted and cat == "cambodia":
                            article_tw = await translate(article.copy(), "twitter")
                            if await post_to_twitter(article_tw, cat, breaking):
                                await mark_as_posted(aid, cat, src["name"], "twitter")
                                stats.twitter_posts += 1
                                posted_count += 1
                                await asyncio.sleep(10)
                    
                    except Exception as e:
                        logging.error(f"Error {src['name']}: {e}")
                        continue
            
            logging.info(f"📊 Cycle: Telegram={stats.telegram_posts} Twitter={stats.twitter_posts} | {slot['name']} | Next: {delay}s")
            await asyncio.sleep(delay)
        
        except Exception as e:
            logging.critical(f"💥 Worker crashed: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(60)

# =========================== HEALTH SERVER ===========================
async def health(request):
    return web.Response(
        text=json.dumps({
            "status": "alive",
            "bot": "Unified News Bot (Telegram + Twitter)",
            "platforms": {
                "telegram": "enabled" if ENABLE_TELEGRAM else "disabled",
                "twitter": "enabled" if ENABLE_TWITTER else "disabled"
            },
            "stats": {
                "telegram_posts": stats.telegram_posts,
                "twitter_posts": stats.twitter_posts,
                "failed_posts": stats.failed_posts,
                "breaking_news": stats.breaking_news_count
            },
            "timestamp": datetime.now(ICT).isoformat()
        }),
        content_type="application/json"
    )

async def web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"🌐 Health server: http://0.0.0.0:{port}")

# =========================== MAIN ===========================
async def main():
    await asyncio.gather(
        web_server(),
        worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Bot stopped")
    except Exception as e:
        logging.critical(f"💥 Fatal: {e}\n{traceback.format_exc()}")