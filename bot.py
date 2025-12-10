"""
Ultimate Cambodia News Bot v6.5 - Official Strict Edition
=========================================================
🎯 Philosophy: Professionalism, Neutrality, Accuracy
🎯 Status: PRODUCTION READY

Key Upgrades for Official Use:
✅ Senior Editor AI Persona (Formal Tone)
✅ High Quality Threshold (80/100)
✅ Cross-Source Duplicate Elimination
✅ Zero Tolerance for Clickbait/Spam
"""

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
import ssl
import io
from datetime import datetime, timedelta
from urllib.parse import urljoin
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict
from difflib import SequenceMatcher

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
import tweepy
from aiohttp import web
from PIL import Image

import firebase_admin
from firebase_admin import credentials, firestore

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION (STRICT MODE)
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

# API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# ប្រើ Model ថ្មី និងលឿនបំផុត
GEMINI_MODEL = "gemini-2.0-flash-exp" 

# Social Media Links
TELEGRAM_LINK = "https://t.me/AIDailyNewsKH"
TWITTER_LINK = "https://x.com/AIDailyNewskh"
WEBSITE_LINK = os.getenv("WEBSITE_LINK", "")

# Platform Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Platform Control
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"

# ➤ STRICT SETTINGS (ចំណុចកែប្រែសំខាន់)
TWITTER_DAILY_LIMIT = 12  # កាត់បន្ថយចំនួន Post អោយតិច តែយកគុណភាព
TWITTER_COOLDOWN_MINUTES = 45 # ទុកចន្លោះពេលយូរបន្តិច

# ពិន្ទុគុណភាពត្រូវតែលើស 80 ទើប Post (ពីមុន 65)
CONTENT_QUALITY_THRESHOLD = 80 
# បើចំណងជើងដូចគ្នាលើស 60% ចាត់ទុកថាស្ទួន (ការពារស្ទួនតឹងរ៉ឹង)
SIMILARITY_THRESHOLD = 0.60 

ENABLE_IMAGE_OPTIMIZATION = True

# Timezone
ICT = pytz.timezone('Asia/Phnom_Penh')

# ═══════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'
    }
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter("%(asctime)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])

# ═══════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY missing!")

telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if (ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN) else None

twitter_client = None
twitter_api_v1 = None
if ENABLE_TWITTER and TWITTER_API_KEY:
    try:
        twitter_client = tweepy.Client(
            bearer_token=TWITTER_BEARER_TOKEN,
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
            wait_on_rate_limit=False
        )
        auth = tweepy.OAuth1UserHandler(TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        twitter_api_v1 = tweepy.API(auth)
    except Exception as e:
        logging.error(f"❌ Twitter Error: {e}")

# Firebase
db = None
try:
    firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_creds_str:
        cred = credentials.Certificate(json.loads(firebase_creds_str))
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("✅ Firebase Connected")
except Exception as e:
    logging.critical(f"❌ Firebase Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# SOURCES (Clean List - Only High Authority)
# ═══════════════════════════════════════════════════════════════════════════

NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed", "url": "https://thmeythmey.com", "priority": 10},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/", "url": "https://www.khmertimeskh.com", "priority": 10},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed", "url": "https://www.dap-news.com", "priority": 9},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed", "url": "https://kohsantepheapdaily.com.kh", "priority": 8},
    ],
    "international": [
        {"name": "BBC World",      "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "url": "https://www.bbc.com", "priority": 10},
        {"name": "Reuters",        "rss": "https://www.reutersagency.com/feed/", "url": "https://www.reuters.com", "priority": 10},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com", "priority": 9},
    ]
}

# ═══════════════════════════════════════════════════════════════════════════
# FILTERS (STRICT)
# ═══════════════════════════════════════════════════════════════════════════

SPAM_KEYWORDS = [
    "ឆ្នោត", "lottery", "casino", "betting", "gamble", "ល្បែង",
    "sex", "xxx", "porn", "18+", "partner", "sponsored",
    "promotion", "discount", "ទិញ", "លក់", "buy", "sell", "free money",
    "រាសី", "horoscope", "fortune", "ចុចមើល"
]

BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "គ្រោះថ្នាក់", "ផ្ទុះ", "ស្លាប់", "dead", "crisis"]

@dataclass
class BotStats:
    telegram_posts: int = 0
    twitter_posts: int = 0
    blocked_count: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())

    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            self.telegram_posts = 0
            self.twitter_posts = 0
            self.blocked_count = 0
            self.last_reset = today
            logging.info("📊 Stats Reset")

stats = BotStats()

def is_spam(text: str) -> bool:
    if not text: return True
    text_lower = text.lower()
    
    # 1. Keyword Block
    for k in SPAM_KEYWORDS:
        if k in text_lower: return True
    
    # 2. Pattern Block (Too many numbers = Lottery/Spam)
    digit_count = sum(c.isdigit() for c in text)
    if len(text) > 0 and (digit_count / len(text)) > 0.4: return True
    
    return False

