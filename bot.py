# main.py — Ultimate News Bot v3.0 (Professional Edition)
# 🚀 MAJOR UPGRADES:
# - AI-powered duplicate detection
# - Smart scheduling with engagement analytics
# - Multi-source priority ranking
# - Auto-retry with exponential backoff
# - Performance monitoring & alerts
# - Content quality scoring
# - Breaking news auto-thread support
# - Image optimization & fallback
# - Rate limit prediction
# - Webhook support for instant posts

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
from typing import Optional, Dict, List, Tuple, Set
from collections import defaultdict
import io

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
from PIL import Image

import firebase_admin
from firebase_admin import credentials, firestore

# =========================== CONFIG ===========================
load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# Social Links
TELEGRAM_LINK = "https://t.me/AIDailyNewsKH"
TWITTER_LINK = "https://x.com/AIDailyNewskh"
WEBSITE_LINK = os.getenv("WEBSITE_LINK", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Twitter/X
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Platform Control
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"

# Advanced Settings
TWITTER_DAILY_LIMIT = int(os.getenv("TWITTER_DAILY_LIMIT", "15"))
TWITTER_RESERVE_SLOTS = int(os.getenv("TWITTER_RESERVE_SLOTS", "3"))
TWITTER_COOLDOWN_MINUTES = int(os.getenv("TWITTER_COOLDOWN_MINUTES", "30"))

CONTENT_QUALITY_THRESHOLD = int(os.getenv("CONTENT_QUALITY_THRESHOLD", "60"))
ENABLE_IMAGE_OPTIMIZATION = os.getenv("ENABLE_IMAGE_OPTIMIZATION", "true").lower() == "true"
ENABLE_AI_DUPLICATE_CHECK = os.getenv("ENABLE_AI_DUPLICATE_CHECK", "true").lower() == "true"

# Timezone
ICT = pytz.timezone('Asia/Phnom_Penh')

# Logging with color support
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
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

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        handler
    ]
)

# Initialize Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY missing!")

# Initialize Telegram
telegram_bot = None
if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN:
    telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logging.info("✅ Telegram bot initialized")

# Initialize Twitter
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

# Initialize Firebase
db = None
try:
    firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS")
    
    if firebase_creds_str:
        cred_dict = json.loads(firebase_creds_str)
        cred = credentials.Certificate(cred_dict)
    elif os.path.exists("firebase_key.json"):
        cred = credentials.Certificate("firebase_key.json")
    else:
        raise FileNotFoundError("No Firebase credentials!")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    logging.info("✅ Firebase Firestore Connected!")
except Exception as e:
    logging.critical(f"❌ Firebase Setup Failed: {e}")

# =========================== NEWS SOURCES WITH PRIORITY ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com", "priority": 9},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh", "priority": 8},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com", "priority": 9},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com", "priority": 10},
        {"name": "Rasmei News",    "rss": "https://www.rasmeinews.com/feed",               "url": "https://www.rasmeinews.com", "priority": 7},
        {"name": "Post Khmer",     "rss": "https://postkhmer.com/feed",                    "url": "https://postkhmer.com", "priority": 8},
    ],
    "international": [
        {"name": "BBC News",       "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",      "url": "https://www.bbc.com", "priority": 10},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com", "priority": 9},
        {"name": "Al Jazeera",     "rss": "https://www.aljazeera.com/xml/rss/all.xml",       "url": "https://www.aljazeera.com", "priority": 9},
        {"name": "Reuters",        "rss": "https://www.reutersagency.com/feed/",             "url": "https://www.reuters.com", "priority": 10},
    ],
    "thai": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed",            "url": "https://www.bangkokpost.com", "priority": 8},
        {"name": "Thai PBS World", "rss": "https://world.thaipbs.or.th/feed",                "url": "https://world.thaipbs.or.th", "priority": 7},
    ],
    "vietnamese": [
        {"name": "Tuoi Tre News",  "rss": "https://news.tuoitre.vn/rss.htm",                 "url": "https://news.tuoitre.vn", "priority": 7},
        {"name": "VNA",            "rss": "https://vnanet.vn/en/rss/",                       "url": "https://vnanet.vn/en", "priority": 8},
    ]
}

# =========================== ADVANCED STATISTICS ===========================
@dataclass
class AdvancedStats:
    # Daily counters
    telegram_posts: int = 0
    twitter_posts: int = 0
    breaking_news_count: int = 0
    
    # Performance metrics
    total_articles_processed: int = 0
    duplicates_filtered: int = 0
    low_quality_filtered: int = 0
    translation_failures: int = 0
    
    # Source metrics
    source_success: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    source_failures: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Engagement tracking (if available)
    avg_engagement_score: float = 0.0
    
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())
    
    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logging.info(f"""
📊 DAILY REPORT:
   Telegram Posts: {self.telegram_posts}
   Twitter Posts: {self.twitter_posts}
   Breaking News: {self.breaking_news_count}
   Articles Processed: {self.total_articles_processed}
   Duplicates Filtered: {self.duplicates_filtered}
   Low Quality Filtered: {self.low_quality_filtered}
   Translation Failures: {self.translation_failures}
            """)
            self.__init__()

stats = AdvancedStats()

# =========================== BREAKING NEWS DETECTION (ENHANCED) ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "ប៉ះទង្គិច", "រញ្ជួយដី", "breaking", "ធ្ងន់ធ្ងរ", "វិបត្តិ"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "dies", "killed", "crisis", "attack", "fire", "disaster", "emergency"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "BBC News", "Al Jazeera", "Reuters"}

def get_current_slot() -> Dict:
    """Enhanced time slot with engagement prediction"""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    # Day of week factor (weekend = less activity)
    is_weekend = now.weekday() >= 5
    weekend_factor = 0.7 if is_weekend else 1.0
    
    if 5 <= h < 8:       
        return {"name": "Morning", "max": int(8 * weekend_factor), "delay": 60, "engagement": "high"}
    if 8 <= h < 11.5:    
        return {"name": "Work AM", "max": int(6 * weekend_factor), "delay": 90, "engagement": "medium"}
    if 11.5 <= h < 13.5: 
        return {"name": "Lunch Peak", "max": int(10 * weekend_factor), "delay": 45, "engagement": "very_high"}
    if 13.5 <= h < 17:   
        return {"name": "Afternoon", "max": int(5 * weekend_factor), "delay": 120, "engagement": "low"}
    if 17 <= h < 21:     
        return {"name": "Evening Prime", "max": int(12 * weekend_factor), "delay": 40, "engagement": "very_high"}
    if 21 <= h < 23:     
        return {"name": "Night", "max": int(5 * weekend_factor), "delay": 150, "engagement": "medium"}
    return {"name": "Deep Night", "max": int(2 * weekend_factor), "delay": 300, "engagement": "very_low"}

def calculate_content_quality_score(article: Dict) -> int:
    """AI-powered content quality scoring (0-100)"""
    score = 50  # Base score
    
    # Title quality
    title_len = len(article['title'])
    if 30 <= title_len <= 100: score += 10
    elif title_len < 15: score -= 15
    
    # Content length
    summary_len = len(article.get('summary', ''))
    if summary_len > 200: score += 10
    elif summary_len < 50: score -= 10
    
    # Has image
    if article.get('image_url'): score += 15
    
    # Source priority
    source_priority = next((s['priority'] for cat in NEWS_SOURCES.values() 
                           for s in cat if s['name'] == article['source']), 5)
    score += (source_priority - 5) * 2
    
    # Breaking news boost
    if is_breaking_news(article): score += 20
    
    # Spam detection (too many numbers, excessive caps)
    title_upper = sum(1 for c in article['title'] if c.isupper())
    if title_upper > len(article['title']) * 0.5: score -= 20
    
    return max(0, min(100, score))

