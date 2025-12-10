# main.py — Ultimate News Bot v5.0 (Anti-Spam + Semantic Deduplication)
# គោលបំណង: បង្ហោះព័ត៌មានសំខាន់ៗ កុំអោយស្ទួន កុំអោយ Spam

import os
import asyncio
import json
import hashlib
import re
import logging
import traceback
import io
from datetime import datetime, timedelta
from urllib.parse import urljoin
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from difflib import SequenceMatcher  # ប្រើសម្រាប់ផ្ទៀងផ្ទាត់ភាពស្រដៀងគ្នានៃអត្ថបទ

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

import firebase_admin
from firebase_admin import credentials, firestore

# =========================== CONFIGURATION ===========================
load_dotenv()

# --- API KEYS ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_CHANNEL_LINK = os.getenv("TELEGRAM_CHANNEL_LINK", "https://t.me/AIDailyNewsKH")

# --- TWITTER/X ---
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# --- SYSTEM SETTINGS ---
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() == "true"
ENABLE_TWITTER = os.getenv("ENABLE_TWITTER", "true").lower() == "true"
RENDER_SERVICE_URL = os.getenv("RENDER_SERVICE_URL", "https://your-app.onrender.com")

# Timezone
ICT = pytz.timezone('Asia/Phnom_Penh')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# =========================== SPAM & FILTER CONFIG ===========================

# ពាក្យគន្លឹះដែលត្រូវហាមឃាត់ (Spam/Junk Keywords)
BLOCKED_KEYWORDS = [
    "ឆ្នោត", "lottery", "lotto", "vippro", "game", "casino", "betting", 
    "រាសី", "horoscope", "promotion", "discount", "ទិញ", "លក់", "buy", "sell",
    "sex", "xxx", "porn", "18+", "partner", "sponsored"
]

# កម្រិតភាពស្រដៀងគ្នា (0.0 ដល់ 1.0)។ បើចំណងជើងស្រដៀងគ្នាលើស 0.65 (65%) ចាត់ទុកថាស្ទួន
SIMILARITY_THRESHOLD = 0.65 

# =========================== INITIALIZATION ===========================

# 1. Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY missing!")

# 2. Telegram
telegram_bot = None
if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN:
    telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

# 3. Twitter
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
    except Exception as e:
        logging.error(f"❌ Twitter Setup Failed: {e}")

# 4. Firebase (Database)
db = None
try:
    firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_creds_str:
        cred_dict = json.loads(firebase_creds_str)
        cred = credentials.Certificate(cred_dict)
    elif os.path.exists("firebase_key.json"):
        cred = credentials.Certificate("firebase_key.json")
    else:
        raise FileNotFoundError("No Firebase credentials found!")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    logging.info("✅ Firebase Firestore Connected!")
except Exception as e:
    logging.critical(f"❌ Firebase Setup Failed: {e}")

# =========================== NEWS SOURCES ===========================
NEWS_SOURCES = {
    # អាទិភាពទី ១: ព័ត៌មានកម្ពុជា
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
    ],
    # អាទិភាពទី ២: អន្តរជាតិ
    "international": [
        {"name": "BBC World",      "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",      "url": "https://www.bbc.com"},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com"},
    ],
    # អាទិភាពទី ៣: តំបន់
    "regional": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed",            "url": "https://www.bangkokpost.com"},
        {"name": "Tuoi Tre News",  "rss": "https://news.tuoitre.vn/rss.htm",                 "url": "https://news.tuoitre.vn"},
    ]
}

BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "គ្រោះថ្នាក់", "ផ្ទុះ", "ស្លាប់", "dead", "crisis"]

@dataclass
class BotStats:
    telegram_posts: int = 0
    twitter_posts: int = 0
    spam_blocked: int = 0
    duplicates_blocked: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())

    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            self.telegram_posts = 0
            self.twitter_posts = 0
            self.spam_blocked = 0
            self.duplicates_blocked = 0
            self.last_reset = today
            logging.info("📊 Stats Reset for New Day")

