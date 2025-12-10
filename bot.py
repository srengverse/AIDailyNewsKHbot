# bot.py – Khmer News Bot 2026 (Professional Edition)
# Stack: Python + Aiogram/Telegram + Gemini AI + Firebase Firestore
# Focus: Quality, Reliability, Professionalism

import os
import asyncio
import json
import hashlib
import re
import logging
import html
import traceback
from datetime import datetime, timedelta
from urllib.parse import urljoin

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

import firebase_admin
from firebase_admin import credentials, firestore

# =========================== CONFIGURATION ===========================
load_dotenv()

# --- Credentials ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
CHANNEL_LINK = "https://t.me/AIDailyNewsKH" # ដាក់ Link Channel របស់អ្នក
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "firebase_key.json")

# --- AI Settings ---
GEMINI_MODEL = "gemini-2.5-flash" # លឿននិងសន្សំសំចៃបំផុតសម្រាប់ News
ICT = pytz.timezone('Asia/Phnom_Penh')

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# =========================== FIREBASE SETUP ===========================
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase Connected Successfully")
except Exception as e:
    logging.critical(f"❌ Firebase Connection Failed: {e}")
    exit(1)

# =========================== AI CONFIGURATION ===========================
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY missing!")
    exit(1)

# =========================== NEWS SOURCES (Professional List) ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "Cambodianess",   "rss": "https://cambodianess.com/rss",                  "url": "https://cambodianess.com"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
    ],
    "international": [
        {"name": "BBC World",      "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",    "url": "https://www.bbc.com"},
        {"name": "CNA Asia",       "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com"},
        {"name": "Reuters World",  "rss": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best", "url": "https://www.reuters.com"},
    ]
}

# =========================== CORE LOGIC ===========================

def get_schedule():
    """Smart Schedule: កំណត់ល្បឿន Post តាមម៉ោងជាក់ស្តែងនៅកម្ពុជា"""
    now = datetime.now(ICT)
    h = now.hour

    # ម៉ោង 12:00 យប់ - 5:00 ព្រឹក (សម្រាក)
    if 0 <= h < 5:
        return {"mode": "Sleep", "interval": 1800, "max_per_cycle": 1} 
    
    # ម៉ោង 6:00 ព្រឹក - 8:30 ព្រឹក (Morning Brief)
    elif 5 <= h < 9:
        return {"mode": "Morning Rush", "interval": 300, "max_per_cycle": 3}
    
    # ម៉ោង 11:30 - 13:30 (Lunch Break)
    elif 11 <= h < 14:
        return {"mode": "Lunch Update", "interval": 300, "max_per_cycle": 3}
    
    # ម៉ោង 17:00 - 20:00 (Evening Prime)
    elif 17 <= h < 20:
        return {"mode": "Prime Time", "interval": 200, "max_per_cycle": 4}
    
    # ម៉ោងធម្មតា (Normal Work Hours)
    else:
        return {"mode": "Regular", "interval": 600, "max_per_cycle": 2}

# --- Database Functions (Firebase) ---
async def is_article_posted(article_id: str) -> bool:
    """ពិនិត្យក្នុង Firebase ថាព័ត៌មាននេះធ្លាប់ Post ឬនៅ"""
    try:
        # ប្រើ asyncio.to_thread ព្រោះ firebase sdk ជា sync
        doc = await asyncio.to_thread(lambda: db.collection('posted_articles').document(article_id).get())
        return doc.exists
    except Exception as e:
        logging.error(f"DB Check Error: {e}")
        return True # សុខចិត្តមិន Post បើ DB error ដើម្បីការពារ Spam

async def record_post(article_id: str, data: dict):
    """រក្សាទុកប្រវត្តិ Post ចូល Firebase"""
    try:
        payload = {
            "title": data['title'],
            "source": data['source'],
            "posted_at": firestore.SERVER_TIMESTAMP,
            "category": data.get('category', 'general')
        }
        await asyncio.to_thread(lambda: db.collection('posted_articles').document(article_id).set(payload))
    except Exception as e:
        logging.error(f"DB Save Error: {e}")

# --- AI & Content ---
async def process_content_with_ai(article: dict) -> dict:
    """ប្រើ Gemini ដើម្បីសង្ខេប និងបកប្រែជាភាសាព័ត៌មានផ្លូវការ"""
    
    # Prompt ផ្តោតលើគុណភាពនិងវិជ្ជាជីវៈ
    prompt = f"""
    Role: You are a professional Chief Editor for a top Cambodian news agency.
    Task: Summarize and translate the following news into formal, engaging, and neutral Khmer (Cambodian).
    
    Source Title: {article['title']}
    Source Content: {article['summary']}
    
    Guidelines:
    1. Tone: Professional, Journalistic, Objectivity (ភាសាព័ត៌មានផ្លូវការ).
    2. Structure: 
       - Headline: Catchy but accurate (No clickbait).
       - Body: 2-3 short paragraphs summarizing the key facts (Who, What, Where, When, Why).
    3. Output: JSON format ONLY.
    
    Schema:
    {{
        "title_kh": "Headline in Khmer",
        "body_kh": "Content body in Khmer (do not use markdown bolding inside body)"
    }}
    """
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        # ប្រើ response_mime_type ដើម្បីធានាថាចេញ JSON ១០០%
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        data = json.loads(response.text)
        
        # Clean Data & Escape HTML
        article["title_kh"] = data.get("title_kh", article["title"]).strip()
        article["body_kh"] = data.get("body_kh", article["summary"]).strip()
        
        return article

    except Exception as e:
        logging.error(f"AI Error: {e}")
        return None # បើ AI ខូច មិន Post ទេ ដើម្បីរក្សាគុណភាព

