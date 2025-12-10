"""
Professional Cambodia News Bot v10.0 - Enterprise Radar Edition
===============================================================
🏗️ Base Structure: v7.0 Enterprise (Preserving your formatting)
🧠 Intelligence: v8.1 Radar Logic (Smart Filtering)
🎨 Style: High-End Journalistic Standard

Status: PRODUCTION READY
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
from typing import Optional, Dict, List, Tuple
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
from telegram.error import NetworkError, TimedOut, RetryAfter
import tweepy
from aiohttp import web
from PIL import Image

import firebase_admin
from firebase_admin import credentials, firestore

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

# System
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
ICT = pytz.timezone('Asia/Phnom_Penh')

# Social Media
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
# 2. LOGGING & STATS (ENTERPRISE STYLE)
# ═══════════════════════════════════════════════════════════════════════════

class ProfessionalFormatter(logging.Formatter):
    """Restoring your beautiful log format"""
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
    irrelevant_intl_blocked: int = 0
    breaking_news: int = 0
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
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if ENABLE_TELEGRAM else None

twitter_client = None
twitter_api_v1 = None
if ENABLE_TWITTER and TWITTER_API_KEY:
    try:
        twitter_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET, access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET, wait_on_rate_limit=False)
        auth = tweepy.OAuth1UserHandler(TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        twitter_api_v1 = tweepy.API(auth)
        logger.info("✅ Twitter Connected")
    except Exception as e:
        logger.error(f"❌ Twitter Init Failed: {e}")

db = None
try:
    if os.getenv("FIREBASE_CREDENTIALS"):
        cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("✅ Firebase Connected")
except: logger.warning("⚠️ Firebase not connected (Running in memory mode)")

# ═══════════════════════════════════════════════════════════════════════════
# 4. SOURCES & RADAR LOGIC
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

# ➤ RADAR SYSTEM: The "Brain" of the bot
# Must match GROUP A (Cambodia) AND GROUP B (Context)
INTL_GROUP_A = ["cambodia", "khmer", "phnom penh", "hun manet", "hun sen", "preah vihear", "angkor", "កម្ពុជា"]
INTL_GROUP_B = ["thailand", "thai", "bangkok", "border", "military", "clash", "troop", "soldier", "dispute", "ថៃ"]

def is_relevant_international(article: Dict) -> Tuple[bool, str]:
    """Strict Radar: Only allows Cambodia-related international news"""
    if article['category'] == 'cambodia':
        return True, "Local News"
    
    full_text = (article['title'] + " " + article['summary']).lower()
    has_cambodia = any(k in full_text for k in INTL_GROUP_A)
    has_context = any(k in full_text for k in INTL_GROUP_B)
    
    if has_cambodia and has_context:
        return True, "✅ Matched Radar (Cambodia + Context)"
    return False, "❌ Irrelevant International News"

SPAM_KEYWORDS = ["ឆ្នោត", "lottery", "casino", "betting", "gamble", "ល្បែង", "sex", "xxx", "porn", "partner", "sponsored", "buy", "sell"]
BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "គ្រោះថ្នាក់", "ផ្ទុះ", "ស្លាប់", "dead", "crisis", "attack", "fire"]

def is_spam(text: str) -> bool:
    if not text: return True
    if any(k in text.lower() for k in SPAM_KEYWORDS): return True
    if len(text) > 0 and (sum(c.isdigit() for c in text) / len(text)) > 0.40: return True
    return False

def calculate_quality_score(article: Dict) -> int:
    score = 50
    if len(article['summary']) > 300: score += 20
    elif len(article['summary']) < 100: score -= 20
    
    prio = next((s['priority'] for cat in NEWS_SOURCES.values() for s in cat if s['name'] == article['source']), 5)
    score += (prio - 5) * 5
    
    if article.get('is_breaking'): score += 20
    if article.get('image_url'): score += 10
    
    return max(0, min(100, score))

# ═══════════════════════════════════════════════════════════════════════════
# 5. FETCHING & PROCESSING
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_rss(url: str):
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx), timeout=timeout) as s:
            async with s.get(url) as r:
                return feedparser.parse(await r.text()) if r.status == 200 else None
    except: return None

def extract_image(entry):
    try:
        if hasattr(entry, 'media_content'): return entry.media_content[0]['url']
        if hasattr(entry, 'media_thumbnail'): return entry.media_thumbnail[0]['url']
        soup = BeautifulSoup(entry.get('summary', '') or entry.get('description', ''), 'html.parser')
        img = soup.find('img')
        if img: return img.get('src')
    except: pass
    return None

async def download_image(url: str):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=10) as r:
                if r.status == 200:
                    data = await r.read()
                    if ENABLE_IMAGE_OPTIMIZATION:
                        img = Image.open(io.BytesIO(data))
                        if img.mode != 'RGB': img = img.convert('RGB')
                        out = io.BytesIO()
                        img.save(out, format='JPEG', quality=85, optimize=True)
                        return out.getvalue()
                    return data
    except: pass
    return None

async def translate_ai(article: Dict, platform: str) -> Dict:
    lang = "Khmer" if platform == "telegram" else "English"
    max_len = 600 if platform == "telegram" else 280
    
    # Context note for AI
    context_note = ""
    if article['category'] == "international":
        context_note = "NOTE: This is International news. Translate objectively as 'Reports state...' or 'Foreign media claims...'."

    prompt = f"""You are a Professional News Editor.