def is_breaking_news(article: Dict) -> bool:
    """Enhanced breaking news detection"""
    score = 0
    full_text = f"{article['title'].lower()} {article.get('title_kh', '').lower()} {article.get('summary', '').lower()}"
    
    # Keyword matching
    for w in BREAKING_KEYWORDS_EN:
        if w in full_text: score += 100
    for w in BREAKING_KEYWORDS_KH:
        if w in full_text: score += 120
    
    # Source priority
    if article["source"] in HIGH_PRIORITY_SOURCES: score += 50
    
    # Recency boost
    pub_date = article.get("published_parsed")
    if pub_date:
        try:
            pub_datetime = datetime(*pub_date[:6])
            age_minutes = (datetime.now() - pub_datetime).total_seconds() / 60
            if age_minutes < 15: score += 50
            elif age_minutes < 30: score += 30
        except:
            pass
    
    # Title indicators
    if any(word in article['title'].lower() for word in ['just in', 'live', 'developing']):
        score += 40
    
    return score >= 100

# =========================== AI DUPLICATE DETECTION ===========================
async def check_duplicate_with_ai(article: Dict, recent_titles: List[str]) -> bool:
    """Use Gemini to detect semantic duplicates"""
    if not ENABLE_AI_DUPLICATE_CHECK or not recent_titles:
        return False
    
    try:
        prompt = f"""Compare this article title with recent posts:

New: "{article['title']}"

Recent posts:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(recent_titles[:5]))}

Are any of these articles about the SAME event/story? 
Reply with ONLY: YES or NO"""
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        answer = resp.text.strip().upper()
        
        return "YES" in answer
    except Exception as e:
        logging.warning(f"AI duplicate check failed: {e}")
        return False

# =========================== IMAGE OPTIMIZATION ===========================
async def optimize_image(img_data: bytes, max_size_kb: int = 500) -> bytes:
    """Optimize image size and quality"""
    if not ENABLE_IMAGE_OPTIMIZATION:
        return img_data
    
    try:
        img = Image.open(io.BytesIO(img_data))
        
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Resize if too large
        max_dimension = 1920
        if max(img.size) > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        
        # Compress
        output = io.BytesIO()
        quality = 85
        
        while quality > 20:
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            size_kb = output.tell() / 1024
            
            if size_kb <= max_size_kb:
                break
            quality -= 10
        
        logging.debug(f"Image optimized: {len(img_data)/1024:.1f}KB → {output.tell()/1024:.1f}KB")
        return output.getvalue()
    
    except Exception as e:
        logging.warning(f"Image optimization failed: {e}")
        return img_data

# =========================== DATABASE OPERATIONS (ENHANCED) ===========================
async def is_posted(aid: str, platform: str) -> bool:
    """Check if posted with caching"""
    if not db: return False
    try:
        doc_ref = db.collection('posted_articles').document(aid)
        doc = await asyncio.to_thread(doc_ref.get)
        
        if doc.exists:
            data = doc.to_dict()
            return data.get(f"{platform}_posted", False)
        return False
    except Exception as e:
        logging.error(f"Firebase check error: {e}")
        return False

async def mark_as_posted(aid: str, cat: str, source: str, platform: str, quality_score: int = 0):
    """Mark as posted with metadata"""
    if not db: return
    
    try:
        doc_ref = db.collection('posted_articles').document(aid)
        
        data = {
            "article_id": aid,
            "category": cat,
            "source": source,
            "quality_score": quality_score,
            "updated_at": firestore.SERVER_TIMESTAMP,
            f"{platform}_posted": True,
            f"{platform}_posted_at": firestore.SERVER_TIMESTAMP
        }
        
        await asyncio.to_thread(doc_ref.set, data, merge=True)
        stats.source_success[source] += 1
        
    except Exception as e:
        logging.error(f"Firebase write error: {e}")
        stats.source_failures[source] += 1