# --- Helper Functions ---
def get_article_hash(link: str) -> str:
    return hashlib.md5(link.encode()).hexdigest()

def extract_image(entry, base_url):
    # Logic ចាប់រូបភាពដែលល្អជាងមុន
    if 'media_content' in entry and entry.media_content:
        return entry.media_content[0]['url']
    if 'media_thumbnail' in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0]['url']
    
    soup = BeautifulSoup(entry.get('summary', '') + entry.get('description', ''), 'html.parser')
    img = soup.find('img')
    if img and img.get('src'):
        return urljoin(base_url, img.get('src'))
    return None

# --- Telegram Posting ---
async def send_to_telegram(bot: Bot, article: dict) -> bool:
    # Escape HTML ដើម្បីការពារ Error (សំខាន់ណាស់!)
    title_safe = html.escape(article['title_kh'])
    body_safe = html.escape(article['body_kh'])
    source_safe = html.escape(article['source'])
    
    # Design Template
    flag = "🇰🇭" if article['category'] == 'cambodia' else "🌍"
    caption = (
        f"{flag} <b>{title_safe}</b>\n\n"
        f"{body_safe}\n\n"
        f"🔗 <a href='{article['link']}'>អានលម្អិតនៅទីនេះ</a>\n"
        f"🗞 <i>ប្រភព: {source_safe}</i>"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("ចែករំលែក / Share ↗️", url=f"https://t.me/share/url?url={article['link']}")]
    ])

    try:
        # សាកល្បងផ្ញើរូបភាពជាមុន
        if article['image_url']:
            await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=article['image_url'],
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=buttons
            )
        else:
            # បើគ្មានរូប ផ្ញើអក្សរ
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
        return True
    except TelegramError as e:
        logging.error(f"Telegram Error: {e}")
        return False

# =========================== MAIN WORKER ===========================
async def news_worker():
    logging.info("🚀 Khmer News Bot Professional Started...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    while True:
        schedule = get_schedule()
        logging.info(f"🕒 Status: {schedule['mode']} | Interval: {schedule['interval']}s")
        
        posts_in_cycle = 0
        
        # Loop តាម Category
        for category, sources in NEWS_SOURCES.items():
            if posts_in_cycle >= schedule['max_per_cycle']: break
            
            for source in sources:
                if posts_in_cycle >= schedule['max_per_cycle']: break
                
                try:
                    feed = feedparser.parse(source['rss'])
                    if not feed.entries: continue
                    
                    # យកព័ត៌មានថ្មីបំផុត ១ មកពិនិត្យ
                    entry = feed.entries[0]
                    aid = get_article_hash(entry.link)
                    
                    # 1. Check DB (Deduplication)
                    if await is_article_posted(aid):
                        continue
                    
                    # 2. Prepare Data
                    raw_article = {
                        "title": entry.title,
                        "link": entry.link,
                        "summary": BeautifulSoup(entry.get('summary', '') or entry.get('description', ''), "html.parser").get_text()[:1500],
                        "image_url": extract_image(entry, source['url']),
                        "source": source['name'],
                        "category": category
                    }
                    
                    # 3. AI Processing (Translation & Summarization)
                    logging.info(f"🤖 Processing: {raw_article['title'][:30]}...")
                    final_article = await process_content_with_ai(raw_article)
                    
                    if final_article:
                        # 4. Send to Telegram
                        sent = await send_to_telegram(bot, final_article)
                        
                        if sent:
                            # 5. Save to DB
                            await record_post(aid, final_article)
                            logging.info(f"✅ Posted: {final_article['title_kh']}")
                            posts_in_cycle += 1
                            await asyncio.sleep(10) # Delay រវាង Post នីមួយៗ
                        else:
                            # បើ Post មិនចេញ (អាចមកពី Image error) ដាក់ចូល DB ដែរដើម្បីកុំឲ្យជាប់គាំង
                            await record_post(aid, final_article)
                    
                except Exception as e:
                    logging.error(f"Source Error ({source['name']}): {e}")
                    continue

        # ដេកតាមកាលវិភាគ
        await asyncio.sleep(schedule['interval'])

# =========================== HEALTH CHECK (Keep Alive) ===========================
async def health(request):
    return web.Response(text="Bot is Running - Professional Mode")

async def start_server():
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await site.start()

# =========================== ENTRY POINT ===========================
async def main():
    if not TELEGRAM_BOT_TOKEN or not FIREBASE_CRED_PATH:
        logging.error("❌ Environment variables missing!")
        return
        
    await asyncio.gather(
        start_server(),
        news_worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass