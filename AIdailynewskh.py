"""
AI Daily News KH v10.5 - Final Perfected Edition (Fixed)
========================================================
📸 Focus: Advanced Image Extraction (Fixing DAP News)
🎨 Style: Enterprise Formatting (Badges + Buttons)
🧠 Logic: Radar + Spam Filter + AI Translation
"""

import os
import asyncio
import json
import hashlib
import re
import logging
import ssl
import io
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from difflib import SequenceMatcher
from dataclasses import dataclass, field  # <--- បានបន្ថែមបន្ទាត់នេះ

# Third-party libraries
import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
import tweepy
from aiohttp import web
from PIL import Image

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION (ការកំណត់ប្រព័ន្ធ)
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

# System
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash-exp"
ICT = pytz.timezone('Asia/Phnom_Penh')

# Social Media Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_LINK = "https://t.me/AIDailyNewsKH"

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_LINK = "https://x.com/AIDailyNewskh"
WEBSITE_LINK = os.getenv("WEBSITE_LINK", "")

# Controls
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"
ENABLE_IMAGE_OPTIMIZATION = True

# Limits
CONTENT_QUALITY_THRESHOLD = 75
SIMILARITY_THRESHOLD = 0.70
TWITTER_DAILY_LIMIT = 15

# ═══════════════════════════════════════════════════════════════════════════
# 2. LOGGING & STATS
# ═══════════════════════════════════════════════════════════════════════════

class ProfessionalFormatter(logging.Formatter):
    COLORS = {'INFO': '\033[32m', 'WARNING': '\033[33m', 'ERROR': '\033[31m', 'RESET': '\033[0m'}
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

handler = logging.StreamHandler()
handler.setFormatter(ProfessionalFormatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

@dataclass
class SystemStatistics:
    telegram_posts: int = 0
    twitter_posts: int = 0
    articles_processed: int = 0
    spam_blocked: int = 0
    duplicates_blocked: int = 0
    low_quality_blocked: int = 0
    image_failures: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())

    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logger.info(f"\n📊 DAILY REPORT: {self.telegram_posts} posts yesterday.\n")
            self.__init__()

stats = SystemStatistics()

# ═══════════════════════════════════════════════════════════════════════════
# 3. INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

genai.configure(api_key=GEMINI_API_KEY)
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if (ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN) else None

twitter_client = None
twitter_api_v1 = None
if ENABLE_TWITTER and TWITTER_API_KEY:
    try:
        twitter_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET, access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET, wait_on_rate_limit=False)
        auth = tweepy.OAuth1UserHandler(TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        twitter_api_v1 = tweepy.API(auth)
        logger.info("✅ Twitter Connected")
    except Exception as e:
        logger.warning(f"⚠️ Twitter Init Failed: {e}")

db = None
try:
    if os.getenv("FIREBASE_CREDENTIALS"):
        cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
        if not firebase_admin._apps: firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("✅ Firebase Connected")
except Exception as e:
    logger.warning("⚠️ Firebase Not Connected (Running in Memory Mode)")

# ═══════════════════════════════════════════════════════════════════════════
# 4. ADVANCED IMAGE EXTRACTION (The Fix for DAP News)
# ═══════════════════════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

async def fetch_og_image(url: str) -> Optional[str]:
    """
    Digs into the website HTML to find the 'og:image' meta tag.
    Crucial for sites like DAP News that don't put images in RSS.
    """
    try:
        ssl_ctx = ssl.create_default_context(); ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, connector=aiohttp.TCPConnector(ssl=ssl_ctx), timeout=timeout) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    text = await r.text()
                    soup = BeautifulSoup(text, 'html.parser')
                    og_image = soup.find("meta", property="og:image")
                    if og_image and og_image.get("content"):
                        return og_image["content"]
    except: pass
    return None

async def download_image(url: str):
    """Downloads image bytes with proper headers."""
    try:
        ssl_ctx = ssl.create_default_context(); ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, connector=aiohttp.TCPConnector(ssl=ssl_ctx), timeout=timeout) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    data = await r.read()
                    if ENABLE_IMAGE_OPTIMIZATION:
                        # Optimize Image to prevent Telegram errors
                        img = Image.open(io.BytesIO(data))
                        if img.mode != 'RGB': img = img.convert('RGB')
                        out = io.BytesIO()
                        img.save(out, format='JPEG', quality=85, optimize=True)
                        return out.getvalue()
                    return data
    except Exception as e:
        logger.warning(f"⚠️ Image Download Error: {e}")
    return None

def get_best_image(entry) -> Optional[str]:
    """Tries RSS fields first."""
    try:
        if hasattr(entry, 'media_content'): return entry.media_content[0]['url']
        if hasattr(entry, 'media_thumbnail'): return entry.media_thumbnail[0]['url']
        soup = BeautifulSoup(entry.get('summary', '') or entry.get('description', ''), 'html.parser')
        img = soup.find('img')
        if img: return img.get('src')
    except: pass
    return None

