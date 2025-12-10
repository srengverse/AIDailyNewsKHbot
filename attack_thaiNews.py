"""
AI Daily News KH v19.0 - Lightweight Edition
============================================
🚀 STATUS: PRODUCTION READY (No Video/Voice Dependencies)
-------------------------------------------------
1. 🧠 Intelligence: Radar (Filter), Chat (RAG), Sentiment, Time Machine
2. 🎨 Visuals: Auto-Poster (Design), Deep Image Extraction
3. 🛠️ Tools: Admin Broadcast, Daily Briefing (Text), Scheduling
4. 📡 Posting: Telegram (Enterprise Format), Twitter (X)
"""

import os
import asyncio
import json
import hashlib
import re
import logging
import ssl
import io
import textwrap
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, field

# Third-party libraries
import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import tweepy
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

# System
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash-exp"
ICT = pytz.timezone('Asia/Phnom_Penh')
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_LINK = "https://t.me/AIDailyNewsKH"

# Twitter
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_LINK = "https://x.com/AIDailyNewskh"
WEBSITE_LINK = os.getenv("WEBSITE_LINK", "")

# Visual Settings
ENABLE_POSTER = True

# Limits
CONTENT_QUALITY_THRESHOLD = 75
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
    user_queries_answered: int = 0
    articles_processed: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(ICT).date())

    def reset_if_new_day(self):
        today = datetime.now(ICT).date()
        if today > self.last_reset:
            logger.info(f"\n📊 DAILY REPORT: TG={self.telegram_posts}, TW={self.twitter_posts}\n")
            self.__init__()

stats = SystemStatistics()

# ═══════════════════════════════════════════════════════════════════════════
# 3. INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

genai.configure(api_key=GEMINI_API_KEY)
tg_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
global_bot = tg_app.bot 
scheduler = AsyncIOScheduler(timezone=ICT)

