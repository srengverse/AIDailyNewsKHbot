# main.py – Unified News Bot (Telegram + Twitter/X)
# Deploy to Render.com
# Version: 3.2 (Python 3.13 Compatible)

# === PYTHON 3.13 COMPATIBILITY FIX ===
import sys
if sys.version_info >= (3, 13):
    # Polyfill for removed imghdr module
    import imghdr as _imghdr_placeholder
    sys.modules['imghdr'] = type(sys)('imghdr')
    sys.modules['imghdr'].what = lambda file, h=None: None

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
import ssl
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

# FIREBASE IMPORTS
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import FieldFilter

# =========================== CONFIG ===========================
load_dotenv()

# Gemini AI (Stable 1.5 Flash)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-1.5-flash"

# Links Configuration
TELEGRAM_LINK = "https://t.me/AIDailyNewsKH"
TWITTER_LINK = "https://x.com/AIDailyNewskh"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Twitter/X
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Enable/Disable platforms
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"

# LIMITS FOR FREE TIER
TWITTER_DAILY_LIMIT = 15     
TWITTER_RESERVE_SLOTS = 3    
TWITTER_COOLDOWN_MINUTES = 30 

# Timezone Cambodia
ICT = pytz.timezone('Asia/Phnom_Penh')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
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
            wait_on_rate_limit=False 
        )
        auth = tweepy.OAuth1UserHandler(
            TWITTER_API_KEY, TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
        )
        twitter_api_v1 = tweepy.API(auth)
        logging.info("✅ Twitter bot initialized")
    except Exception as e:
        logging.error(f"❌ Twitter init failed: {e}")

# =========================== FIREBASE SETUP ===========================
db = None
try:
    firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS")
    
    if firebase_creds_str:
        cred_dict = json.loads(firebase_creds_str)
        cred = credentials.Certificate(cred_dict)
        logging.info("🔥 Loading Firebase from Environment Variable...")
    elif os.path.exists("firebase_key.json"):
        cred = credentials.Certificate("firebase_key.json")
        logging.info("🔥 Loading Firebase from local file...")
    else:
        raise FileNotFoundError("No FIREBASE_CREDENTIALS env var or firebase_key.json found!")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    logging.info("✅ Firebase Firestore Connected!")

except Exception as e:
    logging.critical(f"❌ Firebase Setup Failed: {e}")

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

# =========================== STATISTICS ===========================
@dataclass
class BotStats:
    telegram_posts: int = 0
    twitter_posts: int = 0
    breaking_news_count: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())
    
    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logging.info(f"📊 Daily Stats Reset: Telegram={self.telegram_posts}, Twitter={self.twitter_posts}")
            self.telegram_posts = 0
            self.twitter_posts = 0
            self.breaking_news_count = 0
            self.last_reset = today

stats = BotStats()

# =========================== BREAKING NEWS & SCHEDULING ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "breaking"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "killed", "crisis", "attack"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "BBC News", "Al Jazeera"}

def get_current_slot() -> Dict:
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
    score = 0
    full_text = f"{article['title'].lower()} {article.get('title_kh', '').lower()} {article.get('summary', '').lower()}"
    
    for w in BREAKING_KEYWORDS_EN:
        if w in full_text: score += 100
    for w in BREAKING_KEYWORDS_KH:
        if w in full_text: score += 120
    
    if article["source"] in HIGH_PRIORITY_SOURCES: score += 50
    return score >= 100

# =========================== DATABASE OPERATIONS ===========================
async def is_posted(aid: str, platform: str) -> bool:
    if not db: return False
    try:
        doc_ref = db.collection('posted_articles').document(aid)
        doc = await asyncio.to_thread(doc_ref.get)
        if doc.exists:
            data = doc.to_dict()
            return data.get(f"{platform}_posted", False)
        return False
    except Exception as e:
        logging.error(f"Firebase Check Error: {e}")
        return False

async def mark_as_posted(aid: str, cat: str, source: str, platform: str):
    if not db: return
    max_retries = 3
    for attempt in range(max_retries):
        try:
            doc_ref = db.collection('posted_articles').document(aid)
            data = {
                "article_id": aid,
                "category": cat,
                "source": source,
                "updated_at": firestore.SERVER_TIMESTAMP,
                f"{platform}_posted": True
            }
            if platform == "twitter":
                data["twitter_posted_at"] = firestore.SERVER_TIMESTAMP
            
            await asyncio.to_thread(doc_ref.set, data, merge=True)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                logging.error(f"❌ Failed to mark posted: {e}")

async def get_daily_twitter_count() -> int:
    if not db: return 0
    try:
        now = datetime.now(ICT)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        docs = await asyncio.to_thread(
            lambda: db.collection('posted_articles')
            .where(filter=FieldFilter('twitter_posted', '==', True))
            .where(filter=FieldFilter('updated_at', '>=', start_of_day))
            .stream()
        )
        count = sum(1 for _ in docs)
        return count
    except Exception as e:
        logging.error(f"Failed to get daily tweet count: {e}")
        return 0