# ═══════════════════════════════════════════════════════════════════════════
# 5. CORE LOGIC (SOURCES, RADAR, TRANSLATE)
# ═══════════════════════════════════════════════════════════════════════════

NEWS_SOURCES = {
    "cambodia": [
        {"name": "Khmer Times", "rss": "https://www.khmertimeskh.com/feed/", "priority": 10},
        {"name": "Thmey Thmey", "rss": "https://thmeythmey.com/feed", "priority": 10},
        {"name": "DAP News", "rss": "https://www.dap-news.com/feed", "priority": 9},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed", "priority": 8},
    ],
    "international": [
        {"name": "BBC World", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "priority": 10},
        {"name": "Reuters", "rss": "https://www.reutersagency.com/feed/", "priority": 10},
        {"name": "CNA", "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "priority": 9},
        {"name": "Bangkok Post", "rss": "https://www.bangkokpost.com/rss/data/topstories.xml", "priority": 10},
    ]
}

# Radar Keywords (To filter international news)
INTL_GROUP_A = ["cambodia", "khmer", "phnom penh", "hun manet", "preah vihear", "កម្ពុជា"]
INTL_GROUP_B = ["thailand", "thai", "bangkok", "border", "military", "clash", "troop", "soldier", "dispute", "ថៃ"]

SPAM_KEYWORDS = ["ឆ្នោត", "lottery", "casino", "betting", "gamble", "ល្បែង", "sex", "xxx", "porn", "partner", "sponsored", "buy", "sell"]
BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "គ្រោះថ្នាក់", "ផ្ទុះ", "ស្លាប់", "dead", "crisis", "attack", "fire"]

def is_relevant_international(article: Dict) -> Tuple[bool, str]:
    """Strict Radar Logic with Relaxed Rules for Breaking News"""
    if article['category'] == 'cambodia': return True, "Local"
    
    full_text = (article['title'] + " " + article['summary']).lower()
    
    # 1. Match Conflict Context
    if any(k in full_text for k in INTL_GROUP_A) and any(k in full_text for k in INTL_GROUP_B):
        return True, "✅ Radar Matched"
    
    # 2. Match Major Breaking News (Even if not Cambodia related)
    if article.get('is_breaking'): 
        return True, "✅ Major Breaking News"
    
    return False, "❌ Irrelevant"

def is_spam(text: str) -> bool:
    if not text: return True
    if any(k in text.lower() for k in SPAM_KEYWORDS): return True
    return False

async def translate_ai(article: Dict, platform: str) -> Dict:
    lang = "Khmer" if platform == "telegram" else "English"
    max_len = 600 if platform == "telegram" else 280
    
    prompt = f"""You are a News Editor.
Task: Summarize for {platform} ({lang}).
Article: {article['title']}
Context: {article['summary'][:1500]}

STRICT RULES:
1. TONE: Formal, Neutral, Professional.
2. FACTS: Who, What, Where, When.
3. OUTPUT: JSON ONLY.

JSON:
{{
    "title_{platform}": "Headline",
    "body_{platform}": "Summary..."
}}"""

    for _ in range(2):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
            data = json.loads(text)
            article[f"title_{platform}"] = data.get(f"title_{platform}", article['title'])
            article[f"body_{platform}"] = data.get(f"body_{platform}", article['summary'])[:max_len]
            return article
        except: await asyncio.sleep(1)
    
    article[f"title_{platform}"] = article['title']
    article[f"body_{platform}"] = article['summary'][:max_len]
    return article

# ═══════════════════════════════════════════════════════════════════════════
# 6. POSTING (ENTERPRISE FORMAT)
# ═══════════════════════════════════════════════════════════════════════════