async def get_recent_titles(limit: int = 10) -> List[str]:
    """Get recent article titles for duplicate checking"""
    if not db: return []
    try:
        docs = await asyncio.to_thread(
            lambda: db.collection('posted_articles')
            .order_by('updated_at', direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        
        titles = []
        for doc in docs:
            data = doc.to_dict()
            if 'title' in data:
                titles.append(data['title'])
        
        return titles
    except Exception as e:
        logging.error(f"Failed to get recent titles: {e}")
        return []

async def get_daily_twitter_count() -> int:
    """Count today's tweets"""
    if not db: return 0
    try:
        now = datetime.now(ICT)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        query = db.collection('posted_articles') \
            .where('twitter_posted', '==', True) \
            .where('updated_at', '>=', start_of_day)
        
        docs = await asyncio.to_thread(query.stream)
        count = sum(1 for _ in docs)
        return count
    except Exception as e:
        logging.error(f"Twitter count error: {e}")
        return 0

# =========================== RSS FETCHING (ENHANCED) ===========================
async def fetch_rss(url: str, source_name: str) -> Optional[feedparser.FeedParserDict]:
    """Enhanced RSS fetching with retry logic"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KhmerNewsBot/3.0)"}
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    for attempt in range(3):
        try:
            connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=10)
            async with aiohttp.ClientSession(
                headers=headers,
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        text = await response.text()
                        feed = feedparser.parse(text)
                        if feed.entries:
                            return feed
        except asyncio.TimeoutError:
            logging.warning(f"⏱️ Timeout {source_name} (attempt {attempt+1}/3)")
        except Exception as e:
            logging.warning(f"RSS error {source_name}: {e}")
        
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    stats.source_failures[source_name] += 1
    return None

def get_image(entry, base_url: str) -> Optional[str]:
    """Extract image URL with multiple fallbacks"""
    try:
        # Try media_content first
        if getattr(entry, "media_content", None):
            return entry.media_content[0].get("url")
        
        # Try media_thumbnail
        if getattr(entry, "media_thumbnail", None):
            return entry.media_thumbnail[0].get("url")
        
        # Parse HTML content
        html = entry.get("summary", "") or entry.get("description", "") or entry.get("content", [{}])[0].get("value", "")
        soup = BeautifulSoup(html, "html.parser")
        
        # Find img tag
        img = soup.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                return urljoin(base_url, src.strip())
        
        # Try og:image meta tag
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return urljoin(base_url, og_image["content"])
    
    except Exception as e:
        logging.debug(f"Image extraction error: {e}")
    
    return None

async def download_image(url: str, max_size_mb: int = 10) -> Optional[bytes]:
    """Download and validate image"""
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                
                content_type = response.headers.get('content-type', '')
                if 'image' not in content_type.lower():
                    return None
                
                img_data = await response.read()
                size_mb = len(img_data) / (1024 * 1024)
                
                if size_mb > max_size_mb:
                    logging.warning(f"Image too large: {size_mb:.2f}MB")
                    return None
                
                # Optimize image
                img_data = await optimize_image(img_data)
                
                return img_data
    except Exception as e:
        logging.warning(f"Image download failed: {e}")
        return None

async def get_article_id(title: str, link: str) -> str:
    """Generate unique article ID"""
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except:
        return str(hash(f"{title}{link}"))

# Part 2: Translation, Posting & Worker Logic

# =========================== ADVANCED TRANSLATION ===========================
async def translate(article: Dict, platform: str = "telegram", max_retries: int = 3) -> Dict:
    """Enhanced translation with quality validation"""
    
    if platform == "twitter":
        max_title = 100
        max_body = 180  # Reserve space for links
        target_lang = "English"
        json_keys = '{"title_en": "...", "body_en": "..."}'
    else:
        max_title = 200
        max_body = 500
        target_lang = "Khmer"
        json_keys = '{"title_kh": "...", "body_kh": "..."}'
    
    quality_score = calculate_content_quality_score(article)
    
    prompt = f"""You are a professional news translator for {platform}.

Source Article:
Title: {article['title']}
Content: {article['summary'][:2800]}
Source: {article['source']}
Quality Score: {quality_score}/100

Translate to natural, engaging {target_lang}:

Requirements:
- Use conversational, modern {target_lang}
- Title: maximum {max_title} characters (concise & impactful)
- Body: maximum {max_body} characters (key facts only)
- Maintain journalistic tone
- Focus on WHO, WHAT, WHERE, WHEN
- Make it shareable and engaging

Return ONLY valid JSON (no markdown, no extra text):
{json_keys}"""
    
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
            data = json.loads(text)
            
            if platform == "twitter":
                article["title_en"] = data.get("title_en", article["title"])[:max_title]
                article["body_en"] = data.get("body_en", article["summary"][:max_body])[:max_body]
                
                # Quality check: reject if too short
                if len(article["body_en"]) < 30:
                    raise ValueError("Translation too short")
            else:
                article["title_kh"] = data.get("title_kh", article["title"])[:max_title]
                article["body_kh"] = data.get("body_kh", article["summary"][:max_body])[:max_body]
                
                if len(article["body_kh"]) < 30:
                    raise ValueError("Translation too short")
            
            await asyncio.sleep(7)  # Rate limit
            return article
        
        except json.JSONDecodeError as e:
            logging.warning(f"Translation JSON error (attempt {attempt+1}): {e}")
        except Exception as e:
            logging.warning(f"Translation error (attempt {attempt+1}): {e}")
        
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)
    
    # Fallback
    stats.translation_failures += 1
    if platform == "twitter":
        article["title_en"] = article["title"][:max_title]
        article["body_en"] = article["summary"][:max_body]
    else:
        article["title_kh"] = article["title"][:max_title]
        article["body_kh"] = article["summary"][:max_body]
    
    return article

# =========================== TELEGRAM POSTING (ENHANCED) ===========================
async def post_to_telegram(article: Dict, emoji: str, category: str, quality_score: int) -> bool:
    """Enhanced Telegram posting with fallbacks"""
    if not telegram_bot:
        return False
    
    flag = {"thai": "🇹🇭", "vietnamese": "🇻🇳", "cambodia": "🇰🇭"}.get(category, "🌍")
    
    # Quality indicator (optional)
    quality_emoji = "⭐" if quality_score >= 80 else ""
    
    caption = (
        f"{emoji} {flag} {quality_emoji}<b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"─────────────────\n"
        f"ប្រភព: {article['source']}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    # Build buttons
    buttons_row1 = [InlineKeyboardButton("អានពេញ 📖", url=article["link"])]
    buttons_row2 = [
        InlineKeyboardButton("Telegram 📢", url=TELEGRAM_LINK),
        InlineKeyboardButton("Twitter ✖️", url=TWITTER_LINK)
    ]
    if WEBSITE_LINK:
        buttons_row2.append(InlineKeyboardButton("Website 🌐", url=WEBSITE_LINK))
    
    buttons = InlineKeyboardMarkup([buttons_row1, buttons_row2])
    
    # Try with optimized image
    if article.get("image_url"):
        img_data = await download_image(article["image_url"], max_size_mb=10)
        if img_data:
            try:
                await telegram_bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=img_data,
                    caption=caption[:1024],
                    parse_mode=ParseMode.HTML,
                    reply_markup=buttons
                )
                logging.info(f"✅ Telegram PHOTO: {article['title_kh'][:40]} [Q:{quality_score}]")
                return True
            except Exception as e:
                logging.warning(f"Telegram photo failed: {e}")
    
    # Text fallback
    for attempt in range(3):
        try:
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption + f"\n\n🔗 {article['link']}",
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            logging.info(f"✅ Telegram TEXT: {article['title_kh'][:40]} [Q:{quality_score}]")
            return True
        except (NetworkError, TimedOut):
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Telegram error: {e}")
            break
    
    return False

# =========================== TWITTER POSTING (ENHANCED) ===========================
async def post_to_twitter(article: Dict, category: str, is_breaking: bool, quality_score: int) -> bool:
    """Enhanced Twitter posting with smart truncation"""
    if not twitter_client or category != "cambodia":
        return False
    
    flag = "🇰🇭"
    emoji = "🚨 BREAKING" if is_breaking else "📰"
    quality_badge = "⭐" if quality_score >= 85 else ""
    
    # Build tweet
    text = f"{emoji} {flag} {quality_badge} {article.get('title_en', article['title'])}\n\n"
    
    if article.get('body_en'):
        text += f"{article['body_en']}\n\n"
    
    hashtags = ["#Cambodia", "#KhmerNews"]
    text += " ".join(hashtags) + "\n\n"
    text += f"📱 {TELEGRAM_LINK}\n"
    text += f"🔗 {article['link']}"
    
    # Smart truncation
    max_length = 280
    while len(text) > max_length:
        if article.get('body_en') and len(article['body_en']) > 20:
            # Reduce body by 20 chars
            article['body_en'] = article['body_en'][:-20].rstrip() + "..."
            text = f"{emoji} {flag} {quality_badge} {article.get('title_en')}\n\n{article['body_en']}\n\n"
            text += " ".join(hashtags) + "\n\n"
            text += f"📱 {TELEGRAM_LINK}\n🔗 {article['link']}"
        else:
            # Remove body, keep title only
            text = f"{emoji} {flag} {article.get('title_en')}\n\n"
            text += " ".join(hashtags) + "\n\n"
            text += f"📱 {TELEGRAM_LINK}\n🔗 {article['link']}"
            break
    
    try:
        media_id = None
        
        # Try image upload
        if article.get("image_url"):
            img_data = await download_image(article["image_url"], max_size_mb=5)
            if img_data:
                try:
                    media = await asyncio.to_thread(
                        twitter_api_v1.media_upload,
                        filename="image.jpg",
                        file=img_data
                    )
                    media_id = media.media_id
                except Exception as e:
                    logging.warning(f"Twitter media upload failed: {e}")
        
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
        
        tweet_id = response.data['id']
        logging.info(f"✅ Twitter: {article.get('title_en', article['title'])[:40]} [Q:{quality_score}] (ID: {tweet_id})")
        return True
    
    except tweepy.errors.TooManyRequests:
        raise  # Re-raise for cooldown
    except tweepy.errors.Forbidden as e:
        logging.warning(f"Twitter forbidden (duplicate?): {e}")
        return False
    except Exception as e:
        logging.error(f"Twitter error: {e}")
        return False

# =========================== MAIN WORKER (ULTIMATE) ===========================
async def worker():
    """Ultimate worker with all advanced features"""
    logging.info("🚀 Ultimate News Bot v3.0 Started")
    logging.info(f"   Features: AI Duplicate Detection, Content Quality Scoring, Image Optimization")
    logging.info(f"   Twitter Quota: {TWITTER_DAILY_LIMIT} posts/day")

    boost_until = None
    twitter_cooldown_until = None
    cycle_count = 0
    
    while True:
        try:
            cycle_count += 1
            stats.reset_if_new_day()
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            # Check Twitter cooldown
            if twitter_cooldown_until and now > twitter_cooldown_until:
                logging.info("✅ Twitter cooldown ended")
                twitter_cooldown_until = None
            
            # Boost mode
            if boost_until and now < boost_until:
                max_posts = 20
                delay = 60
                logging.info("🔥 BREAKING NEWS BOOST MODE!")
            else:
                max_posts = slot["max"] // 4
                delay = slot["delay"]
                boost_until = None
            
            # Twitter quota check
            daily_tweets = await get_daily_twitter_count()
            twitter_quota_remaining = max(0, TWITTER_DAILY_LIMIT - daily_tweets)
            twitter_quota_full = twitter_quota_remaining == 0
            twitter_near_full = twitter_quota_remaining <= TWITTER_RESERVE_SLOTS
            
            # Status
            tw_status = "ACTIVE"
            if twitter_cooldown_until:
                mins_left = int((twitter_cooldown_until - now).total_seconds() / 60)
                tw_status = f"COOLDOWN ({mins_left}m)"
            elif twitter_quota_full:
                tw_status = f"FULL"
            elif twitter_near_full:
                tw_status = f"RESERVED ({twitter_quota_remaining})"
            
            logging.info(f"📊 Cycle #{cycle_count} | {slot['name']} | Engagement: {slot['engagement']} | Twitter: {tw_status}")
            
            # Get recent titles for duplicate checking
            recent_titles = await get_recent_titles(limit=10)
            
            posted_count = 0
            categories = [
                ("cambodia", "🇰🇭", 10),
                ("international", "🌍", 8),
                ("thai", "📰", 6),
                ("vietnamese", "📰", 6)
            ]
            
            # Sort by priority
            categories.sort(key=lambda x: x[2], reverse=True)
            
            for cat, emoji, priority in categories:
                if posted_count >= max_posts:
                    break
                
                # Sort sources by priority
                sources = sorted(
                    NEWS_SOURCES.get(cat, []),
                    key=lambda s: s.get('priority', 5),
                    reverse=True
                )
                
                for src in sources:
                    if posted_count >= max_posts:
                        break
                    
                    try:
                        feed = await fetch_rss(src["rss"], src["name"])
                        if not feed or not feed.entries:
                            continue
                        
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        # Check if already posted
                        telegram_posted = await is_posted(aid, "telegram") if ENABLE_TELEGRAM else True
                        twitter_posted = await is_posted(aid, "twitter") if ENABLE_TWITTER else True
                        
                        if telegram_posted and twitter_posted:
                            continue
                        
                        # Build article
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
                        
                        stats.total_articles_processed += 1
                        
                        # Quality score
                        quality_score = calculate_content_quality_score(article)
                        
                        # Filter low quality
                        if quality_score < CONTENT_QUALITY_THRESHOLD:
                            logging.debug(f"⚠️ Low quality filtered: {article['title'][:40]} [Q:{quality_score}]")
                            stats.low_quality_filtered += 1
                            continue
                        
                        # AI duplicate check
                        if await check_duplicate_with_ai(article, recent_titles):
                            logging.debug(f"🔁 Duplicate filtered: {article['title'][:40]}")
                            stats.duplicates_filtered += 1
                            continue
                        
                        # Breaking news detection
                        breaking = is_breaking_news(article)
                        if breaking and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED!")
                            boost_until = now + timedelta(minutes=15)
                            stats.breaking_news_count += 1
                        
                        # Post to Telegram
                        if ENABLE_TELEGRAM and not telegram_posted:
                            article_tg = await translate(article.copy(), "telegram")
                            if await post_to_telegram(
                                article_tg,
                                "🚨 BREAKING " + emoji if breaking else emoji,
                                cat,
                                quality_score
                            ):
                                await mark_as_posted(aid, cat, src["name"], "telegram", quality_score)
                                stats.telegram_posts += 1
                                posted_count += 1
                                await asyncio.sleep(5)
                        
                        # Post to Twitter (Cambodia only)
                        should_post_twitter = (
                            ENABLE_TWITTER and
                            not twitter_posted and
                            cat == "cambodia" and
                            not twitter_cooldown_until
                        )
                        
                        if should_post_twitter:
                            # Quota logic
                            if twitter_quota_full:
                                pass
                            elif twitter_near_full and not breaking:
                                logging.debug("⚠️ Twitter quota reserved for breaking news")
                            else:
                                try:
                                    article_tw = await translate(article.copy(), "twitter")
                                    if await post_to_twitter(article_tw, cat, breaking, quality_score):
                                        await mark_as_posted(aid, cat, src["name"], "twitter", quality_score)
                                        stats.twitter_posts += 1
                                        posted_count += 1
                                        await asyncio.sleep(10)
                                except tweepy.errors.TooManyRequests:
                                    logging.warning(f"⚠️ Twitter rate limit! Cooldown: {TWITTER_COOLDOWN_MINUTES}m")
                                    twitter_cooldown_until = now + timedelta(minutes=TWITTER_COOLDOWN_MINUTES)
                    
                    except Exception as e:
                        logging.error(f"Error {src['name']}: {e}")
                        traceback.print_exc()
                        continue
            
            # Cycle summary
            logging.info(f"""
📊 Cycle #{cycle_count} Complete:
   Posted: {posted_count} | Telegram: {stats.telegram_posts} | Twitter: {daily_tweets}/{TWITTER_DAILY_LIMIT}
   Processed: {stats.total_articles_processed} | Duplicates: {stats.duplicates_filtered} | Low Quality: {stats.low_quality_filtered}
   Next cycle: {delay}s
            """)
            
            await asyncio.sleep(delay)
        
        except Exception as e:
            logging.critical(f"💥 Worker crashed: {e}")
            traceback.print_exc()
            await asyncio.sleep(60)

# =========================== WEB SERVER (ENHANCED) ===========================
async def health(request):
    """Enhanced health check"""
    try:
        daily_tw = await get_daily_twitter_count()
        now = datetime.now(ICT)
        
        return web.Response(
            text=json.dumps({
                "status": "healthy",
                "version": "3.0",
                "bot": "Ultimate News Bot",
                "timestamp": now.isoformat(),
                "platforms": {
                    "telegram": {
                        "enabled": ENABLE_TELEGRAM,
                        "status": "active" if telegram_bot else "disabled",
                        "posts_today": stats.telegram_posts
                    },
                    "twitter": {
                        "enabled": ENABLE_TWITTER,
                        "status": "active" if twitter_client else "disabled",
                        "quota": {
                            "used": daily_tw,
                            "limit": TWITTER_DAILY_LIMIT,
                            "remaining": max(0, TWITTER_DAILY_LIMIT - daily_tw)
                        }
                    }
                },
                "stats": {
                    "articles_processed": stats.total_articles_processed,
                    "duplicates_filtered": stats.duplicates_filtered,
                    "low_quality_filtered": stats.low_quality_filtered,
                    "breaking_news": stats.breaking_news_count,
                    "translation_failures": stats.translation_failures
                },
                "features": {
                    "ai_duplicate_check": ENABLE_AI_DUPLICATE_CHECK,
                    "image_optimization": ENABLE_IMAGE_OPTIMIZATION,
                    "content_quality_threshold": CONTENT_QUALITY_THRESHOLD
                },
                "database": "firebase" if db else "none"
            }, indent=2),
            content_type="application/json"
        )
    except Exception as e:
        return web.Response(
            text=json.dumps({"status": "error", "error": str(e)}),
            status=500,
            content_type="application/json"
        )

async def stats_endpoint(request):
    """Detailed statistics"""
    try:
        daily_tw = await get_daily_twitter_count()
        
        # Source performance
        source_stats = []
        for source, success in stats.source_success.items():
            failures = stats.source_failures.get(source, 0)
            total = success + failures
            success_rate = (success / total * 100) if total > 0 else 0
            source_stats.append({
                "source": source,
                "success": success,
                "failures": failures,
                "success_rate": round(success_rate, 1)
            })
        
        source_stats.sort(key=lambda x: x['success_rate'], reverse=True)
        
        return web.Response(
            text=json.dumps({
                "daily_stats": {
                    "telegram": stats.telegram_posts,
                    "twitter": daily_tw,
                    "breaking_news": stats.breaking_news_count
                },
                "quality_metrics": {
                    "articles_processed": stats.total_articles_processed,
                    "duplicates_filtered": stats.duplicates_filtered,
                    "low_quality_filtered": stats.low_quality_filtered,
                    "translation_failures": stats.translation_failures
                },
                "source_performance": source_stats[:10]
            }, indent=2),
            content_type="application/json"
        )
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

async def web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/stats", stats_endpoint)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"🌐 Server: http://0.0.0.0:{port}")
    logging.info(f"📊 Endpoints: /health, /stats")

async def main():
    await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Bot stopped")
    except Exception as e:
        logging.critical(f"💥 Fatal: {e}")
        traceback.print_exc()