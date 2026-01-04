# -*- coding: utf-8 -*-
# bot_facebook_only.py — Production Ready Version (Facebook Only)
# Version: 13.0 - Telegram removed, Facebook only
# Last Updated: 2025-12-20

import os
import asyncio
import json
import hashlib
import logging
import html
import io
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import urljoin
from typing import Dict, List, Optional, Tuple, Set, Any, Callable
from dataclasses import dataclass

# Third-party imports
try:
    import pytz
    from dotenv import load_dotenv
    import aiohttp
    import feedparser
    from bs4 import BeautifulSoup
    from groq import Groq
    import google.generativeai as genai
    from aiohttp import web, FormData
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    
    import firebase_admin
    from firebase_admin import credentials, firestore
    from google.cloud.firestore import FieldFilter
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("💉 Please run: pip install -r requirements.txt")
    exit(1)

# =========================== ⚙️ CONFIGURATION ===========================
load_dotenv()

# --- Credentials ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GEMINI_API_KEYS_RAW = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS_RAW.split(",") if k.strip()]
current_gemini_key_index = 0
failed_gemini_keys = set()



FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "firebase_key.json")
FB_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")

# --- Admin Settings ---

DAILY_REPORT_TIME = "22:00"  # 10 PM ICT

# --- Settings ---
# --- Settings ---
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash" # Or gemini-1.5-flash
PRIMARY_API = "groq"
FALLBACK_API = "gemini"
ICT = pytz.timezone('Asia/Phnom_Penh')
FONT_PATH = os.getenv("FONT_PATH", "Battambang-Bold.ttf")

# Global Event for Manual Trigger
scan_event = asyncio.Event()

# --- Cache Settings ---
CACHE_DIR = "image_cache"
CACHE_MAX_SIZE_MB = 100
CACHE_EXPIRY_HOURS = 24

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# =========================== 🛡️ SYSTEM CHECKS ===========================
# Check Font
if not os.path.exists(FONT_PATH):
    logging.warning(f"⚠️ WARNING: '{FONT_PATH}' not found! Will use default font.")
    logging.warning(f"💉 For better Khmer support, upload '{FONT_PATH}' to project root.")

# Check Keys
if not all([GROQ_API_KEY, GEMINI_API_KEYS, FB_ACCESS_TOKEN, FB_PAGE_ID, FIREBASE_CRED_PATH]):
    logging.error("❌ Missing required environment variables:")
    if not GROQ_API_KEY:
        logging.error("  - GROQ_API_KEY")
    if not GEMINI_API_KEYS:
        logging.error("  - GEMINI_API_KEY")
    if not FB_ACCESS_TOKEN:
        logging.error("  - FACEBOOK_ACCESS_TOKEN")
    if not FB_PAGE_ID:
        logging.error("  - FACEBOOK_PAGE_ID")
    if not FIREBASE_CRED_PATH:
        logging.error("  - FIREBASE_CRED_PATH")
    exit(1)

logging.info(f"✅ Loaded Groq API key")
logging.info(f"✅ Loaded {len(GEMINI_API_KEYS)} Gemini API key(s)")
logging.info(f"✅ Facebook Page ID: {FB_PAGE_ID}")

# =========================== 🔥 INITIALIZATION ===========================
try:
    if not firebase_admin._apps:
        # Try environment variable first (for Render/Cloud deployment)
        firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS")
        if firebase_creds_json:
            cred_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(cred_dict)
            logging.info("✅ Using Firebase credentials from environment variable")
        else:
            # Fallback to file (for local development)
            cred = credentials.Certificate(FIREBASE_CRED_PATH)
            logging.info("✅ Using Firebase credentials from file")
        
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase Connected")
except Exception as e:
    logging.critical(f"❌ Firebase Error: {e}")
    exit(1)

# Configure Groq
client = Groq(api_key=GROQ_API_KEY)

# Configure Gemini
if GEMINI_API_KEYS:
    genai.configure(api_key=GEMINI_API_KEYS[current_gemini_key_index])

# Create cache directory
os.makedirs(CACHE_DIR, exist_ok=True)

# =========================== 🔧 ERROR HANDLING UTILITIES ===========================
from functools import wraps
from collections import defaultdict
import time

# --- Retry Decorator ---
def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """Retry decorator with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = min(delay * (2 ** attempt), max_delay)
                        logging.warning(f"⚠️ {func.__name__} failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logging.error(f"❌ {func.__name__} failed after {max_retries} attempts: {str(e)[:150]}")
            
            raise last_exception
        return wrapper
    return decorator

# --- Circuit Breaker ---
class CircuitBreaker:
    """Prevent cascade failures."""
    def __init__(self, failure_threshold: int = 5, timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = defaultdict(int)
        self.last_failure_time = defaultdict(float)
        self.opened = defaultdict(bool)
    
    def call(self, key: str) -> bool:
        if self.opened[key]:
            if time.time() - self.last_failure_time[key] > self.timeout:
                logging.info(f"🔧 Circuit breaker for '{key}' auto-recovering...")
                self.reset(key)
                return True
            return False
        return True
    
    def record_success(self, key: str):
        if self.failures[key] > 0:
            self.failures[key] = max(0, self.failures[key] - 1)
    
    def record_failure(self, key: str):
        self.failures[key] += 1
        self.last_failure_time[key] = time.time()
        
        if self.failures[key] >= self.failure_threshold:
            self.opened[key] = True
            logging.error(f"⚠️ Circuit breaker OPENED for '{key}' after {self.failures[key]} failures.")
    
    def reset(self, key: str):
        self.failures[key] = 0
        self.opened[key] = False

circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=300)

# --- URL Validation ---
def validate_url(url: Optional[str]) -> bool:
    if not url or not isinstance(url, str):
        return False
    return url.startswith(('http://', 'https://'))

# --- Safe JSON Parser ---
def safe_json_parse(text: str) -> Optional[dict]:
    """Parse JSON with fallback strategies."""
    if not text:
        return None
    
    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Remove markdown
    try:
        cleaned = re.sub(r'```(?:json)?\s*|\s*```', '', text).strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Extract JSON object
    try:
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except (json.JSONDecodeError, AttributeError):
        pass
    
    logging.error(f"❌ Failed to parse JSON from: {text[:200]}...")
    return None

# =========================== 📋 DATA MODELS ===========================
@dataclass
class FailedPost:
    article_id: str
    article_data: Dict[str, Any]
    image_bytes: Optional[bytes]
    attempts: int
    last_attempt: datetime
    error_message: str

# =========================== 🔍 DEDUPLICATION ===========================
def calculate_text_similarity(text1: str, text2: str) -> float:
    """Jaccard similarity."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union) if union else 0.0