async def post_to_telegram_channel(article: Dict, quality_score: int) -> bool:
    if not telegram_bot: return False
    
    # Header logic
    if article['category'] == "international":
        header = "🌏 **មតិអន្តរជាតិ (Intl Focus)**"
    elif article['is_breaking']:
        header = "🚨 **BREAKING NEWS**"
    else:
        header = "🇰🇭 **ព័ត៌មានជាតិ**"
        
    badge = "⭐" if quality_score >= 85 else ""
    caption = (
        f"{header}\n\n"
        f"{badge} <b>{article['title_telegram']}</b>\n\n"
        f"{article['body_telegram']}\n\n"
        f"{'─' * 30}\n"
        f"📰 ប្រភព: {article['source']}\n"
        f"🕐 {datetime.now(ICT):%d/%m/%Y • %H:%M} ICT"
    )
    
    # Professional Buttons
    buttons = [
        [InlineKeyboardButton("អានពេញលេញ 📖", url=article["link"])],
        [InlineKeyboardButton("Telegram 📢", url=TELEGRAM_LINK), InlineKeyboardButton("Twitter ✖️", url=TWITTER_LINK)]
    ]
    if WEBSITE_LINK: buttons[1].append(InlineKeyboardButton("Web 🌐", url=WEBSITE_LINK))
    
    try:
        # Priority: Send Photo -> Fallback: Send Text
        if article.get("image_bytes"):
            await telegram_bot.send_photo(TELEGRAM_CHANNEL_ID, article["image_bytes"], caption=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await telegram_bot.send_message(TELEGRAM_CHANNEL_ID, caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return True
    except Exception as e:
        logger.error(f"TG Post Failed: {e}")
        return False

async def post_to_twitter_account(article: Dict, quality_score: int) -> bool:
    if not twitter_client: return False
    text = f"🇰🇭 {article['title_twitter']}\n\n{article['body_twitter'][:180]}...\n\n#Cambodia #News\n🔗 {article['link']}"
    try:
        mid = None
        if article.get("image_bytes"):
            media = await asyncio.to_thread(twitter_api_v1.media_upload, filename="news.jpg", file=io.BytesIO(article["image_bytes"]))
            mid = media.media_id
        if mid: await asyncio.to_thread(twitter_client.create_tweet, text=text, media_ids=[mid])
        else: await asyncio.to_thread(twitter_client.create_tweet, text=text)
        return True
    except: return False

# ═══════════════════════════════════════════════════════════════════════════
# 7. WORKER & MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_rss_safe(url):
    try:
        ssl_ctx = ssl.create_default_context(); ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=HEADERS, connector=aiohttp.TCPConnector(ssl=ssl_ctx), timeout=timeout) as s:
            async with s.get(url) as r:
                return feedparser.parse(await r.text()) if r.status == 200 else None
    except: return None

async def worker():
    logger.info("="*60)
    logger.info("🚀 AI News Bot v10.5 (Deep Image Edition) Started")
    logger.info("📸 Features: Auto-Fetch OG:Image for Missing RSS Images")
    logger.info("="*60)
    
    while True:
        stats.reset_if_new_day()
        recent_titles = [] 
        
        # Smart Delay based on Time
        h = datetime.now(ICT).hour
        if 0 <= h < 6: delay = 300      # Night (Slow)
        elif 6 <= h < 20: delay = 60    # Day (Fast)
        else: delay = 120               # Evening (Medium)

        for category, sources in NEWS_SOURCES.items():
            for src in sources:
                try:
                    feed = await fetch_rss_safe(src['rss'])
                    if not feed or not feed.entries: continue
                    
                    entry = feed.entries[0]
                    stats.articles_processed += 1
                    
                    # 1. DB Check
                    aid = hashlib.md5(f"{entry.title}{entry.link}".encode()).hexdigest()
                    if db:
                        doc = await asyncio.to_thread(db.collection('posted_articles').document(aid).get)
                        if doc.exists: continue
                    
                    # 2. IMAGE EXTRACTION (CRITICAL FIX)
                    # Try getting image from RSS
                    img_url = get_best_image(entry)
                    if not img_url:
                        # If failed, go DIG into the website
                        logger.info(f"   🔍 Digging image for: {entry.title[:30]}")
                        img_url = await fetch_og_image(entry.link)
                    
                    article = {
                        "title": entry.title, "link": entry.link, "source": src['name'], "category": category,
                        "summary": BeautifulSoup(entry.get('summary', ''), 'html.parser').get_text()[:2000],
                        "image_url": img_url,
                        "is_breaking": any(k in entry.title.lower() for k in BREAKING_KEYWORDS)
                    }
                    
                    # 3. FILTERS
                    is_rel, reason = is_relevant_international(article)
                    if not is_rel: continue
                    
                    if is_spam(article['title']):
                        stats.spam_blocked += 1; continue
                    
                    # 4. DOWNLOAD IMAGE BYTES
                    logger.info(f"✨ NEW: {article['title'][:50]}")
                    if article['image_url']:
                        article['image_bytes'] = await download_image(article['image_url'])
                    else:
                        article['image_bytes'] = None
                        stats.image_failures += 1
                    
                    # 5. POSTING
                    processed = await translate_ai(article, "telegram")
                    
                    # Calculate simple quality score for badge (0-100)
                    q_score = 80 + (10 if article['is_breaking'] else 0) + (10 if article['image_bytes'] else -10)
                    
                    if await post_to_telegram_channel(processed, q_score):
                        stats.telegram_posts += 1
                        if db:
                            await asyncio.to_thread(db.collection('posted_articles').document(aid).set, {
                                'article_id': aid, 'title': article['title'], 'updated_at': firestore.SERVER_TIMESTAMP
                            }, merge=True)
                        
                        # Post to Twitter (Only if Breaking or Cambodia)
                        if ENABLE_TWITTER and (article['is_breaking'] or category == 'cambodia'):
                             processed_tw = await translate_ai(article, "twitter")
                             await post_to_twitter_account(processed_tw, q_score)
                             
                        await asyncio.sleep(60) # Cooldown after posting
                        
                except Exception as e:
                    logger.error(f"Err {src['name']}: {e}")
            
            await asyncio.sleep(delay)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot v10.5 Running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    await worker()

if __name__ == "__main__":
    asyncio.run(main())