twitter_client = None
if TWITTER_API_KEY:
    try:
        twitter_client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET, access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET, wait_on_rate_limit=False)
        auth = tweepy.OAuth1UserHandler(TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        logger.info("✅ Twitter Connected")
    except: pass

db = None
try:
    if os.getenv("FIREBASE_CREDENTIALS"):
        try: cred_dict = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
        except: cred_dict = os.getenv("FIREBASE_CREDENTIALS")
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps: firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("✅ Firebase Connected")
except: logger.warning("⚠️ Firebase Not Connected (Running in Memory Mode)")

# ═══════════════════════════════════════════════════════════════════════════
# 4. VISUAL ENGINE (FONTS & POSTERS)
# ═══════════════════════════════════════════════════════════════════════════

FONT_URL = "https://github.com/google/fonts/raw/main/ofl/battambang/Battambang-Bold.ttf"
FONT_PATH = "Battambang-Bold.ttf"

async def download_font():
    if not os.path.exists(FONT_PATH):
        async with aiohttp.ClientSession() as session:
            async with session.get(FONT_URL) as resp:
                if resp.status == 200:
                    with open(FONT_PATH, 'wb') as f: f.write(await resp.read())

async def generate_poster(image_bytes: bytes, headline: str, is_breaking: bool) -> bytes:
    if not ENABLE_POSTER or not image_bytes: return image_bytes
    try:
        base_img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        base_img = base_img.resize((1200, 800), Image.Resampling.LANCZOS)
        
        overlay = Image.new('RGBA', base_img.size, (0,0,0,0))
        draw = ImageDraw.Draw(overlay)
        for y in range(400, 800):
            alpha = int(255 * ((y - 400) / 400))
            draw.line([(0, y), (1200, y)], fill=(0, 0, 0, int(alpha * 0.9)))
            
        out = Image.alpha_composite(base_img, overlay)
        draw = ImageDraw.Draw(out)
        
        try: font = ImageFont.truetype(FONT_PATH, 50)
        except: font = ImageFont.load_default()

        wrapped = textwrap.wrap(headline, width=40)
        text_y = 800 - (len(wrapped) * 65) - 100
        
        color = (220, 0, 0) if is_breaking else (0, 102, 204)
        label = "BREAKING NEWS" if is_breaking else "DAILY NEWS KH"
        
        draw.rectangle([40, text_y - 60, 400, text_y - 10], fill=color)
        draw.text((60, text_y - 55), label, font=font, fill="white")

        for line in wrapped:
            draw.text((43, text_y + 3), line, font=font, fill="black")
            draw.text((40, text_y), line, font=font, fill="white")
            text_y += 65

        img_byte_arr = io.BytesIO()
        out.convert("RGB").save(img_byte_arr, format='JPEG', quality=95)
        return img_byte_arr.getvalue()
    except: return image_bytes

# ═══════════════════════════════════════════════════════════════════════════
# 5. CHAT & ADMIN
# ═══════════════════════════════════════════════════════════════════════════

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    context_text = "No recent news."
    if db:
        docs = db.collection('posted_articles').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(10).stream()
        context_text = "\n".join([f"- {d.to_dict().get('title')}" for d in docs])
    
    prompt = f"Role: News Bot. Question: '{user_text}'. News Context: {context_text}. Answer in Khmer."
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        await update.message.reply_text(resp.text)
        stats.user_queries_answered += 1
    except: pass

tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = " ".join(context.args)
    if msg: await context.bot.send_message(TELEGRAM_CHANNEL_ID, f"📢 **សេចក្តីជូនដំណឹង**\n\n{msg}", parse_mode=ParseMode.MARKDOWN)

tg_app.add_handler(CommandHandler("broadcast", broadcast_command))

# ═══════════════════════════════════════════════════════════════════════════
# 6. DAILY JOBS
# ═══════════════════════════════════════════════════════════════════════════

async def daily_briefing_job():
    if not db: return
    logger.info("📅 Generating Daily Briefing (Text Only)...")
    try:
        start_of_day = datetime.now(ICT).replace(hour=0, minute=0, second=0)
        docs = db.collection('posted_articles').where('updated_at', '>=', start_of_day).stream()
        headlines = [f"- {d.to_dict().get('title', '')}" for d in docs]
        if not headlines: return

        news_list = "\n".join(headlines[:20])
        prompt = f"Create a 'Daily News Briefing' (Khmer) from: {news_list}. Output 5 bullet points."
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        summary_text = resp.text
        
        await global_bot.send_message(TELEGRAM_CHANNEL_ID, f"🌙 **សរុបព័ត៌មានប្រចាំថ្ងៃ**\n\n{summary_text}\n\n#DailyRecap", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Briefing Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# 7. NEWS LOGIC (RADAR + TIME MACHINE + TRANSLATOR)
# ═══════════════════════════════════════════════════════════════════════════

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

async def fetch_og_image(url):
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=10) as r:
                if r.status==200:
                    soup = BeautifulSoup(await r.text(), 'html.parser')
                    meta = soup.find("meta", property="og:image")
                    return meta["content"] if meta else None
    except: return None

async def download_image(url):
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=15) as r:
                return await r.read() if r.status==200 else None
    except: return None

def get_best_image(entry):
    try:
        if hasattr(entry, 'media_content'): return entry.media_content[0]['url']
        if hasattr(entry, 'media_thumbnail'): return entry.media_thumbnail[0]['url']
        soup = BeautifulSoup(entry.get('summary', '') or entry.get('description', ''), 'html.parser')
        img = soup.find('img')
        if img: return img.get('src')
    except: pass
    return None

async def find_related_news(title: str):
    if not db: return ""
    try:
        keywords = [w for w in title.split() if len(w) > 4][:2]
        if not keywords: return ""
        docs = db.collection('posted_articles').order_by('updated_at', direction=firestore.Query.DESCENDING).limit(20).stream()
        related = []
        for doc in docs:
            d = doc.to_dict()
            if d.get('title') != title and any(k.lower() in d.get('title', '').lower() for k in keywords):
                related.append(f"• {d.get('title')}")
                if len(related) >= 2: break
        return "\n📌 **ព័ត៌មានពាក់ព័ន្ធ:**\n" + "\n".join(related) if related else ""
    except: return ""