def create_article_fingerprint(title: str, summary: str) -> str:
    """Content-based fingerprint."""
    normalized = f"{title.lower().strip()} {summary.lower().strip()[:200]}"
    return hashlib.md5(normalized.encode()).hexdigest()

def is_priority_news(article_data: dict) -> bool:
    """Detect Cambodia-Thai conflict news."""
    priority_keywords = {
        'conflict': ['war', 'conflict', 'fighting', 'attack', 'bomb', 'rocket', 'shell', 
                    'military', 'troops', 'casualties', 'death', 'killed', 'wounded'],
        'locations': ['cambodia', 'thailand', 'thai', 'khmer', 'cambodian']
    }
    
    text = f"{article_data.get('title', '')} {article_data.get('summary', '')}".lower()
    
    has_cambodia = 'cambodia' in text or 'cambodian' in text or 'khmer' in text
    has_thailand = 'thailand' in text or 'thai' in text
    has_conflict = any(kw in text for kw in priority_keywords['conflict'])
    
    is_priority = has_cambodia and has_thailand and has_conflict
    
    if is_priority:
        logging.info(f"🚨 PRIORITY NEWS: Cambodia-Thai conflict detected")
    
    return is_priority

def is_relevant_content(article_data: dict, category: str) -> bool:
    """Filter content based on category relevance to Cambodian audience."""
    text = f"{article_data.get('title', '')} {article_data.get('summary', '')}".lower()
    
    # Thailand/Cambodia/Global-Politics: strict geography check
    if category in ['global', 'cambodia', 'thailand']:
        cambodia_keywords = [
            'cambodia', 'cambodian', 'khmer', 'phnom penh', 'siem reap', 
            'hun sen', 'hun manet', 'asean', 'southeast asia',
            'china', 'usa', 'united states', 'eu', 'europe' # Major powers
        ]
        return any(k in text for k in cambodia_keywords)

    # Technology: AI, Scams, Security
    if category == 'technology':
        tech_keywords = [
            'ai', 'artificial intelligence', 'chatgpt', 'gemini', 'llama',
            'scam', 'hack', 'malware', 'cybersecurity', 'virus', 'security',
            'facebook', 'telegram', 'tiktok', 'youtube', 'iphone', 'android', 'wahtsapp'
        ]
        return any(k in text for k in tech_keywords)

    # Business: ASEAN, Gold, Oil
    if category == 'business':
        biz_keywords = [
            'asean', 'asia', 'china', 'thailand', 'vietnam', 
            'gold', 'oil', 'price', 'inflation', 'dollar', 'economy', 'trade',
            'export', 'import', 'investment'
        ]
        return any(k in text for k in biz_keywords)

    # Environment: Climate, Disasters
    if category == 'environment':
        env_keywords = [
            'climate', 'warming', 'heat', 'flood', 'storm', 'typhoon', 'mekong',
            'drought', 'rain', 'weather', 'pollution', 'plastic'
        ]
        return any(k in text for k in env_keywords)

    return True

# =========================== 💾 IMAGE CACHE ===========================
class ImageCache:
    """Disk-based image cache."""
    
    def __init__(self, cache_dir: str, max_size_mb: int, expiry_hours: int):
        self.cache_dir = cache_dir
        self.max_size = max_size_mb * 1024 * 1024
        self.expiry = timedelta(hours=expiry_hours)
    
    def _get_cache_path(self, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}.jpg")
    
    def _is_expired(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return True
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
        return datetime.now() - mtime > self.expiry
    
    async def get(self, url: str) -> Optional[bytes]:
        cache_path = self._get_cache_path(url)
        
        if self._is_expired(cache_path):
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                return await asyncio.to_thread(f.read)
        except Exception:
            return None
    
    async def set(self, url: str, image_bytes: bytes) -> None:
        cache_path = self._get_cache_path(url)
        
        try:
            with open(cache_path, 'wb') as f:
                await asyncio.to_thread(f.write, image_bytes)
            await self._cleanup_if_needed()
        except Exception as e:
            logging.warning(f"⚠️ Cache write failed: {e}")
    
    async def _cleanup_if_needed(self) -> None:
        try:
            files = [(os.path.join(self.cache_dir, f), os.path.getmtime(os.path.join(self.cache_dir, f))) 
                    for f in os.listdir(self.cache_dir) 
                    if os.path.isfile(os.path.join(self.cache_dir, f))]
            
            total_size = sum(os.path.getsize(f[0]) for f in files)
            
            if total_size > self.max_size:
                files.sort(key=lambda x: x[1])
                for filepath, _ in files[:len(files)//4]:
                    try:
                        os.remove(filepath)
                        logging.debug(f"🗑️ Removed cached file: {os.path.basename(filepath)}")
                    except Exception:
                        pass
        except Exception as e:
            logging.warning(f"⚠️ Cache cleanup failed: {e}")

# =========================== 🔄 RETRY QUEUE ===========================
class RetryQueue:
    """Manages retry queue in Firebase."""
    
    def __init__(self, db_client):
        self.db = db_client
        self.collection = 'retry_queue'
        self.max_retries = 3
    
    async def add_failed_post(self, failed_post: FailedPost) -> None:
        try:
            await asyncio.to_thread(lambda: self.db.collection(self.collection).add({
                'article_id': failed_post.article_id,
                'article_data': failed_post.article_data,
                'attempts': failed_post.attempts,
                'last_attempt': firestore.SERVER_TIMESTAMP,
                'error_message': failed_post.error_message
            }))
            logging.info(f"🔄 Added to retry queue: {failed_post.article_data.get('title_kh', 'unknown')[:50]}")
        except Exception as e:
            logging.error(f"❌ Failed to add to retry queue: {e}")
    
    async def get_retry_candidates(self) -> List[Tuple[str, Dict]]:
        try:
            docs = await asyncio.to_thread(
                lambda: self.db.collection(self.collection)
                            .where(filter=FieldFilter('attempts', '<', self.max_retries))
                            .limit(5)
                            .get()
            )
            
            candidates = []
            for doc in docs:
                data = doc.to_dict()
                last_attempt = data.get('last_attempt')
                if last_attempt and isinstance(last_attempt, datetime):
                    if datetime.now(ICT) - last_attempt > timedelta(hours=1):
                        candidates.append((doc.id, data))
            
            return candidates
        except Exception as e:
            logging.error(f"❌ Failed to get retry candidates: {e}")
            return []
    
    async def increment_attempts(self, doc_id: str) -> None:
        try:
            await asyncio.to_thread(lambda: self.db.collection(self.collection).document(doc_id).update({
                'attempts': firestore.Increment(1),
                'last_attempt': firestore.SERVER_TIMESTAMP
            }))
        except Exception as e:
            logging.error(f"❌ Failed to increment attempts: {e}")
    
    async def remove_from_queue(self, doc_id: str) -> None:
        try:
            await asyncio.to_thread(
                lambda: self.db.collection(self.collection).document(doc_id).delete()
            )
            logging.info(f"✅ Removed from retry queue: {doc_id}")
        except Exception as e:
            logging.error(f"❌ Failed to remove from queue: {e}")

# =========================== 📊 RATE LIMIT TRACKING ===========================
class RateLimitTracker:
    """Track API usage."""
    
    def __init__(self):
        self.calls: Dict[str, List[datetime]] = {
            'groq': [],
            'gemini': [],
            'facebook': []
        }
        self.limits: Dict[str, Dict[str, int]] = {
            'groq': {'per_minute': 30, 'per_hour': 1000, 'per_day': 14400},
            'gemini': {'per_minute': 15, 'per_hour': 100, 'per_day': 1500},
            'facebook': {'per_minute': 10, 'per_hour': 200, 'per_day': 5000}
        }
    
    def record_call(self, api_name: str) -> None:
        self.calls[api_name].append(datetime.now())
        self._cleanup_old_calls(api_name)
    
    def _cleanup_old_calls(self, api_name: str) -> None:
        cutoff = datetime.now() - timedelta(days=1)
        self.calls[api_name] = [dt for dt in self.calls[api_name] if dt > cutoff]
    
    def get_usage(self, api_name: str) -> Dict[str, int]:
        now = datetime.now()
        calls = self.calls.get(api_name, [])
        
        return {
            'last_minute': sum(1 for dt in calls if now - dt < timedelta(minutes=1)),
            'last_hour': sum(1 for dt in calls if now - dt < timedelta(hours=1)),
            'last_day': len(calls)
        }
    
    def would_exceed_limit(self, api_name: str) -> bool:
        usage = self.get_usage(api_name)
        limits = self.limits.get(api_name, {})
        
        if usage['last_minute'] >= limits.get('per_minute', 999):
            return True
        if usage['last_hour'] >= limits.get('per_hour', 999):
            return True
        if usage['last_day'] >= limits.get('per_day', 999):
            return True
        
        return False
    
    def get_wait_time(self, api_name: str) -> int:
        usage = self.get_usage(api_name)
        limits = self.limits.get(api_name, {})
        
        if usage['last_minute'] >= limits.get('per_minute', 999):
            return 60
        if usage['last_hour'] >= limits.get('per_hour', 999):
            return 300
        if usage['last_day'] >= limits.get('per_day', 999):
            return 3600
        return 0

# Initialize
image_cache = ImageCache(CACHE_DIR, CACHE_MAX_SIZE_MB, CACHE_EXPIRY_HOURS)
rate_tracker = RateLimitTracker()

# =========================== 🕐 TIME FORMATTING ===========================
def format_time_ago(published_date) -> str:
    """Convert to 'X hours ago'."""
    if not published_date:
        return "Recently"
    
    try:
        if isinstance(published_date, str):
            from dateutil import parser
            published_date = parser.parse(published_date)
        
        if published_date.tzinfo is None:
            published_date = ICT.localize(published_date)
        
        now = datetime.now(ICT)
        diff = now - published_date
        
        if diff.days > 7:
            return f"{diff.days // 7} week{'s' if diff.days // 7 > 1 else ''} ago"
        elif diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"
    except Exception as e:
        logging.debug(f"Time formatting error: {e}")
        return "Recently"

# =========================== 📰 NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed", "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "Khmer Times", "rss": "https://www.khmertimeskh.com/feed/", "url": "https://www.khmertimeskh.com"},
        {"name": "CamboJA (Khmer)", "rss": "https://cambojanews.com/kh/feed/", "url": "https://cambojanews.com/kh"},
        {"name": "CamboJA (English)", "rss": "https://cambojanews.com/feed/", "url": "https://cambojanews.com"},
    ],
    "thailand": [
        {"name": "Khaosod English", "rss": "https://www.khaosodenglish.com/feed", "url": "https://www.khaosodenglish.com"},
        {"name": "The Thaiger", "rss": "https://thethaiger.com/feed", "url": "https://thethaiger.com"},
        {"name": "Bangkok Post", "rss": "https://www.bangkokpost.com/rss/data/topstories.xml", "url": "https://www.bangkokpost.com"},
    ],
    "global": [
        {"name": "BBC World News", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "url": "https://www.bbc.com/news/world"},
        {"name": "Al Jazeera", "rss": "https://aljazeera.com/xml/rss/all.xml", "url": "https://www.aljazeera.com"},
        {"name": "Associated Press", "rss": "https://feeds.apnews.com/rss/apf-topnews", "url": "https://apnews.com"},
        {"name": "Reuters", "rss": "https://www.reutersagency.com/feed/?best-topics=world-at-work&post_type=best", "url": "https://www.reuters.com"},
        {"name": "CNN World", "rss": "http://rss.cnn.com/rss/edition_world.rss", "url": "https://edition.cnn.com/world"},
        {"name": "The Guardian", "rss": "https://www.theguardian.com/world/rss", "url": "https://www.theguardian.com/world"},
        {"name": "Deutsche Welle (DW)", "rss": "https://rss.dw.com/xml/rss-en-all", "url": "https://www.dw.com"},
        {"name": "Channel News Asia (CNA)", "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511", "url": "https://www.channelnewsasia.com"}
    ],
    "technology": [
        {"name": "TechCrunch", "rss": "https://techcrunch.com/feed/", "url": "https://techcrunch.com"},
        {"name": "The Verge", "rss": "https://www.theverge.com/rss/index.xml", "url": "https://www.theverge.com"},
        {"name": "BleepingComputer", "rss": "https://www.bleepingcomputer.com/feed/", "url": "https://www.bleepingcomputer.com"},
    ],
    "business": [
        {"name": "CNBC Business", "rss": "https://www.cnbc.com/id/10001147/device/rss/rss.html", "url": "https://www.cnbc.com/business"},
        {"name": "CNBC International", "rss": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "url": "https://www.cnbc.com/world"},
    ],
    "environment": [
        {"name": "ScienceDaily (Climate)", "rss": "https://www.sciencedaily.com/rss/earth_climate/climate.xml", "url": "https://www.sciencedaily.com"},
    ]
}