# =========================== RSS & IMAGE ===========================
async def fetch_rss(url: str, source_name: str) -> Optional[feedparser.FeedParserDict]:
    headers = {"User-Agent": "KhmerNewsBot/2.0"}
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    try:
        ssl_ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT for VNA
    except AttributeError: pass

    for attempt in range(3):
        try:
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(headers=headers, connector=connector, timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        feed = feedparser.parse(await r.text())
                        if feed.entries: return feed
        except Exception as e:
            logging.warning(f"RSS fetch {source_name}: {e}")
        if attempt < 2: await asyncio.sleep(2)
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

async def download_image(url: str, max_size_mb: int = 10) -> Optional[bytes]:
    """Downloads image data (for Twitter upload)"""
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200: return None
                img_data = await response.read()
                if len(img_data) > max_size_mb * 1024 * 1024: return None
                return img_data
    except: return None

async def get_article_id(title: str, link: str) -> str:
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except:
        return str(hash(f"{title}{link}"))

# =========================== GEMINI TRANSLATE ===========================
async def translate(article: Dict, platform: str = "telegram", max_retries: int = 3) -> Dict:
    if platform == "twitter":
        max_title, max_body = 100, 200
        prompt = f"Translate to natural English for Twitter:\nTitle: {article['title']}\nContent: {article['summary'][:2800]}\nReturn JSON: {{'title_en': '...', 'body_en': '...'}}"
    else:
        max_title, max_body = 200, 500
        prompt = f"Translate to natural Khmer for Telegram:\nTitle: {article['title']}\nContent: {article['summary'][:2800]}\nReturn JSON: {{'title_kh': '...', 'body_kh': '...'}}"

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
            
            await asyncio.sleep(5)
            return article
        except Exception:
            if attempt < max_retries - 1: await asyncio.sleep(2)
    
    # Fallback
    if platform == "twitter":
        article["title_en"] = article["title"][:max_title]
        article["body_en"] = article["summary"][:max_body]
    else:
        article["title_kh"] = article["title"][:max_title]
        article["body_kh"] = article["summary"][:max_body]
    return article

# =========================== POSTING LOGIC ===========================
async def post_to_telegram(article: Dict, emoji: str, category: str) -> bool:
    if not telegram_bot: return False
    
    flag = {"thai": "🇹🇭", "vietnamese": "🇻🇳", "cambodia": "🇰🇭"}.get(category, "🌍")
    caption = f"{emoji} {flag} <b>{article['title_kh']}</b>\n\n{article['body_kh']}\n\n────────────────\nប្រភព: {article['source']}\n{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📖", url=article["link"])],
        [InlineKeyboardButton("Join Telegram 📢", url=TELEGRAM_LINK), InlineKeyboardButton("Follow X ✖️", url=TWITTER_LINK)]
    ])
    
    if article.get("image_url"):
        img_data = await download_image(article["image_url"])
        if img_data:
            try:
                await telegram_bot.send_photo(TELEGRAM_CHANNEL_ID, photo=img_data, caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=buttons)
                logging.info(f"✅ Telegram PHOTO: {article['title_kh'][:40]}")
                return True
            except: pass
    
    try:
        await telegram_bot.send_message(TELEGRAM_CHANNEL_ID, text=caption + f"\n\n🔗 {article['link']}", parse_mode=ParseMode.HTML, reply_markup=buttons)
        logging.info(f"✅ Telegram TEXT: {article['title_kh'][:40]}")
        return True
    except Exception as e:
        logging.error(f"Telegram error: {e}")
        return False

async def post_to_twitter(article: Dict, category: str, is_breaking: bool = False) -> bool:
    if not twitter_client or category != "cambodia": return False
    
    emoji = "🚨 BREAKING" if is_breaking else "📰"
    text = f"{emoji} 🇰🇭 {article.get('title_en', article['title'])}\n\n"
    if article.get('body_en'): text += f"{article['body_en']}\n\n"
    text += "#Cambodia #KhmerNews\n"
    text += f"Join Telegram: {TELEGRAM_LINK}\n🔗 {article['link']}"
    
    if len(text) > 280:
        text = f"{emoji} 🇰🇭 {article.get('title_en', article['title'])}\n\n#Cambodia\nTelegram: {TELEGRAM_LINK}\n🔗 {article['link']}"

    try:
        media_id = None
        if article.get("image_url"):
            img_data = await download_image(article["image_url"], max_size_mb=5)
            if img_data:
                try:
                    media = await asyncio.to_thread(twitter_api_v1.media_upload, filename="image.jpg", file=img_data)
                    media_id = media.media_id
                except: pass
        
        if media_id:
            await asyncio.to_thread(twitter_client.create_tweet, text=text, media_ids=[media_id])
        else:
            await asyncio.to_thread(twitter_client.create_tweet, text=text)
        
        logging.info(f"✅ Twitter (EN): {article.get('title_en', article['title'])[:40]}")
        return True
    except tweepy.errors.TooManyRequests:
        raise
    except Exception as e:
        logging.error(f"Twitter error: {e}")
        return False