def check_semantic_duplicate(new_title: str, recent_titles: List[str]) -> bool:
    """Advanced Logic: Finds same news even if title is slightly different"""
    if not recent_titles: return False
    
    # Remove special chars for comparison
    clean_new = re.sub(r'[^\w\s]', '', new_title.lower())
    
    for old_title in recent_titles:
        clean_old = re.sub(r'[^\w\s]', '', old_title.lower())
        ratio = SequenceMatcher(None, clean_new, clean_old).ratio()
        
        if ratio > SIMILARITY_THRESHOLD:
            logging.info(f"🚫 Duplicate Blocked ({ratio:.2f}): '{new_title}' vs '{old_title}'")
            return True
    return False

def calculate_strict_quality(article: Dict) -> int:
    score = 50
    
    # Length Check
    if len(article.get('summary', '')) > 300: score += 20
    elif len(article.get('summary', '')) < 100: score -= 20
    
    # Source Priority
    prio = next((s['priority'] for cat in NEWS_SOURCES.values() for s in cat if s['name'] == article['source']), 5)
    score += (prio - 5) * 4 # Give more weight to high priority sources
    
    # Spammy Title Penalty
    if "!" in article['title']: score -= 10
    if "?" in article['title']: score -= 5
    
    # Breaking News Bonus
    if any(k in article['title'].lower() for k in BREAKING_KEYWORDS): score += 20
    
    return max(0, min(100, score))

# ═══════════════════════════════════════════════════════════════════════════
# CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_rss_safe(url: str) -> Optional[feedparser.FeedParserDict]:
    headers = {"User-Agent": "CambodiaNewsBot/Official"}
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    try:
        async with aiohttp.ClientSession(headers=headers, connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as s:
            async with s.get(url, timeout=15) as r:
                if r.status == 200:
                    return feedparser.parse(await r.text())
    except: pass
    return None

async def download_image_optimized(url: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=10) as r:
                if r.status == 200:
                    data = await r.read()
                    if len(data) > 8 * 1024 * 1024: return None # Skip > 8MB
                    
                    if ENABLE_IMAGE_OPTIMIZATION:
                        img = Image.open(io.BytesIO(data))
                        if img.mode != 'RGB': img = img.convert('RGB')
                        out = io.BytesIO()
                        img.save(out, format='JPEG', quality=85, optimize=True)
                        return out.getvalue()
                    return data
    except: pass
    return None

# ➤ OFFICIAL TRANSLATION PROMPT (The "Strict" Part)
async def translate_official(article: Dict, platform: str) -> Dict:
    lang = "Khmer" if platform == "telegram" else "English"
    max_len = 500 if platform == "telegram" else 200
    
    prompt = f"""You are a Senior News Editor for a reputable news agency.
Task: Translate and summarize this news for {platform} ({lang}).

Source: {article['title']}
Context: {article['summary'][:2000]}

STRICT EDITORIAL GUIDELINES:
1. TONE: Formal, Neutral, Objective. NO slang. NO emojis in body text.
2. ACCURACY: Summarize facts (Who, What, Where, When). Do not add opinions.
3. TITLE: Professional headline. No clickbait.
4. FORMAT: Return JSON ONLY.

JSON Format:
{{
    "title_{platform}": "Formal Headline Here",
    "body_{platform}": "Concise summary of facts here..."
}}
"""
    for _ in range(2):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
            data = json.loads(text)
            
            t_key = f"title_{platform}"
            b_key = f"body_{platform}"
            
            article[t_key] = data.get(t_key, article['title'])
            article[b_key] = data.get(b_key, article['summary'])[:max_len]
            return article
        except: 
            await asyncio.sleep(2)
            
    # Fallback
    article[f"title_{platform}"] = article['title']
    article[f"body_{platform}"] = article['summary'][:max_len]
    return article

# ═══════════════════════════════════════════════════════════════════════════
# POSTING
# ═══════════════════════════════════════════════════════════════════════════

async def post_telegram(article: Dict, cat: str):
    if not telegram_bot: return False
    
    flag = "🇰🇭" if cat == "cambodia" else "🌍"
    is_breaking = any(k in article['title'].lower() for k in BREAKING_KEYWORDS)
    header = "🚨 BREAKING" if is_breaking else flag
    
    text = (
        f"{header} <b>{article['title_telegram']}</b>\n\n"
        f"{article['body_telegram']}\n\n"
        f"─────────────────\n"
        f"ប្រភព: {article['source']}\n"
        f"🗓 {datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានលម្អិត 🔗", url=article["link"])],
        [InlineKeyboardButton("Join Channel 📢", url=TELEGRAM_LINK)]
    ])
    
    try:
        if article.get("image_url"):
            img = await download_image_optimized(article["image_url"])
            if img:
                await telegram_bot.send_photo(TELEGRAM_CHANNEL_ID, img, caption=text, parse_mode=ParseMode.HTML, reply_markup=buttons)
                return True
        await telegram_bot.send_message(TELEGRAM_CHANNEL_ID, text, parse_mode=ParseMode.HTML, reply_markup=buttons)
        return True
    except Exception as e:
        logging.error(f"Telegram Error: {e}")
        return False