# =========================== 🎨 VISUAL ENGINE ===========================
@retry_with_backoff(max_retries=3, base_delay=1.0)
async def download_image_bytes(url: str) -> Optional[bytes]:
    """Download image with caching."""
    if not validate_url(url):
        logging.warning(f"⚠️ Invalid image URL: {url}")
        return None
    
    # Check cache
    cached = await image_cache.get(url)
    if cached:
        logging.debug(f"📦 Cache hit: {url[:50]}")
        return cached
    
    try:
        timeout = aiohttp.ClientTimeout(total=15, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logging.warning(f"⚠️ Image download failed: HTTP {resp.status}")
                    return None
                
                content_type = resp.headers.get('Content-Type', '')
                if 'image' not in content_type.lower():
                    logging.warning(f"⚠️ Invalid content type: {content_type}")
                    return None
                
                content_length = resp.headers.get('Content-Length')
                if content_length and int(content_length) > 10 * 1024 * 1024:
                    logging.warning(f"⚠️ Image too large: {content_length} bytes")
                    return None
                
                image_bytes = await resp.read()
                
                if image_bytes:
                    await image_cache.set(url, image_bytes)
                    logging.debug(f"💾 Cached image: {url[:50]}")
                
                return image_bytes
                
    except asyncio.TimeoutError:
        logging.error(f"⏱️ Image download timeout: {url}")
        raise
    except Exception as e:
        logging.error(f"❌ Image download error: {e}")
        raise

async def generate_poster(image_bytes, title, source_name, is_breaking=False):
    """Generate styled poster."""
    if not image_bytes:
        return None
    
    try:
        target_size = (1200, 800)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        
        # Resize & Crop
        ratio = max(target_size[0] / img.width, target_size[1] / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        left = (img.width - target_size[0]) / 2
        top = (img.height - target_size[1]) / 2
        img = img.crop((left, top, left + target_size[0], top + target_size[1]))
        
        # Darken
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.85)
        
        # Gradient overlay
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(300, 800):
            alpha = int(255 * ((y - 300) / 500)**1.2)
            draw.line([(0, y), (1200, y)], fill=(5, 5, 10, alpha))
        
        out = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(out)
        
        # Fonts
        try:
            font_title = ImageFont.truetype(FONT_PATH, 50)
            font_meta = ImageFont.truetype(FONT_PATH, 28)
            font_badge = ImageFont.truetype(FONT_PATH, 24)
        except:
            font_title = ImageFont.load_default()
            font_meta = ImageFont.load_default()
            font_badge = ImageFont.load_default()
        
        # Badge
        badge_text = "BREAKING NEWS" if is_breaking else "AI DAILY UPDATE"
        color = (220, 20, 60) if is_breaking else (0, 102, 204)
        draw.rectangle([50, 530, 270 if is_breaking else 260, 570], fill=color)
        draw.text((65, 535), badge_text, font=font_badge, fill="white")
        
        # Title with wrapping
        text_x, text_y = 50, 590
        max_width = 1100
        max_lines = 3
        
        words = title.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + word + " "
            bbox = draw.textbbox((0, 0), test_line, font=font_title)
            text_width = bbox[2] - bbox[0]
            
            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                    current_line = word + " "
                else:
                    lines.append(word)
                    current_line = ""
        
        if current_line:
            lines.append(current_line.strip())
        
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:35] + "..."
        
        # Draw title
        for line in lines:
            draw.text((text_x+2, text_y+2), line, font=font_title, fill="black")
            draw.text((text_x, text_y), line, font=font_title, fill="white")
            text_y += 70
        
        # Footer
        draw.rectangle([text_x, text_y+20, text_x+5, text_y+50], fill=(255, 204, 0))
        draw.text((text_x+20, text_y+22), f"{source_name} • {datetime.now(ICT):%d %b %Y}", font=font_meta, fill=(220, 220, 220))
        
        bio = io.BytesIO()
        out.convert("RGB").save(bio, format='JPEG', quality=95)
        return bio.getvalue()
        
    except Exception as e:
        logging.error(f"❌ Poster generation error: {e}")
        return None