stats = BotStats()

# =========================== SMART LOGIC FUNCTIONS ===========================

def is_spam(text: str) -> bool:
    """ពិនិត្យមើលថាតើអត្ថបទនេះជា Spam ឬទេ"""
    text_lower = text.lower()
    for keyword in BLOCKED_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

def check_similarity(new_title: str, recent_titles: List[str]) -> bool:
    """ពិនិត្យមើលថាតើចំណងជើងនេះដូចគ្នានឹងចំណងជើងមុនៗដែរឬទេ (Semantic Check)"""
    new_clean = re.sub(r'[^\w\s]', '', new_title.lower())
    
    for old_title in recent_titles:
        old_clean = re.sub(r'[^\w\s]', '', old_title.lower())
        # ប្រើ SequenceMatcher ដើម្បីរក % នៃភាពដូចគ្នា
        similarity = SequenceMatcher(None, new_clean, old_clean).ratio()
        if similarity > SIMILARITY_THRESHOLD:
            logging.info(f"🚫 Duplicate Content Blocked: '{new_title}' is {similarity*100:.1f}% similar to '{old_title}'")
            return True
    return False

async def get_recent_titles(limit: int = 30) -> List[str]:
    """ទាញយកចំណងជើងចុងក្រោយពី Firebase ដើម្បីផ្ទៀងផ្ទាត់"""
    if not db: return []
    try:
        titles = []
        # ទាញយកតែចំណងជើងដែល Post ក្នុងរយៈពេល ២៤ ម៉ោងចុងក្រោយ
        yesterday = datetime.now(pytz.utc) - timedelta(hours=24)
        docs = db.collection('posted_articles')\
                .where('created_at', '>=', yesterday)\
                .order_by('created_at', direction=firestore.Query.DESCENDING)\
                .limit(limit)\
                .stream()
        
        for doc in docs:
            data = doc.to_dict()
            if 'original_title' in data:
                titles.append(data['original_title'])
        return titles
    except Exception as e:
        logging.warning(f"⚠️ Failed to fetch recent titles: {e}")
        return []

def get_current_slot() -> Dict:
    """កំណត់ម៉ោងបង្ហោះកុំអោយ Spam (Smart Schedule)"""
    now = datetime.now(ICT)
    h = now.hour
    
    # ម៉ោងសំខាន់ៗ (Prime Time) អោយ Post ច្រើនបន្តិច
    if 6 <= h < 9:       return {"name": "Morning Update", "delay": 60}
    if 11 <= h < 14:     return {"name": "Lunch Break",    "delay": 45}
    if 17 <= h < 21:     return {"name": "Evening News",   "delay": 40}
    
    # ម៉ោងធម្មតា (Normal)
    if 9 <= h < 17:      return {"name": "Work Hours",     "delay": 120}
    
    # ម៉ោងយប់ជ្រៅ (Night) - Post តិចបំផុត
    return                       {"name": "Night Mode",     "delay": 600}

# =========================== CORE FUNCTIONS ===========================

async def fetch_rss(url: str) -> Optional[feedparser.FeedParserDict]:
    headers = {"User-Agent": "CambodiaNewsBot/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    return feedparser.parse(await r.text())
    except:
        pass
    return None

async def download_image(url: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) <= 5 * 1024 * 1024: # Max 5MB
                        return data
    except:
        pass
    return None

async def translate_content(article: Dict, platform: str) -> Dict:
    """ប្រើ Gemini ដើម្បីសង្ខេប និងបកប្រែអោយខ្លឹម"""
    lang = "KHMER" if platform == "telegram" else "ENGLISH"
    context = "Cambodian audience" if platform == "telegram" else "International audience interested in Cambodia"
    
    prompt = (
        f"Act as a professional journalist. Summarize this news for {platform} ({lang}).\n"
        f"Context: {context}\n"
        f"Original Title: {article['title']}\n"
        f"Original Content: {article['summary'][:2500]}\n\n"
        f"Requirements:\n"
        f"1. Title must be catchy, informative, NO Clickbait.\n"
        f"2. Body must be concise key points.\n"
        f"3. Return JSON ONLY: {{'title': '...', 'body': '...'}}"
    )

    for _ in range(2):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
            data = json.loads(text)
            
            key_title = f"title_{platform}"
            key_body = f"body_{platform}"
            
            article[key_title] = data.get("title", article['title'])
            article[key_body] = data.get("body", article['summary'])
            return article
        except:
            await asyncio.sleep(2)

    # Fallback
    key_title = f"title_{platform}"
    key_body = f"body_{platform}"
    article[key_title] = article['title']
    article[key_body] = article['summary'][:500] + "..."
    return article

# =========================== POSTING LOGIC ===========================

async def post_to_telegram(article: Dict, category: str) -> bool:
    if not telegram_bot: return False
    
    flag = {"cambodia": "🇰🇭", "international": "🌍", "regional": "🌏"}.get(category, "📰")
    is_breaking = any(k in article['title'].lower() for k in BREAKING_KEYWORDS)
    header_emoji = "🚨 BREAKING" if is_breaking else flag
    
    caption = (
        f"{header_emoji} <b>{article['title_telegram']}</b>\n\n"
        f"{article['body_telegram']}\n\n"
        f"─────────────────\n"
        f"ប្រភព: {article['source']}\n"
        f"🗓 {datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានលម្អិត 🔗", url=article["link"])],
        [InlineKeyboardButton("Join Channel 📢", url=TELEGRAM_CHANNEL_LINK)]
    ])

    try:
        # Priority: Image -> Text
        if article.get("image_url"):
            await telegram_bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=article["image_url"],
                caption=caption[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=buttons
            )
        else:
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=buttons
            )
        return True
    except Exception as e:
        logging.error(f"Telegram Error: {e}")
        return False

async def post_to_twitter(article: Dict, category: str) -> bool:
    if not twitter_client: return False
    # Only post Cambodia-related news to Twitter
    if category != "cambodia": return False
    
    is_breaking = any(k in article['title'].lower() for k in BREAKING_KEYWORDS)
    emoji = "🚨" if is_breaking else "🇰🇭"
    
    text = f"{emoji} {article['title_twitter']}\n\n{article['body_twitter'][:180]}...\n\n#Cambodia #News\n🔗 {article['link']}"
    
    try:
        media_id = None
        if article.get("image_url"):
            img_bytes = await download_image(article["image_url"])
            if img_bytes:
                file_obj = io.BytesIO(img_bytes)
                file_obj.name = "image.jpg"
                media = await asyncio.to_thread(twitter_api_v1.media_upload, filename="news.jpg", file=file_obj)
                media_id = media.media_id
        
        if media_id:
            await asyncio.to_thread(twitter_client.create_tweet, text=text, media_ids=[media_id])
        else:
            await asyncio.to_thread(twitter_client.create_tweet, text=text)
        return True
    except Exception as e:
        logging.error(f"Twitter Error: {e}")
        return False

async def save_to_db(aid: str, title: str, category: str, source: str, tg_posted: bool, tw_posted: bool):
    """រក្សាទុកក្នុង Firebase ដើម្បីកុំអោយស្ទួននៅថ្ងៃក្រោយ"""
    if not db: return
    try:
        db.collection('posted_articles').document(aid).set({
            'article_id': aid,
            'original_title': title, # សំខាន់សម្រាប់ Semantic Check
            'category': category,
            'source': source,
            'telegram_posted': tg_posted,
            'twitter_posted': tw_posted,
            'created_at': firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logging.error(f"DB Error: {e}")

# =========================== MAIN WORKER ===========================

async def worker():
    logging.info("🚀 Bot v5.0 Started - Strict Anti-Spam Mode")
    
    while True:
        try:
            stats.reset_if_new_day()
            slot = get_current_slot()
            
            # 1. Load Recent Titles (សម្រាប់ផ្ទៀងផ្ទាត់កុំអោយស្ទួន)
            recent_titles = await get_recent_titles(limit=40)
            
            # 2. Iterate Categories (Priority: Cambodia First)
            categories = ["cambodia", "international", "regional"]
            
            for cat in categories:
                sources = NEWS_SOURCES.get(cat, [])
                for src in sources:
                    
                    # Fetch RSS
                    feed = await fetch_rss(src["rss"])
                    if not feed or not feed.entries: continue
                    
                    entry = feed.entries[0] # Check latest only
                    
                    # --- FILTERS (កន្លែងសំខាន់) ---
                    
                    # Filter 1: Spam Check
                    if is_spam(entry.title) or is_spam(entry.get('summary', '')):
                        logging.info(f"🗑 Blocked Spam: {entry.title}")
                        stats.spam_blocked += 1
                        continue

                    # Filter 2: Exact Duplicate Check (ID)
                    aid = hashlib.md5(f"{entry.title}{entry.link}".encode()).hexdigest()
                    doc_ref = db.collection('posted_articles').document(aid) if db else None
                    if doc_ref and doc_ref.get().exists:
                        continue # Skip if exact match exists

                    # Filter 3: Semantic Duplicate Check (ខ្លឹមសារដូចគ្នា តែវេបសាយផ្សេង)
                    if check_similarity(entry.title, recent_titles):
                        stats.duplicates_blocked += 1
                        continue

                    # --- PROCESSING ---
                    logging.info(f"⚡ Processing: {entry.title} ({src['name']})")
                    
                    # Prepare Article Data
                    img_url = None
                    if hasattr(entry, 'media_content'): img_url = entry.media_content[0]['url']
                    elif entry.get('description'):
                        soup = BeautifulSoup(entry.description, 'html.parser')
                        img = soup.find('img')
                        if img: img_url = urljoin(src['url'], img.get('src'))

                    article = {
                        "title": entry.title,
                        "link": entry.link,
                        "summary": BeautifulSoup(entry.get('summary', ''), 'html.parser').get_text()[:1500],
                        "source": src["name"],
                        "image_url": img_url
                    }

                    # Translate & Post
                    tg_success = False
                    tw_success = False

                    # Telegram (All Categories)
                    if ENABLE_TELEGRAM:
                        article = await translate_content(article, "telegram")
                        if await post_to_telegram(article, cat):
                            tg_success = True
                            stats.telegram_posts += 1
                    
                    # Twitter (Cambodia Only)
                    if ENABLE_TWITTER and cat == "cambodia":
                        article = await translate_content(article, "twitter")
                        if await post_to_twitter(article, cat):
                            tw_success = True
                            stats.twitter_posts += 1
                    
                    # Save if at least one posted
                    if tg_success or tw_success:
                        await save_to_db(aid, entry.title, cat, src["name"], tg_success, tw_success)
                        logging.info(f"✅ Posted Successfully! Sleeping {slot['delay']}s")
                        
                        # Stop processing other sources for a while to avoid flood
                        await asyncio.sleep(slot['delay']) 
                        break # Break inner loop to rotate categories
                
                # Small pause between categories
                await asyncio.sleep(5)

        except Exception as e:
            logging.error(f"Worker Loop Error: {e}")
            await asyncio.sleep(60)

# =========================== SERVER & START ===========================

async def self_ping():
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{RENDER_SERVICE_URL}/health") as r: pass
        except: pass

async def health(request):
    return web.json_response({
        "status": "active",
        "stats": {
            "telegram": stats.telegram_posts,
            "twitter": stats.twitter_posts,
            "spam_blocked": stats.spam_blocked,
            "duplicates_blocked": stats.duplicates_blocked
        }
    })

async def main():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    await asyncio.gather(worker(), self_ping())

if __name__ == "__main__":
    asyncio.run(main())