NEWS_SOURCES = {
    "cambodia": [
        {"name": "Khmer Times", "rss": "https://www.khmertimeskh.com/feed/", "priority": 10},
        {"name": "Thmey Thmey", "rss": "https://thmeythmey.com/feed", "priority": 10},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed", "priority": 8},
    ],
    "international": [
        {"name": "BBC World", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "priority": 10},
        {"name": "Reuters", "rss": "https://www.reutersagency.com/feed/", "priority": 10},
        {"name": "Bangkok Post", "rss": "https://www.bangkokpost.com/rss/data/topstories.xml", "priority": 10},
    ],
    "thailand": [
        # ប្រភពអង់គ្លេសផ្លូវការពីថៃ (ងាយស្រួលឲ្យ AI បកប្រែជាងភាសាថៃសុទ្ធ)
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed/topstories", "url": "https://www.bangkokpost.com"},
        {"name": "Thai PBS World", "rss": "https://world.thaipbs.or.th/feed",                "url": "https://world.thaipbs.or.th"},
        {"name": "Khaosod English","rss": "https://www.khaosodenglish.com/feed",             "url": "https://www.khaosodenglish.com"},
    ]
}

INTL_KEYWORDS = ["cambodia", "khmer", "thailand", "thai", "border", "military", "hun manet", "hun sen"]
BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "គ្រោះថ្នាក់", "ផ្ទុះ", "ស្លាប់", "dead", "crisis", "attack", "fire"]

async def translate_ai(article, platform):
    lang = "Khmer" if platform == "telegram" else "English"
    
    prompt = f"""You are a Senior News Editor for a top agency.
    Task: Summarize, Translate, and Analyze this news for {platform} ({lang}).
    
    Source Material:
    - Title: {article['title']}
    - Content: {article['summary'][:2000]}
    
    STRICT GUIDELINES:
    1. TRANSLATION: Formal, Neutral, Journalistic (No slang).
    2. ACCURACY: Focus on Who, What, Where, When, Why.
    3. ANALYSIS: Provide 1 short sentence explaining context/impact.
    4. SENTIMENT: Detect if the news is Happy, Sad, Warning, or Neutral.
    
    OUTPUT FORMAT (JSON ONLY):
    {{
        "title": "Formal Headline in {lang}",
        "body": "Concise summary in {lang} (approx 100-150 words)",
        "analysis": "One sentence context analysis in {lang}",
        "hashtags": "#Tag1 #Tag2 #Tag3 (in {lang} or English)",
        "sentiment": "Neutral/Happy/Sad/Warning",
        "poll_question": "A relevant Yes/No question for public opinion (or null if not applicable)"
    }}"""
    
    for _ in range(2):
        try:
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            return json.loads(re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M))
        except: await asyncio.sleep(1)
            
    return {"title": article['title'], "body": article['summary'], "analysis": "", "hashtags": "", "sentiment": "Neutral", "poll_question": None}

def get_sentiment_header(sentiment: str, is_breaking: bool, category: str):
    if category == 'international': return "🌏 **មតិអន្តរជាតិ**"
    if is_breaking: return "🚨 **BREAKING NEWS**"
    s = sentiment.lower()
    if "sad" in s or "tragedy" in s: return "🕯️ **ចូលរួមរំលែកទុក្ខ**"
    if "happy" in s or "celebrate" in s: return "🎉 **អបអរសាទរ**"
    if "warning" in s: return "⚠️ **ការដាស់តឿន**"
    return "🇰🇭 **ព័ត៌មានជាតិ**"

# ═══════════════════════════════════════════════════════════════════════════
# 9. POSTING MAIN LOGIC
# ═══════════════════════════════════════════════════════════════════════════

async def post_to_twitter_account(article, content, image_bytes):
    if not twitter_client: return False
    text = f"🇰🇭 {content['title']}\n\n{content['body'][:180]}...\n\n#Cambodia #News\n🔗 {article['link']}"
    try:
        mid = None
        if image_bytes:
            media = await asyncio.to_thread(twitter_client.v1.media_upload, filename="news.jpg", file=io.BytesIO(image_bytes))
            mid = media.media_id
        
        if mid: await asyncio.to_thread(twitter_client.create_tweet, text=text, media_ids=[mid])
        else: await asyncio.to_thread(twitter_client.create_tweet, text=text)
        stats.twitter_posts += 1
        return True
    except: return False