# =========================== 🧠 AI ENGINE ===========================
@retry_with_backoff(max_retries=3, base_delay=2.0)
async def process_with_ai(article: dict) -> Optional[dict]:
    """Process with Groq AI (Primary) and Gemini (Fallback)."""
    global current_gemini_key_index, failed_gemini_keys
    
    retries = 3
    for attempt in range(retries):
        try:
            # --- 1. Try Groq (Primary) ---
            try:
                if rate_tracker.would_exceed_limit('groq'):
                    raise Exception("Groq rate limit predicted")

                prompt = f"""
Article: {article.get('title', '')}
Summary: {article.get('summary', '')}
Source: {article.get('source', '')}

Act as a professional Khmer journalist. Summarize this news for a Cambodian audience.
Generate JSON:
{{
    "title_kh": "Engaging Khmer title (avoid clickbait)",
    "summary_kh": "A short, engaging paragraph summary (2-3 sentences)",
    "key_points": ["Khmer bullet point 1", "Khmer bullet point 2", "Khmer bullet point 3"],
    "why_matters": "Explain why this is important for Cambodia/World in Khmer",
    "question": "An engaging question to ask the audience in Khmer",
    "sentiment": "Positive/Neutral/Negative",
    "hashtags": "#relevant #tags #aidailynews"
}}
"""
                
                completion = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that responses in JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                
                rate_tracker.record_call('groq')
                resp_content = completion.choices[0].message.content
                if not resp_content:
                    raise ValueError("Empty Groq response")
                    
                data = safe_json_parse(resp_content)
                if data:
                    logging.info(f"🤖 User Groq success")
                    # Fill missing
                    # ... (Validation logic reused below) ...
            
            except Exception as e_groq:
                logging.warning(f"⚠️ Groq failed: {e_groq}. Switching to Gemini...")
                
                # --- 2. Fallback to Gemini ---
                model = genai.GenerativeModel(GEMINI_MODEL)
                
                resp = await asyncio.to_thread(
                    model.generate_content,
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                rate_tracker.record_call('gemini')
                
                if not resp or not hasattr(resp, 'text') or not resp.text:
                    raise ValueError("Empty Gemini response")
                
                data = safe_json_parse(resp.text)
                logging.info(f"🤖 Gemini used as fallback")

            if not data:
                raise ValueError("Failed to parse JSON from both providers")
            
            # Validate fields (Common for both)
            required_fields = ['title_kh', 'summary_kh', 'key_points', 'why_matters', 'question', 'hashtags']
            missing_fields = [f for f in required_fields if f not in data]
            
            if missing_fields:
                logging.warning(f"⚠️ Missing fields: {missing_fields}")
                defaults = {
                    'title_kh': article.get('title', 'ព័ត៌មាន'),
                    'summary_kh': article.get('summary', '')[:300],
                    'key_points': [article.get('summary', '')[:100]],
                    'why_matters': 'ព័ត៌មានពី ' + article.get('source', 'ប្រភព'),
                    'question': 'តើអ្នកយល់យ៉ាងណាដែរ?',
                    'sentiment': 'Neutral',
                    'hashtags': '#News #Cambodia #aidailynews'
                }
                for field in missing_fields:
                    data[field] = defaults.get(field, '')
            
            article.update(data)
            return article
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"❌ AI Multi-Provider error: {e}")
            
            # Check Gemini quota error if that was the last failure
            if "429" in error_msg or "quota" in error_msg.lower():
                current_key = GEMINI_API_KEYS[current_gemini_key_index]
                failed_gemini_keys.add(current_gemini_key_index)
                logging.warning(f"⚠️ Gemini API key {current_gemini_key_index + 1} exhausted")
                
                available_keys = [i for i in range(len(GEMINI_API_KEYS)) if i not in failed_gemini_keys]
                
                if available_keys:
                    current_gemini_key_index = available_keys[0]
                    new_key = GEMINI_API_KEYS[current_gemini_key_index]
                    genai.configure(api_key=new_key)
                    logging.info(f"🔄 Switched to Gemini Key {current_gemini_key_index + 1}")
                    await asyncio.sleep(1)
                    continue
            
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise

# =========================== 📨 FACEBOOK POSTING ===========================
@retry_with_backoff(max_retries=2, base_delay=3.0)
async def post_facebook(article: dict, image_bytes: Optional[bytes] = None) -> bool:
    """Post to Facebook with image or text."""
    try:
        # Select appropriate flag emoji based on category
        category = article.get('category', 'global')
        if category == 'cambodia':
            flag = "🇰🇭"
        elif category == 'thailand':
            flag = "🇹🇭"
        elif category == 'technology':
            flag = "💻"
        elif category == 'business':
            flag = "💰"
        elif category == 'environment':
            flag = "🌱"
        else:  # global or unknown
            flag = "🌍"
        
        pub_time = format_time_ago(article.get('published'))
        post_time = datetime.now(ICT).strftime('%d %b %Y, %H:%M')
        
        # Enhanced post template with better formatting and engagement
        points = "\n".join([f"• {p}" for p in article.get('key_points', [])])
        
        message = (
            f"{flag} {article.get('title_kh', article.get('title', ''))}\n\n"
            f"{article.get('summary_kh', article.get('summary', '')[:300])}\n\n"
            f"📋 **ចំណុចសំខាន់ៗ\n"
            f"{points}\n\n"
            f"� **ហេតុអ្វីវាសំខាន់?\n"
            f"{article.get('why_matters', '')}\n\n"
            f"🗣️ **យោបល់របស់អ្នក:\n"
            f"{article.get('question', '')}\n\n"
            f"══════════════════\n"
            f"ℹ️ ព័ត៌មានលម្អិត\n"
            f"✓ ប្រភព: {article.get('source', '')}\n"
            f"⏰ បានផ្សាយ: {pub_time}\n"
            f"📅 ថ្ងៃនេះ: {post_time}\n"
            f"══════════════════\n\n"
            f"🔗 អានបន្ថែម: {article['link']}\n\n"
            f"{article.get('hashtags', '#News #Cambodia')} #aidailynews\n\n"
            f"👍 Like • 💬 Comment • 🔔 Follow for more updates"
        )
        
        # Try with image first
        if image_bytes:
            url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
            try:
                async with aiohttp.ClientSession() as session:
                    data = FormData()
                    data.add_field('access_token', FB_ACCESS_TOKEN)
                    data.add_field('message', message)
                    data.add_field('source', image_bytes, filename='news.jpg', content_type='image/jpeg')
                    
                    async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        result = await resp.json()
                        
                        if 'id' in result:
                            logging.info(f"✅ Facebook posted (with image): {result['id']}")
                            rate_tracker.record_call('facebook')
                            return True
                        elif 'error' in result:
                            error_code = result['error'].get('code')
                            error_msg = result['error'].get('message', '')
                            
                            if error_code in [4, 17, 32, 613]:
                                logging.warning(f"⏱️ Facebook rate limit (code {error_code})")
                                raise Exception(f"Rate limit: {error_msg}")
                            
                            logging.warning(f"⚠️ Image post failed (code {error_code}), trying text...")
            except asyncio.TimeoutError:
                logging.warning(f"⏱️ Image upload timeout, trying text...")
        
        # Fallback: text-only
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
        async with aiohttp.ClientSession() as session:
            data = FormData()
            data.add_field('access_token', FB_ACCESS_TOKEN)
            data.add_field('message', message)
            data.add_field('link', article['link'])
            
            async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                result = await resp.json()
                
                if 'id' in result:
                    logging.info(f"✅ Facebook posted (text): {result['id']}")
                    rate_tracker.record_call('facebook')
                    return True
                else:
                    error_info = result.get('error', result)
                    logging.error(f"❌ Facebook API error: {error_info}")
                    raise Exception(f"Facebook error: {error_info}")
    
    except Exception as e:
        logging.error(f"❌ Facebook posting failed: {e}")
        raise

# =========================== 📊 DAILY REPORT ===========================
async def generate_daily_report() -> str:
    """Generate daily statistics."""
    now = datetime.now(ICT)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        posts_ref = db.collection('posted_articles')\
            .where(filter=FieldFilter('posted_at', '>=', today_start))\
            .stream()
        
        stats = {
            'total': 0,
            'facebook_success': 0,
            'sources': {},
            'failed': 0
        }
        
        for post in posts_ref:
            data = post.to_dict()
            stats['total'] += 1
            
            fb_success = data.get('facebook', False)
            
            if fb_success:
                stats['facebook_success'] += 1
            else:
                stats['failed'] += 1
            
            source = data.get('source', 'Unknown')
            stats['sources'][source] = stats['sources'].get(source, 0) + 1
        
        api_usage = {
            'groq': rate_tracker.get_usage('groq')['last_day'],
            'gemini': rate_tracker.get_usage('gemini')['last_day'],
            'facebook': rate_tracker.get_usage('facebook')['last_day']
        }
        
        success_rate = 0
        if stats['total'] > 0:
            success_rate = int(((stats['total'] - stats['failed']) / stats['total']) * 100)
        
        top_sources = sorted(stats['sources'].items(), key=lambda x: x[1], reverse=True)[:3]
        
        report = f"""📊 **Daily Report** - {now.strftime('%b %d, %Y')}
━━━━━━━━━━━━━━━━━━━━━━

✅ **Posted Today:** {stats['total']} articles
❌ **Failed:** {stats['failed']} attempts
📊 **Success Rate:** {success_rate}%

📘 **Facebook Stats:**
  • Posted: {stats['facebook_success']}/{stats['total']}

🔥 **Top Sources:**
"""
        
        if top_sources:
            for i, (source, count) in enumerate(top_sources, 1):
                report += f"  {i}. {source} ({count} posts)\n"
        else:
            report += "  No posts today\n"
        
        report += f"""
💰 **API Usage:**
💰 **API Usage:**
  🤖 Groq: {api_usage['groq']}
  🤖 Gemini: {api_usage['gemini']}
  📘 Facebook: {api_usage['facebook']}

🔑 **Keys:** Groq (1), Gemini ({len(GEMINI_API_KEYS)})
⏰ **Next Report:** Tomorrow 10:00 PM
"""
        
        return report
        
    except Exception as e:
        logging.error(f"❌ Report generation error: {e}")
        return f"❌ Error: {str(e)[:100]}"

async def daily_report_scheduler():
    """Check for report time."""
    last_sent_day = None
    
    while True:
        try:
            now = datetime.now(ICT)
            current_time = now.strftime("%H:%M")
            current_day = now.date()
            
            if current_time == DAILY_REPORT_TIME and current_day != last_sent_day:
                report = await generate_daily_report()
                logging.info(f"📊 Daily Report:\n{report}")
                last_sent_day = current_day
            
            await asyncio.sleep(60)
            
        except Exception as e:
            logging.error(f"❌ Report scheduler error: {e}")
            await asyncio.sleep(60)

# =========================== 🚀 MAIN WORKER ===========================
async def worker():
    """Main RSS scanning and posting worker."""
    logging.info("🚀 Facebook News Bot Started")
    
    recent_posts_cache = set()
    
    while True:
        h = datetime.now(ICT).hour
        
        # Dynamic scheduling
        if 0 <= h < 5:
            interval, limit = 1800, 1  # Night: 30min, 1 post
        elif 5 <= h < 9 or 11 <= h < 14 or 17 <= h < 20:
            interval, limit = 300, 2  # Peak: 5min, 2 posts (reduced from 4)
        else:
            interval, limit = 600, 2  # Normal: 10min, 2 posts
        
        logging.info(f"🔍 Scanning... (Limit: {limit}, Next: {interval}s)")
        posted_count = 0
        
        for cat, sources in NEWS_SOURCES.items():
            if posted_count >= limit:
                break
            
            for src in sources:
                if posted_count >= limit:
                    break
                
                source_key = f"{cat}:{src['name']}"
                
                # Check circuit breaker
                if not circuit_breaker.call(source_key):
                    logging.debug(f"⚠️ Circuit open for {src['name']}")
                    continue
                
                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive'
                    }
                    
                    feed = await asyncio.wait_for(
                        asyncio.to_thread(lambda: feedparser.parse(
                            src['rss'],
                            request_headers=headers
                        )),
                        timeout=15.0
                    )
                    
                    if not feed or not hasattr(feed, 'entries') or not feed.entries:
                        logging.warning(f"⚠️ No entries from {src['name']}")
                        continue
                    
                    logging.info(f"📡 Fetched {len(feed.entries)} from {src['name']}")
                    
                    for e in feed.entries[:5]:
                        if not hasattr(e, 'link') or not e.link:
                            continue
                        
                        aid = hashlib.md5(e.link.encode()).hexdigest()
                        
                        # Check cache
                        if aid in recent_posts_cache:
                            continue
                        
                        # Check Firebase
                        try:
                            doc = await asyncio.wait_for(
                                asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).get()),
                                timeout=5.0
                            )
                            if doc.exists:
                                recent_posts_cache.add(aid)
                                continue
                        except asyncio.TimeoutError:
                            logging.warning(f"⏱️ Firebase timeout for {src['name']}")
                            continue
                        
                        raw = {
                            "title": getattr(e, 'title', 'ព័ត៌មាន'),
                            "link": e.link,
                            "summary": BeautifulSoup(e.get('summary', ''), "html.parser").get_text()[:1500],
                            "source": src['name'],
                            "category": cat,
                            "published": e.get('published', e.get('updated'))
                        }
                        
                        # Filter based on category relevance
                        if not is_relevant_content(raw, cat):
                            logging.debug(f"⏭️ Skipping irrelevant {cat}: {raw['title'][:30]}")
                            continue
                        
                        is_priority = is_priority_news(raw)
                        
                        if posted_count >= limit:
                            break
                        
                        # Check similarity
                        content_fingerprint = create_article_fingerprint(raw['title'], raw['summary'])
                        
                        try:
                            similar_docs = await asyncio.to_thread(
                                lambda: db.collection('posted_articles')
                                          .where(filter=FieldFilter('fingerprint', '==', content_fingerprint))
                                          .limit(1)
                                          .get()
                            )
                            if similar_docs:
                                logging.info(f"⚠️ Duplicate article: {raw['title'][:50]}")
                                continue
                        except Exception:
                            pass
                        
                        # Extract media
                        media_images = []
                        
                        if hasattr(e, 'media_content') and e.media_content:
                            for media in e.media_content[:10]:
                                url = media.get('url', '')
                                media_type = media.get('type', '').lower()
                                
                                if 'image' in media_type or url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                                    media_images.append(url)
                        
                        if len(media_images) < 10:
                            if summary_html := e.get('summary', ''):
                                soup = BeautifulSoup(summary_html, 'html.parser')
                                for img_tag in soup.find_all('img', limit=10):
                                    img_url = urljoin(src['url'], img_tag.get('src', ''))
                                    if img_url and img_url not in media_images:
                                        media_images.append(img_url)
                        
                        img_url = media_images[0] if media_images else None
                        raw['media_images'] = media_images[:10]
                        
                        # Process with AI
                        try:
                            final = await asyncio.wait_for(process_with_ai(raw), timeout=30.0)
                        except asyncio.TimeoutError:
                            logging.error(f"⏱️ AI timeout for {src['name']}")
                            circuit_breaker.record_failure(source_key)
                            continue
                        except Exception as ai_error:
                            logging.error(f"❌ AI failed: {ai_error}")
                            circuit_breaker.record_failure(source_key)
                            continue
                        
                        if not final:
                            circuit_breaker.record_failure(source_key)
                            continue
                        
                        # Download image
                        raw_bytes = None
                        if img_url and validate_url(img_url):
                            try:
                                raw_bytes = await asyncio.wait_for(
                                    download_image_bytes(img_url),
                                    timeout=15.0
                                )
                            except Exception as e:
                                logging.warning(f"⚠️ Image download failed: {e}")
                        
                        # Generate poster
                        poster_bytes = None
                        if raw_bytes:
                            try:
                                poster_bytes = await asyncio.wait_for(
                                    generate_poster(
                                        raw_bytes,
                                        final.get('title_kh', 'ព័ត៌មាន'),
                                        final['source'],
                                        final.get('sentiment') == 'Warning'
                                    ),
                                    timeout=10.0
                                )
                            except Exception as e:
                                logging.warning(f"⚠️ Poster generation failed: {e}")
                        
                        final_img = poster_bytes if poster_bytes else raw_bytes
                        
                        # Post to Facebook
                        fb_ok = False
                        try:
                            fb_ok = await asyncio.wait_for(
                                post_facebook(final, final_img),
                                timeout=30.0
                            )
                        except Exception as e:
                            logging.error(f"❌ Facebook post failed: {e}")
                        
                        if fb_ok:
                            try:
                                await asyncio.wait_for(
                                    asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).set({
                                        "title": final.get('title', ''),
                                        "fingerprint": content_fingerprint,
                                        "posted_at": firestore.SERVER_TIMESTAMP,
                                        "facebook": fb_ok,
                                        "source": src['name']
                                    })),
                                    timeout=5.0
                                )
                                recent_posts_cache.add(aid)
                                if len(recent_posts_cache) > 100:
                                    recent_posts_cache.pop()
                            except asyncio.TimeoutError:
                                logging.warning(f"⏱️ Firebase save timeout")
                            
                            logging.info(f"✅ Posted: {final.get('title_kh', 'unknown')[:50]}")
                            posted_count += 1
                            circuit_breaker.record_success(source_key)
                            await asyncio.sleep(15)
                        else:
                            failed_post = FailedPost(
                                article_id=aid,
                                article_data=final,
                                image_bytes=final_img,
                                attempts=1,
                                last_attempt=datetime.now(ICT),
                                error_message="Facebook post failed"
                            )
                            await RetryQueue(db).add_failed_post(failed_post)
                            circuit_breaker.record_failure(source_key)
                
                except asyncio.CancelledError:
                    logging.info("🛑 Worker cancelled")
                    raise
                except Exception as ex:
                    logging.error(f"❌ Unexpected error from {src['name']}: {ex}")
                    circuit_breaker.record_failure(source_key)
        
        # Keep-alive ping
        try:
            port = int(os.environ.get("PORT", 8080))
            async with aiohttp.ClientSession() as session:
                await session.get(f"http://localhost:{port}/health", timeout=aiohttp.ClientTimeout(total=5))
            logging.debug("✅ Keep-alive ping sent")
        except:
            pass
        
        logging.info(f"💤 Sleeping for {interval}s")
        try:
            # Wait for interval OR manual trigger event
            await asyncio.wait_for(scan_event.wait(), timeout=interval)
            scan_event.clear()  # Reset event
            logging.info("👊 Manual trigger received! Waking up...")
        except asyncio.TimeoutError:
            pass  # Normal timeout, just loop again