async def post_twitter(article: Dict):
    if not twitter_client: return False
    
    text = f"🇰🇭 {article['title_twitter']}\n\n{article['body_twitter'][:180]}...\n\n#Cambodia #News\n🔗 {article['link']}"
    
    try:
        mid = None
        if article.get("image_url"):
            img = await download_image_optimized(article["image_url"])
            if img:
                media = await asyncio.to_thread(twitter_api_v1.media_upload, filename="news.jpg", file=io.BytesIO(img))
                mid = media.media_id
        
        if mid: await asyncio.to_thread(twitter_client.create_tweet, text=text, media_ids=[mid])
        else: await asyncio.to_thread(twitter_client.create_tweet, text=text)
        return True
    except Exception as e:
        logging.error(f"Twitter Error: {e}")
        return False

async def db_check_and_save(aid: str, article: Dict, tg: bool, tw: bool):
    if not db: return False, False
    
    # Check
    ref = db.collection('posted_articles').document(aid)
    doc = await asyncio.to_thread(ref.get)
    if doc.exists:
        d = doc.to_dict()
        return d.get('telegram_posted', False), d.get('twitter_posted', False)
    
    # Save
    if tg or tw:
        await asyncio.to_thread(ref.set, {
            'article_id': aid,
            'title': article['title'], # For semantic check
            'source': article['source'],
            'telegram_posted': tg,
            'twitter_posted': tw,
            'updated_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
    
    return False, False

async def get_recent_titles_list() -> List[str]:
    if not db: return []
    try:
        cutoff = datetime.now(pytz.utc) - timedelta(hours=24)
        docs = db.collection('posted_articles').where('updated_at', '>=', cutoff).stream()
        return [d.to_dict().get('title', '') for d in docs]
    except: return []

# ═══════════════════════════════════════════════════════════════════════════
# WORKER
# ═══════════════════════════════════════════════════════════════════════════

async def worker():
    logging.info("🚀 Official News Bot Started (Strict Mode)")
    
    while True:
        stats.reset_if_new_day()
        recent_titles = await get_recent_titles_list()
        
        # Schedule Logic (Slow down at night)
        h = datetime.now(ICT).hour
        delay = 600 if 0 <= h < 5 else (30 if 6 <= h < 20 else 180)
        
        for cat, sources in NEWS_SOURCES.items():
            for src in sources:
                try:
                    feed = await fetch_rss_safe(src['rss'])
                    if not feed or not feed.entries: continue
                    
                    entry = feed.entries[0]
                    aid = hashlib.md5(f"{entry.title}{entry.link}".encode()).hexdigest()
                    
                    # 1. Check DB (Exact Match)
                    tg_done, tw_done = await db_check_and_save(aid, {}, False, False)
                    if tg_done and tw_done: continue
                    
                    # 2. Strict Filter Check
                    if is_spam(entry.title): continue
                    if check_semantic_duplicate(entry.title, recent_titles): continue
                    
                    # 3. Build Article
                    img = None
                    if hasattr(entry, 'media_content'): img = entry.media_content[0]['url']
                    
                    article = {
                        "title": entry.title,
                        "link": entry.link,
                        "summary": BeautifulSoup(entry.get('summary', ''), 'html.parser').get_text()[:2000],
                        "source": src['name'],
                        "image_url": img
                    }
                    
                    # 4. Quality Check
                    score = calculate_strict_quality(article)
                    if score < CONTENT_QUALITY_THRESHOLD:
                        logging.warning(f"⚠️ Low Quality ({score}): {article['title'][:30]}")
                        stats.blocked_count += 1
                        continue
                        
                    # 5. Process & Post
                    tg_ok = False
                    if ENABLE_TELEGRAM and not tg_done:
                        processed = await translate_official(article, "telegram")
                        if await post_telegram(processed, cat):
                            tg_ok = True
                            stats.telegram_posts += 1
                            recent_titles.append(entry.title) # Add to memory
                    
                    tw_ok = False
                    if ENABLE_TWITTER and not tw_done and cat == "cambodia":
                         # Only post Breaking News or High Score to Twitter to save quota
                         if score > 85:
                            processed = await translate_official(article, "twitter")
                            if await post_twitter(processed):
                                tw_ok = True
                                stats.twitter_posts += 1
                    
                    if tg_ok or tw_ok:
                        await db_check_and_save(aid, article, tg_ok, tw_ok)
                        logging.info(f"✅ Posted: {entry.title[:40]}")
                        await asyncio.sleep(delay) # Wait before next post
                        
                except Exception as e:
                    logging.error(f"Source Error ({src['name']}): {e}")
            
            await asyncio.sleep(10) # Pause between categories

# ═══════════════════════════════════════════════════════════════════════════
# SERVER
# ═══════════════════════════════════════════════════════════════════════════

async def health(r):
    return web.json_response({
        "status": "strict_mode_active",
        "quality_threshold": CONTENT_QUALITY_THRESHOLD,
        "stats": stats.__dict__
    })

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    await worker()

if __name__ == "__main__":
    asyncio.run(main())