async def post_to_channels(article, content, related_context):
    if not global_bot: return
    
    header = get_sentiment_header(content.get('sentiment', ''), article['is_breaking'], article['category'])
    
    full_caption = (
        f"{header}\n\n"
        f"⭐ <b>{content['title']}</b>\n\n"
        f"{content['body']}\n\n"
        f"💡 <b>វិភាគ:</b> <i>{content.get('analysis', '')}</i>\n"
        f"{related_context}\n"
        f"{content.get('hashtags', '')}\n"
        f"{'─' * 20}\n"
        f"📰 {article['source']} | 🕐 {datetime.now(ICT):%H:%M}"
    )
    
    if len(full_caption) > 1024:
        full_caption = full_caption[:1020] + "..."
    
    buttons = [
        [InlineKeyboardButton("អានលម្អិត 🔗", url=article["link"])],
        [InlineKeyboardButton("Telegram 📢", url=TELEGRAM_LINK), InlineKeyboardButton("Twitter ✖️", url=TWITTER_LINK)]
    ]
    if WEBSITE_LINK: buttons[1].append(InlineKeyboardButton("Web 🌐", url=WEBSITE_LINK))
    
    image_bytes = article.get('image_bytes')
    poster_bytes = await generate_poster(image_bytes, content['title'], article['is_breaking'])
    
    tg_success = False
    try:
        if poster_bytes:
            await global_bot.send_photo(TELEGRAM_CHANNEL_ID, poster_bytes, caption=full_caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
            tg_success = True
        else:
            await global_bot.send_message(TELEGRAM_CHANNEL_ID, full_caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
            tg_success = True
            
        if tg_success:
            stats.telegram_posts += 1
            poll_q = content.get('poll_question')
            if poll_q and article['category'] == 'cambodia':
                await asyncio.sleep(3)
                await global_bot.send_poll(TELEGRAM_CHANNEL_ID, question=f"📊 {poll_q}", options=["យល់ស្រប", "មិនយល់ស្រប", "គ្មានយោបល់"], is_anonymous=True)
            
    except Exception as e: logger.error(f"TG Post Error: {e}")
        
    if tg_success and twitter_client and stats.twitter_posts < TWITTER_DAILY_LIMIT:
        await post_to_twitter_account(article, content, poster_bytes or image_bytes)

    return tg_success

# ═══════════════════════════════════════════════════════════════════════════
# 10. MAIN WORKER
# ═══════════════════════════════════════════════════════════════════════════

async def fetch_rss_safe(url):
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as s:
            async with s.get(url, timeout=20) as r: return feedparser.parse(await r.text()) if r.status == 200 else None
    except: return None

async def rss_worker():
    logger.info("🚀 v19.0 Lightweight Started...")
    await download_font()
    
    while True:
        stats.reset_if_new_day()
        for category, sources in NEWS_SOURCES.items():
            for src in sources:
                try:
                    feed = await fetch_rss_safe(src['rss'])
                    if not feed or not feed.entries: continue
                    entry = feed.entries[0]
                    stats.articles_processed += 1
                    
                    aid = hashlib.md5(entry.link.encode()).hexdigest()
                    if db:
                        if (await asyncio.to_thread(db.collection('posted_articles').document(aid).get)).exists: continue
                    
                    img_url = get_best_image(entry) or await fetch_og_image(entry.link)
                    article = {
                        "title": entry.title, "link": entry.link, "source": src['name'], "category": category,
                        "summary": BeautifulSoup(entry.summary, 'html.parser').get_text()[:2000],
                        "image_bytes": await download_image(img_url) if img_url else None,
                        "is_breaking": any(k in entry.title.lower() for k in BREAKING_KEYWORDS)
                    }
                    
                    if category == 'international':
                        if not any(k in (article['title']+article['summary']).lower() for k in INTL_KEYWORDS): continue

                    logger.info(f"✨ NEW: {entry.title[:30]}")
                    content = await translate_ai(article, "telegram")
                    related_context = await find_related_news(content['title'])
                    
                    if await post_to_channels(article, content, related_context):
                        if db: await asyncio.to_thread(db.collection('posted_articles').document(aid).set, {'title': entry.title, 'updated_at': firestore.SERVER_TIMESTAMP})
                    
                    await asyncio.sleep(60)
                except Exception as e: logger.error(f"Src Error: {e}")
            await asyncio.sleep(120)

async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot v19.0 Active"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    
    scheduler.add_job(daily_briefing_job, 'cron', hour=19, minute=0)
    scheduler.start()
    
    asyncio.create_task(rss_worker())
    
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())