# =========================== 🔄 RETRY WORKER ===========================
async def retry_worker() -> None:
    """Retry failed posts."""
    logging.info("🔄 Retry worker started")
    retry_queue = RetryQueue(db)
    
    while True:
        try:
            candidates = await retry_queue.get_retry_candidates()
            
            for doc_id, data in candidates:
                article = data.get('article_data', {})
                
                logging.info(f"🔄 Retrying: {article.get('title_kh', 'unknown')[:50]}")
                
                fb_ok = False
                try:
                    fb_ok = await asyncio.wait_for(post_facebook(article, None), timeout=30.0)
                except Exception as e:
                    logging.warning(f"⚠️ Retry failed: {e}")
                
                if fb_ok:
                    await retry_queue.remove_from_queue(doc_id)
                    logging.info(f"✅ Retry successful")
                else:
                    await retry_queue.increment_attempts(doc_id)
                
                await asyncio.sleep(10)
        
        except Exception as e:
            logging.error(f"❌ Retry worker error: {e}")
        
        await asyncio.sleep(1800)  # 30 minutes

# =========================== 🌐 WEB SERVER ===========================
async def health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.Response(text="Facebook News Bot Running ✅")

async def metrics(req: web.Request) -> web.Response:
    """Metrics endpoint."""
    metrics_data = {
        'rate_limits': {
            'groq': rate_tracker.get_usage('groq'),
            'gemini': rate_tracker.get_usage('gemini'),
            'facebook': rate_tracker.get_usage('facebook')
        },
        'circuit_breakers': {
            key: {
                'failures': circuit_breaker.failures[key],
                'is_open': circuit_breaker.opened[key]
            }
            for key in circuit_breaker.failures.keys()
        },
        'cache_stats': {
            'directory': CACHE_DIR,
            'max_size_mb': CACHE_MAX_SIZE_MB,
            'expiry_hours': CACHE_EXPIRY_HOURS
        },
        'timestamp': datetime.now(ICT).isoformat()
    }
    return web.json_response(metrics_data)

async def dashboard_handler(request: web.Request) -> web.Response:
    """Serve dashboard HTML."""
    try:
        with open('dashboard.html', 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="Dashboard not found", status=404)

_stats_cache = {'data': None, 'timestamp': None}
STATS_CACHE_SECONDS = 30

async def stats_api_handler(request: web.Request) -> web.Response:
    """API endpoint for dashboard statistics."""
    try:
        now = datetime.now(ICT)
        
        # Check cache
        if _stats_cache['data'] and _stats_cache['timestamp']:
            cache_age = (now - _stats_cache['timestamp']).total_seconds()
            if cache_age < STATS_CACHE_SECONDS:
                return web.json_response(_stats_cache['data'])
        
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        
        posts_ref = db.collection('posted_articles')
        
        # Get recent posts
        recent_posts_query = posts_ref.order_by('posted_at', direction=firestore.Query.DESCENDING).limit(10)
        recent_docs = await asyncio.to_thread(lambda: list(recent_posts_query.stream()))
        
        # Get today's posts
        today_query = posts_ref.where(filter=FieldFilter('posted_at', '>=', day_ago)).stream()
        today_docs = await asyncio.to_thread(lambda: list(today_query))
        
        # Get week's posts
        week_query = posts_ref.where(filter=FieldFilter('posted_at', '>=', week_ago)).stream()
        week_docs = await asyncio.to_thread(lambda: list(week_query))
        
        # Process recent posts
        all_posts = []
        for doc in recent_docs:
            data = doc.to_dict()
            if not data:
                continue
            
            all_posts.append({
                'id': doc.id,
                'title': data.get('title', 'No title'),
                'source': data.get('source', 'Unknown'),
                'posted_at': data.get('posted_at').isoformat() if data.get('posted_at') else None,
                'platforms': {'facebook': data.get('facebook', False)}
            })
        
        # Count today's posts
        today_count = 0
        today_success = 0
        for doc in today_docs:
            data = doc.to_dict()
            if not data:
                continue
            today_count += 1
            if data.get('facebook'):
                today_success += 1
        
        # Count week's posts
        week_count = 0
        for doc in week_docs:
            if doc.to_dict():
                week_count += 1
        
        stats = {
            'total_all': week_count,
            'total_today': today_count,
            'total_week': week_count,
            'success_count': today_success,
            'recent_posts': all_posts,
            'rate_limits': {
                'groq': rate_tracker.get_usage('groq'),
                'gemini': rate_tracker.get_usage('gemini'),
                'facebook': rate_tracker.get_usage('facebook')
            },
            'timestamp': now.isoformat()
        }
        
        _stats_cache['data'] = stats
        _stats_cache['timestamp'] = now
        
        return web.json_response(stats)
        
    except Exception as e:
        logging.error(f"❌ Stats API error: {e}")
        if _stats_cache['data']:
            return web.json_response(_stats_cache['data'])
        
        return web.json_response({
            'error': 'Service unavailable',
            'total_all': 0,
            'total_today': 0,
            'total_week': 0,
            'success_count': 0,
            'recent_posts': [],
            'rate_limits': {},
            'timestamp': datetime.now(ICT).isoformat()
        }, status=503)

async def trigger_handler(request: web.Request):
    """Manual trigger endpoint."""
    logging.info("👊 Manual trigger received!")
    scan_event.set()
    return web.json_response({'status': 'triggered'})

# =========================== 🚀 MAIN ===========================
async def main():
    """Main entry point."""
    
    # Set up web server
    app = web.Application()
    app.router.add_get('/', health)
    app.router.add_get('/health', health)
    app.router.add_get('/dashboard', lambda r: web.FileResponse('dashboard.html'))
    app.router.add_get('/api/stats', stats_api_handler)
    app.router.add_post('/api/trigger', trigger_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    
    logging.info("✅ Facebook News Bot Initialized")
    
    # Start all services
    await asyncio.gather(
        site.start(),
        worker(),
        retry_worker(),
        daily_report_scheduler()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped by user")
    except Exception as e:
        logging.critical(f"❌ Fatal error: {e}")