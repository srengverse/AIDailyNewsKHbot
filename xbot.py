# xbot.py — X (Twitter) News Bot 2026
# Features:
# - Post Cambodia + International + Thai + Vietnamese news to X/Twitter
# - Dynamic time-based posting (peak hours = high frequency)
# - BREAKING NEWS BOOST MODE
# - Gemini AI translation to natural Khmer
# - Smart image + text with proper formatting for X
# - Thread support for longer content
# - Hashtag optimization
# - Never crashes — Full error handling

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
from typing import Optional, Dict, List

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
import tweepy
from aiohttp import web
import aiosqlite

# =========================== CONFIG ===========================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Twitter/X API Credentials (v2)
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

GEMINI_MODEL = "gemini-2.5-flash"  # ✅ លឿន + ថោក + គុណភាពល្អ

# Timezone Cambodia
ICT = pytz.timezone('Asia/Phnom_Penh')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("xbot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("GEMINI_API_KEY missing! Using English fallback")

# Initialize Twitter API v2
try:
    twitter_client = tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
        wait_on_rate_limit=True
    )
    # For media upload (v1.1 API)
    auth = tweepy.OAuth1UserHandler(
        TWITTER_API_KEY, 
        TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN, 
        TWITTER_ACCESS_SECRET
    )
    twitter_api_v1 = tweepy.API(auth)
    logging.info("✅ Twitter API initialized")
except Exception as e:
    logging.critical(f"❌ Twitter API init failed: {e}")
    twitter_client = None
    twitter_api_v1 = None

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

DB_FILE = "xbot_posted.db"

# =========================== HASHTAGS & FORMATTING ===========================
HASHTAGS = {
    "cambodia": ["#Cambodia", "#KhmerNews", "#PhnomPenh", "#ព័ត៌មាន"],
    "international": ["#WorldNews", "#Breaking", "#International"],
    "thai": ["#Thailand", "#Bangkok", "#ThaiNews"],
    "vietnamese": ["#Vietnam", "#VietnamNews", "#Hanoi"]
}

# =========================== STATISTICS ===========================
@dataclass
class XBotStats:
    posted_today: int = 0
    failed_posts: int = 0
    breaking_news_count: int = 0
    threads_created: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())
    
    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logging.info(f"📊 Daily Stats: Posts={self.posted_today}, Fails={self.failed_posts}, Breaking={self.breaking_news_count}, Threads={self.threads_created}")
            self.posted_today = 0
            self.failed_posts = 0
            self.breaking_news_count = 0
            self.threads_created = 0
            self.last_reset = today
    
    def log_summary(self):
        logging.info(f"📈 X Stats: Posts={self.posted_today} | Fails={self.failed_posts} | Breaking={self.breaking_news_count}")

stats = XBotStats()

# =========================== BREAKING NEWS DETECTION ===========================
BREAKING_KEYWORDS_KH = ["បន្ទាន់", "ភ្លាម", "សន្ធឹក", "គ្រោះថ្នាក់", "បាញ់", "ផ្ទុះ", "ប៉ះទង្គិច", "រញ្ជួយដី", "breaking"]
BREAKING_KEYWORDS_EN = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "dies", "killed", "crisis", "attack", "fire"]
HIGH_PRIORITY_SOURCES = {"Khmer Times", "Thmey Thmey", "DAP News", "BBC News", "Al Jazeera"}

def get_current_slot() -> Dict:
    """កំណត់ចំនួន Post និងមោងរង់ចាំ"""
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    
    if 5 <= h < 8:       return {"name": "Morning",      "max": 6,  "delay": 90}
    if 8 <= h < 11.5:    return {"name": "Work AM",      "max": 5,  "delay": 120}
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak",   "max": 8,  "delay": 60}
    if 13.5 <= h < 17:   return {"name": "Afternoon",    "max": 4,  "delay": 150}
    if 17 <= h < 21:     return {"name": "Evening Prime","max": 10, "delay": 50}
    if 21 <= h < 23:     return {"name": "Night",        "max": 4,  "delay": 180}
    return                       {"name": "Deep Night",   "max": 2,  "delay": 400}

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
    """Initialize database"""
    for attempt in range(3):
        try:
            async with aiosqlite.connect(DB_FILE, timeout=15) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posted (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        source TEXT,
                        tweet_id TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_posted_at ON posted(posted_at)")
                await db.commit()
            logging.info("✅ Database ready")
            return
        except Exception as e:
            logging.warning(f"DB init attempt {attempt+1}/3 failed: {e}")
            await asyncio.sleep(3)
    logging.critical("❌ DB failed")

async def is_posted(aid: str) -> bool:
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None
    except:
        return False

async def mark_as_posted(aid: str, cat: str, source: str, tweet_id: str):
    try:
        async with aiosqlite.connect(DB_FILE, timeout=10) as db:
            await db.execute(
                "INSERT OR IGNORE INTO posted(article_id, category, source, tweet_id) VALUES(?,?,?,?)", 
                (aid, cat, source, tweet_id)
            )
            await db.commit()
    except Exception as e:
        logging.warning(f"DB insert error: {e}")

# =========================== RSS & IMAGE ===========================
async def fetch_rss(url: str, source_name: str) -> Optional[feedparser.FeedParserDict]:
    headers = {"User-Agent": "XNewsBot/2.0"}
    
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        feed = feedparser.parse(await response.text())
                        if feed.entries:
                            return feed
        except Exception as e:
            logging.warning(f"RSS fetch error {source_name}: {e}")
        if attempt < 2:
            await asyncio.sleep(2)
    
    return None

def get_image(entry, base_url: str) -> Optional[str]:
    try:
        if getattr(entry, "media_content", None):
            return entry.media_content[0].get("url")
        
        html_content = entry.get("summary", "") or entry.get("description", "")
        soup = BeautifulSoup(html_content, "html.parser")
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
async def translate_for_twitter(article: Dict, max_retries: int = 3) -> Dict:
    """Translate with Twitter-optimized format"""
    prompt = (
        f"Translate to engaging Khmer for Twitter/X post:\n\n"
        f"Title: {article['title']}\n"
        f"Content: {article['summary'][:2000]}\n\n"
        f"Requirements:\n"
        f"- Use conversational, modern Khmer\n"
        f"- Title: maximum 100 characters\n"
        f"- Body: maximum 200 characters (short & punchy for Twitter)\n"
        f"- Make it engaging and shareable\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{\"title_kh\": \"...\", \"body_kh\": \"...\"}}'
    )
    
    for attempt in range(max_retries):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            
            text = resp.text.strip()
            text = re.sub(r"^```json\s*|```$", "", text, flags=re.M)
            data = json.loads(text)
            
            article["title_kh"] = data.get("title_kh", article["title"])[:100]
            article["body_kh"] = data.get("body_kh", article["summary"][:200])[:200]
            
            await asyncio.sleep(7)
            return article
        
        except Exception as e:
            logging.warning(f"Gemini error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    # Fallback
    article["title_kh"] = article["title"][:100]
    article["body_kh"] = article["summary"][:200]
    return article

# =========================== TWITTER POSTING ===========================
async def download_image(url: str) -> Optional[bytes]:
    """Download image for Twitter upload"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200 and "image" in response.content_type:
                    img_data = await response.read()
                    # Twitter limit: 5MB
                    if len(img_data) <= 5 * 1024 * 1024:
                        return img_data
    except Exception as e:
        logging.warning(f"Image download failed: {e}")
    return None

def format_tweet_text(article: Dict, category: str, is_breaking: bool = False) -> str:
    """Format tweet text with proper structure"""
    flag = ""
    if category == "thai": flag = "🇹🇭"
    elif category == "vietnamese": flag = "🇻🇳"
    elif category == "cambodia": flag = "🇰🇭"
    else: flag = "🌍"
    
    emoji = "🚨 BREAKING" if is_breaking else "📰"
    
    # Build tweet text
    text = f"{emoji} {flag} {article['title_kh']}\n\n"
    
    if article.get('body_kh'):
        text += f"{article['body_kh']}\n\n"
    
    # Add hashtags (max 2-3 for Twitter best practices)
    hashtags = HASHTAGS.get(category, [])[:3]
    if hashtags:
        text += " ".join(hashtags) + "\n\n"
    
    # Add link
    text += f"🔗 {article['link']}"
    
    # Twitter limit: 280 characters
    if len(text) > 280:
        # Truncate body
        available = 280 - len(text) + len(article.get('body_kh', ''))
        article['body_kh'] = article.get('body_kh', '')[:available-3] + "..."
        text = format_tweet_text(article, category, is_breaking)
    
    return text

async def post_to_twitter(article: Dict, category: str, is_breaking: bool = False) -> Optional[str]:
    """Post to Twitter/X with image support"""
    if not twitter_client:
        logging.error("Twitter client not initialized")
        return None
    
    try:
        text = format_tweet_text(article, category, is_breaking)
        
        # Try to upload media
        media_id = None
        if article.get("image_url"):
            img_data = await download_image(article["image_url"])
            if img_data:
                try:
                    # Upload media using v1.1 API
                    media = await asyncio.to_thread(
                        twitter_api_v1.media_upload,
                        filename="image.jpg",
                        file=img_data
                    )
                    media_id = media.media_id
                    logging.info("✅ Image uploaded to Twitter")
                except Exception as e:
                    logging.warning(f"Media upload failed: {e}")
        
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
        logging.info(f"✅ POSTED TO X: {article['title_kh'][:50]}... | Tweet ID: {tweet_id}")
        return str(tweet_id)
    
    except Exception as e:
        logging.error(f"❌ Twitter post failed: {e}")
        stats.failed_posts += 1
        return None

# =========================== MAIN WORKER ===========================
async def worker():
    """Main worker loop"""
    await init_db()
    logging.info("🚀 X (Twitter) News Bot 2026 STARTED")

    boost_until = None
    
    while True:
        try:
            stats.reset_if_new_day()
            now = datetime.now(ICT)
            slot = get_current_slot()
            
            # Boost mode
            if boost_until and now < boost_until:
                max_posts = 15
                delay = 90
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
                        
                        if await is_posted(aid):
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
                        
                        # Translate
                        article = await translate_for_twitter(article)
                        
                        # Check breaking news
                        breaking = is_breaking_news(article)
                        if breaking and not boost_until:
                            logging.info("🚨 BREAKING NEWS DETECTED!")
                            boost_until = now + timedelta(minutes=15)
                            stats.breaking_news_count += 1
                        
                        # Post to Twitter
                        tweet_id = await post_to_twitter(article, cat, breaking)
                        
                        if tweet_id:
                            await mark_as_posted(aid, cat, src["name"], tweet_id)
                            stats.posted_today += 1
                            posted_count += 1
                            
                            # Twitter rate limit: wait between posts
                            await asyncio.sleep(10)
                    
                    except Exception as e:
                        logging.error(f"Error processing {src['name']}: {e}")
                        continue
            
            stats.log_summary()
            logging.info(f"📊 Cycle complete: {posted_count} tweets | Mode: {slot['name']} | Next in {delay}s")
            
            await asyncio.sleep(delay)
        
        except Exception as e:
            logging.critical(f"💥 Worker crashed: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(60)

# =========================== HEALTH SERVER ===========================
async def health(request):
    return web.Response(
        text=json.dumps({
            "status": "alive",
            "bot": "X (Twitter) News Bot 2026",
            "stats": {
                "posted_today": stats.posted_today,
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
    
    port = int(os.environ.get("PORT", 8081))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"🌐 Health server running on port {port}")

# =========================== RUN ===========================
async def main():
    await asyncio.gather(
        web_server(),
        worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 X Bot stopped by user")
    except Exception as e:
        logging.critical(f"💥 Fatal crash: {e}\n{traceback.format_exc()}")