Task: Summarize and Translate for {platform} ({lang}).
{context_note}

Article: {article['title']}
Context: {article['summary'][:2000]}

STRICT RULES:
1. TONE: Formal, Neutral, Journalistic.
2. FOCUS: Facts only (Who, What, Where, When).
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
# 6. POSTING (RESTORING THE ORIGINAL FORMAT)
# ═══════════════════════════════════════════════════════════════════════════

async def post_to_telegram_channel(article: Dict, quality_score: int) -> bool:
    """
    Restored the Enterprise formatting with badges and buttons
    """
    if not telegram_bot: return False
    
    # Determine Header & Emoji
    if article['category'] == "international":
        header = "🌏 **មតិអន្តរជាតិ (Intl Focus)**"
    elif article['is_breaking']:
        header = "🚨 **BREAKING NEWS**"
    else:
        header = "🇰🇭 **ព័ត៌មានជាតិ**"
        
    # Quality Badge (Star)
    badge = "⭐" if quality_score >= 90 else ("✨" if quality_score >= 80 else "")
    
    # Caption Construction
    caption = (
        f"{header}\n\n"
        f"{badge} <b>{article['title_telegram']}</b>\n\n"
        f"{article['body_telegram']}\n\n"
        f"{'─' * 30}\n"
        f"📰 ប្រភព: {article['source']}\n"
        f"🕐 {datetime.now(ICT):%d/%m/%Y • %H:%M} ICT"
    )
    
    # Button Layout (Restored)
    buttons = []
    # Row 1: Source
    buttons.append([InlineKeyboardButton("អានពេញលេញ 📖", url=article["link"])])
    # Row 2: Socials
    social_row = [
        InlineKeyboardButton("Telegram 📢", url=TELEGRAM_LINK),
        InlineKeyboardButton("Twitter ✖️", url=TWITTER_LINK)
    ]
    if WEBSITE_LINK: social_row.append(InlineKeyboardButton("Web 🌐", url=WEBSITE_LINK))
    buttons.append(social_row)
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    try:
        if article.get("image_bytes"):
            await telegram_bot.send_photo(TELEGRAM_CHANNEL_ID, article["image_bytes"], caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            await telegram_bot.send_message(TELEGRAM_CHANNEL_ID, caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return True
    except Exception as e:
        logger.error(f"TG Post Failed: {e}")
        return False

async def post_to_twitter_account(article: Dict, quality_score: int) -> bool:
    if not twitter_client: return False
    
    badge = "⭐" if quality_score >= 90 else ""
    text = f"🇰🇭 {badge} {article['title_twitter']}\n\n{article['body_twitter'][:180]}...\n\n#Cambodia #News\n🔗 {article['link']}"
    
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
# 7. MAIN WORKER & DB
# ═══════════════════════════════════════════════════════════════════════════

async def get_recent_titles():
    if not db: return []
    try:
        cutoff = datetime.now(pytz.utc) - timedelta(hours=24)
        docs = db.collection('posted_articles').where(field_path='updated_at', op_string='>=', value=cutoff).stream()
        return [d.to_dict().get('title', '') for d in docs]
    except: return []

async def check_posted(aid):
    if not db: return False, False
    try:
        doc = await asyncio.to_thread(db.collection('posted_articles').document(aid).get)
        if doc.exists:
            d = doc.to_dict()
            return d.get('telegram_posted', False), d.get('twitter_posted', False)
    except: pass
    return False, False

async def save_posted(aid, article, tg, tw, score):
    if not db: return
    try:
        await asyncio.to_thread(db.collection('posted_articles').document(aid).set, {
            'article_id': aid, 'title': article['title'], 'source': article['source'],
            'quality_score': score, 'telegram_posted': tg, 'twitter_posted': tw,
            'updated_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
    except: pass

async def worker():
    logger.info("="*60)
    logger.info("🚀 News Bot v10.0 (Enterprise Radar) Started")
    logger.info("🎯 Focus: Cambodia + Thai Conflict")
    logger.info("="*60)
    
    while True:
        stats.reset_if_new_day()
        recent_titles = await get_recent_titles()
        
        # Simple time slot logic (Keep it robust)
        h = datetime.now(ICT).hour
        delay = 300 if 0 <= h < 6 else (60 if 6 <= h < 20 else 120)
        
        for category, sources in NEWS_SOURCES.items():
            for src in sources:
                try:
                    feed = await fetch_rss(src['rss'])
                    if not feed or not feed.entries: continue
                    
                    entry = feed.entries[0]
                    stats.articles_processed += 1
                    
                    # 1. DB Check
                    aid = hashlib.md5(f"{entry.title}{entry.link}".encode()).hexdigest()
                    tg_done, tw_done = await check_posted(aid)
                    if tg_done and tw_done: continue
                    
                    # 2. Build Article
                    article = {
                        "title": entry.title, "link": entry.link, "source": src['name'], "category": category,
                        "summary": BeautifulSoup(entry.get('summary', ''), 'html.parser').get_text()[:2000],
                        "image_url": extract_image(entry)
                    }
                    
                    # 3. CORE FILTERS
                    # Radar Check
                    is_relevant, reason = is_relevant_international(article)
                    if not is_relevant:
                        logger.info(f"   ⏭️ SKIPPED Intl: {article['title'][:40]}...")
                        stats.irrelevant_intl_blocked += 1
                        continue
                    
                    # Spam Check
                    if is_spam(article['title']):
                        logger.warning(f"   🗑️ SPAM: {article['title'][:30]}")
                        stats.spam_blocked += 1; continue
                        
                    # Duplicate Check
                    clean_title = re.sub(r'[^\w\s]', '', article['title'].lower())
                    is_dup = False
                    for old in recent_titles:
                        if SequenceMatcher(None, clean_title, re.sub(r'[^\w\s]', '', old.lower())).ratio() > SIMILARITY_THRESHOLD:
                            is_dup = True; break
                    if is_dup:
                        logger.warning(f"   🔍 DUPLICATE: {article['title'][:30]}")
                        stats.duplicates_blocked += 1; continue
                    
                    # Quality Check
                    article['is_breaking'] = any(k in article['title'].lower() for k in BREAKING_KEYWORDS)
                    score = calculate_quality_score(article)
                    if score < CONTENT_QUALITY_THRESHOLD:
                        logger.warning(f"   ⚠️ LOW QUALITY ({score}): {article['title'][:30]}")
                        stats.low_quality_blocked += 1; continue
                    
                    # 4. Processing
                    logger.info(f"✨ PROCESSING: {article['title'][:50]} (Score: {score})")
                    article['image_bytes'] = await download_image(article['image_url']) if article['image_url'] else None
                    
                    # 5. Posting
                    tg_ok = False
                    if ENABLE_TELEGRAM and not tg_done:
                        processed = await translate_ai(article, "telegram")
                        if await post_to_telegram_channel(processed, score):
                            tg_ok = True; recent_titles.append(article['title'])
                            stats.telegram_posts += 1
                    
                    tw_ok = False
                    if ENABLE_TWITTER and not tw_done:
                        if score > 85 or article['is_breaking']:
                            processed_tw = await translate_ai(article, "twitter")
                            if await post_to_twitter_account(processed_tw, score):
                                tw_ok = True; stats.twitter_posts += 1
                    
                    if tg_ok or tw_ok:
                        await save_posted(aid, article, tg_ok, tw_ok, score)
                        await asyncio.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"Err {src['name']}: {e}")
            
            await asyncio.sleep(10)

# Web Server
async def stats_endpoint(request):
    return web.json_response({"status": "healthy", "version": "v10.0 Enterprise", "stats": stats.__dict__}, default=str)

async def main():
    app = web.Application()
    app.router.add_get("/", stats_endpoint)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    await worker()

if __name__ == "__main__":
    asyncio.run(main())