# =========================== MAIN WORKER ===========================
async def worker():
    logging.info("🚀 Unified News Bot Started (v3.2 Python 3.13 Compatible)")
    boost_until, twitter_cooldown_until = None, None
    
    while True:
        try:
            stats.reset_if_new_day()
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            if twitter_cooldown_until and now > twitter_cooldown_until:
                logging.info("✅ Twitter Cooldown ended.")
                twitter_cooldown_until = None

            if boost_until and now < boost_until:
                max_posts, delay = 20, 60
            else:
                max_posts, delay, boost_until = slot["max"] // 4, slot["delay"], None
            
            posted_count = 0
            daily_tweets = await get_daily_twitter_count()
            tw_full = daily_tweets >= TWITTER_DAILY_LIMIT
            
            tw_status = "ACTIVE"
            if twitter_cooldown_until: 
                tw_status = f"COOLDOWN ({int((twitter_cooldown_until - now).total_seconds()/60)}m)"
            elif tw_full: 
                tw_status = "FULL"

            categories = [("cambodia", "🇰🇭"), ("international", "🌍"), ("thai", "📰"), ("vietnamese", "📰")]
            for cat, emoji in categories:
                if posted_count >= max_posts: break
                for src in NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts: break
                    try:
                        feed = await fetch_rss(src["rss"], src["name"])
                        if not feed or not feed.entries: continue
                        
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        tg_posted = await is_posted(aid, "telegram") if ENABLE_TELEGRAM else True
                        tw_posted = await is_posted(aid, "twitter") if ENABLE_TWITTER else True
                        if tg_posted and tw_posted: continue
                        
                        article = {
                            "title": entry.title, "link": entry.link,
                            "summary": BeautifulSoup(entry.get("summary", "") or "", "html.parser").get_text(strip=True)[:1000],
                            "image_url": get_image(entry, src["url"]),
                            "source": src["name"]
                        }
                        
                        breaking = is_breaking_news(article)
                        if breaking and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED!")
                            boost_until = now + timedelta(minutes=15)
                            stats.breaking_news_count += 1
                        
                        if ENABLE_TELEGRAM and not tg_posted:
                            art = await translate(article.copy(), "telegram")
                            if await post_to_telegram(art, "🚨 BREAKING " + emoji if breaking else emoji, cat):
                                await mark_as_posted(aid, cat, src["name"], "telegram")
                                stats.telegram_posts += 1; posted_count += 1
                                await asyncio.sleep(5)
                        
                        if ENABLE_TWITTER and not tw_posted and cat == "cambodia" and not twitter_cooldown_until and not tw_full:
                            try:
                                art = await translate(article.copy(), "twitter")
                                if await post_to_twitter(art, cat, breaking):
                                    await mark_as_posted(aid, cat, src["name"], "twitter")
                                    stats.twitter_posts += 1; posted_count += 1
                                    await asyncio.sleep(10)
                            except tweepy.errors.TooManyRequests:
                                logging.warning("⚠️ Twitter Rate Limit! Cooldown 30m.")
                                twitter_cooldown_until = now + timedelta(minutes=TWITTER_COOLDOWN_MINUTES)

                    except Exception as e: logging.error(f"Source {src['name']} error: {e}")
            
            logging.info(f"📊 Cycle: TG={stats.telegram_posts} TW={daily_tweets}/{TWITTER_DAILY_LIMIT} [{tw_status}] | {slot['name']} | Next: {delay}s")
            await asyncio.sleep(delay)
        
        except Exception as e:
            logging.critical(f"💥 Worker crashed: {e}")
            await asyncio.sleep(60)

async def health(request):
    daily_tw = await get_daily_twitter_count()
    return web.Response(text=json.dumps({
        "status": "alive", "version": "3.2",
        "twitter": {"used": daily_tw, "limit": TWITTER_DAILY_LIMIT},
        "stats": {"telegram": stats.telegram_posts, "breaking": stats.breaking_news_count}
    }), content_type="application/json")

async def stats_endpoint(request):
    daily_tw = await get_daily_twitter_count()
    try:
        docs = await asyncio.to_thread(lambda: db.collection('posted_articles').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(5).stream())
        latest = [{"source": d.to_dict().get("source"), "time": str(d.to_dict().get("updated_at"))} for d in docs]
    except: latest = []
    return web.Response(text=json.dumps({"latest": latest, "daily_tw": daily_tw}), content_type="application/json")

async def web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/stats", stats_endpoint)
    runner = web.AppRunner(app); await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info(f"🌐 Server running on port {port}")

async def main(): await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass