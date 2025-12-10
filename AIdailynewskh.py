# bot_hybrid.py – The Ultimate Khmer News Bot (Premium Edition)
# មុខងារ: AI Analysis + Premium Poster Generator + Firebase + Zero Error Logic

import os
import asyncio
import json
import hashlib
import logging
import html
import io
import traceback
from datetime import datetime
from urllib.parse import urljoin

# Third-party Libraries
import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import firebase_admin
from firebase_admin import credentials, firestore

# =========================== ⚙️ CONFIGURATION ===========================
load_dotenv()

# --- API Keys & IDs ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
CHANNEL_LINK = "https://t.me/AIDailyNewsKH"  # ដាក់ Link Channel របស់អ្នក
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "firebase_key.json")

# --- Settings ---
GEMINI_MODEL = "gemini-2.5-flash" 
ICT = pytz.timezone('Asia/Phnom_Penh')
FONT_PATH = "KhmerOS.ttf" # ⚠️ ត្រូវប្រាកដថាមាន File នេះ

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# =========================== 🔥 FIREBASE INIT ===========================
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase Connected Successfully")
except Exception as e:
    logging.critical(f"❌ Firebase Connection Failed: {e}")
    exit(1)

# =========================== 🤖 AI INIT ===========================
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logging.critical("❌ GEMINI_API_KEY Missing!")
    exit(1)

# =========================== 📰 NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
        {"name": "Cambodianess",   "rss": "https://cambodianess.com/rss",                  "url": "https://cambodianess.com"},
    ],
    "thailand": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed/topstories", "url": "https://www.bangkokpost.com"},
        {"name": "Thai PBS World", "rss": "https://world.thaipbs.or.th/feed",                "url": "https://world.thaipbs.or.th"},
        {"name": "Khaosod English","rss": "https://www.khaosodenglish.com/feed",             "url": "https://www.khaosodenglish.com"},
    ]
}

# =========================== 🎨 PREMIUM VISUAL ENGINE ===========================

async def download_image_bytes(url):
    """Download រូបភាពពី Internet ដោយសុវត្ថិភាព"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logging.warning(f"⚠️ Image Download Failed: {e}")
    return None

async def generate_poster(image_bytes, title, source_name, is_breaking=False):
    """
    បង្កើត Poster ដ៏ស្រស់ស្អាត (Premium Design)
    """
    if not image_bytes: return None
    
    try:
        # 1. Setup Canvas & Smart Crop (1200x800)
        target_size = (1200, 800)
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except:
            return None # បើរូបខូច ត្រឡប់ទៅផុសអក្សរវិញ

        # Calculate resize ratio to fill
        ratio = max(target_size[0] / img.width, target_size[1] / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Center Crop Logic
        left = (img.width - target_size[0]) / 2
        top = (img.height - target_size[1]) / 2
        img = img.crop((left, top, left + target_size[0], top + target_size[1]))
        
        # 2. Cinematic Darkening (ធ្វើឲ្យរូបងងឹតបន្តិចដើម្បីឃើញអក្សរច្បាស់)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.85) 
        
        # 3. Gradient Overlay (ស្រមោលខ្មៅពីក្រោមឡើងលើ)
        overlay = Image.new('RGBA', img.size, (0,0,0,0))
        draw = ImageDraw.Draw(overlay)
        
        gradient_height = 500
        start_y = target_size[1] - gradient_height
        for y in range(start_y, target_size[1]):
            # Alpha កើនឡើងបន្តិចម្តងៗ
            alpha = int(255 * ((y - start_y) / gradient_height)**1.2)
            draw.line([(0, y), (target_size[0], y)], fill=(5, 5, 10, alpha))
            
        out = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(out)
        
        # 4. Typography (ផ្ទុក Font)
        try:
            font_title = ImageFont.truetype(FONT_PATH, 50) 
            font_meta = ImageFont.truetype(FONT_PATH, 28)
            font_badge = ImageFont.truetype(FONT_PATH, 24)
        except OSError:
            logging.warning("⚠️ Font not found! Using default.")
            font_title = ImageFont.load_default()
            font_meta = ImageFont.load_default()
            font_badge = ImageFont.load_default()

        # 5. Draw "News Badge" (ស្លាកសញ្ញា)
        badge_text = "BREAKING NEWS" if is_breaking else "AI DAILY UPDATE"
        badge_color = (220, 20, 60) if is_breaking else (0, 102, 204) # ក្រហម ឬ ខៀវ
        
        badge_x, badge_y = 50, 530
        badge_w = 230 if is_breaking else 220
        badge_h = 40
        
        # គូសប្រអប់ Badge
        draw.rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], fill=badge_color)
        draw.text((badge_x + 15, badge_y + 5), badge_text, font=font_badge, fill="white")

        # 6. Draw Title (Smart Wrapping)
        text_x = 50
        text_y = 590
        max_chars_per_line = 38
        
        lines = []
        words = title.split()
        current_line = ""
        
        # Logic កាត់អក្សរ
        if len(words) == 1 and len(title) > max_chars_per_line:
             for i in range(0, len(title), max_chars_per_line):
                 lines.append(title[i:i+max_chars_per_line])
        else:
            for word in words:
                if len(current_line + word) <= max_chars_per_line:
                    current_line += word + " "
                else:
                    lines.append(current_line)
                    current_line = word + " "
            lines.append(current_line)

        # បង្ហាញអក្សរ (Shadow + Text)
        for line in lines[:3]: # យកតែ 3 ជួរប៉ុណ្ណោះ
            draw.text((text_x + 2, text_y + 2), line, font=font_title, fill=(0,0,0)) # Shadow
            draw.text((text_x, text_y), line, font=font_title, fill="white") # Text
            text_y += 70

        # 7. Footer (Source & Time)
        footer_text = f"{source_name} • {datetime.now(ICT).strftime('%d %b %Y, %H:%M')}"
        # បន្ទាត់លឿងតុបតែង
        draw.rectangle([text_x, text_y + 20, text_x + 5, text_y + 50], fill=(255, 204, 0))
        draw.text((text_x + 20, text_y + 22), footer_text, font=font_meta, fill=(220, 220, 220))

        # 8. Export to Bytes
        img_byte_arr = io.BytesIO()
        out.convert("RGB").save(img_byte_arr, format='JPEG', quality=95)
        return img_byte_arr.getvalue()

    except Exception as e:
        logging.error(f"❌ Poster Gen Error: {e}")
        return None # បើមានបញ្ហា ឲ្យត្រឡប់ None (ដើម្បី Post អក្សរជំនួស)

# =========================== 🧠 AI PROCESSING ===========================

async def process_with_ai(article: dict) -> dict:
    """ប្រើ Gemini ដើម្បីវិភាគ និងសង្ខេប"""
    country_context = "Cambodia" if article['category'] == 'cambodia' else "Thailand"
    
    prompt = f"""
    Role: Professional News Editor.
    Task: Process this news for a Cambodian audience.
    
    Source Title: {article['title']} (from {country_context})
    Content Summary: {article['summary']}
    
    Guidelines:
    1. Title: Formal Khmer headline (No clickbait).
    2. Body: Summary in standard Khmer (3-4 sentences, informative).
    3. Analysis: One sentence explaining WHY this matters.
    4. Sentiment: Choose one [Neutral, Positive, Negative, Warning].
    
    Output JSON ONLY:
    {{
        "title_kh": "...", 
        "body_kh": "...",
        "analysis": "...",
        "sentiment": "Neutral"
    }}
    """
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(
            model.generate_content, 
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(resp.text)
        
        # Update Article Data
        article["title_kh"] = data.get("title_kh", article["title"]).strip()
        article["body_kh"] = data.get("body_kh", article["summary"]).strip()
        article["analysis"] = data.get("analysis", "")
        article["sentiment"] = data.get("sentiment", "Neutral")
        
        return article
    except Exception as e:
        logging.error(f"❌ AI Error: {e}")
        return None

# =========================== 📨 TELEGRAM POSTING ===========================

async def post_telegram(bot: Bot, article: dict) -> bool:
    # 1. HTML Safety (ការពារ Error)
    title = html.escape(article['title_kh'])
    body = html.escape(article['body_kh'])
    analysis = html.escape(article['analysis'])
    src = html.escape(article['source'])
    link = article['link']
    
    # 2. Status & Icons
    flag = "🇰🇭" if article['category'] == 'cambodia' else "🇹🇭"
    sent_map = {"Positive": "🎉", "Negative": "😔", "Warning": "⚠️", "Neutral": "📰"}
    emoji = sent_map.get(article.get('sentiment'), "📰")
    
    # 3. Caption Design
    timestamp = datetime.now(ICT).strftime('%d/%m/%Y • %H:%M')
    caption = (
        f"{flag} {emoji} <b>{title}</b>\n\n"
        f"{body}\n\n"
        f"💡 <i>{analysis}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {src}\n"
        f"{timestamp}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ / Read More 🔗", url=link)],
        [InlineKeyboardButton("Join Channel 📢", url=CHANNEL_LINK)]
    ])

    sent_success = False
    
    # 4. Image Posting Logic (Poster -> Raw -> Text)
    if article['image_url']:
        try:
            logging.info("🖼️ Generating Poster...")
            # A. Download Raw
            raw_img = await download_image_bytes(article['image_url'])
            
            # B. Generate Poster
            final_img = None
            if raw_img:
                final_img = await generate_poster(
                    raw_img, 
                    article['title_kh'], 
                    article['source'], 
                    is_breaking=(article['sentiment'] == 'Warning')
                )
            
            # C. Send Photo (Poster ឬ Raw)
            img_to_send = final_img if final_img else raw_img
            
            if img_to_send:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=img_to_send,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=buttons
                )
                sent_success = True
                
        except TelegramError as e:
            logging.warning(f"⚠️ Photo Upload Failed ({e}). Switching to text mode.")
        except Exception as e:
            logging.error(f"⚠️ General Image Error: {e}")

    # 5. Fallback Text Mode (បើគ្មានរូប ឬ រូបខូច)
    if not sent_success:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            sent_success = True
        except TelegramError as e:
            logging.critical(f"❌ Text Post Failed: {e}")

    return sent_success

# =========================== 🛠️ UTILITIES ===========================

def get_schedule():
    """Smart Schedule តាមម៉ោងនៅកម្ពុជា"""
    now = datetime.now(ICT)
    h = now.hour
    if 0 <= h < 5:       return {"mode": "Sleep 🌙", "interval": 1800, "max": 1} 
    elif 5 <= h < 9:     return {"mode": "Morning Rush ☕", "interval": 300, "max": 4}
    elif 11 <= h < 14:   return {"mode": "Lunch Update 🍱", "interval": 300, "max": 4}
    elif 17 <= h < 21:   return {"mode": "Prime Time 📺", "interval": 200, "max": 5}
    else:                return {"mode": "Regular 🕒", "interval": 600, "max": 2}

async def is_posted(aid: str) -> bool:
    try:
        doc = await asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).get())
        return doc.exists
    except: return True 

async def save_post(aid: str, data: dict):
    try:
        payload = {
            "title": data['title'],
            "posted_at": firestore.SERVER_TIMESTAMP,
            "category": data['category']
        }
        await asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).set(payload))
    except Exception as e: logging.error(f"DB Error: {e}")

def get_hash(s): return hashlib.md5(s.encode()).hexdigest()

def get_img(entry, base):
    try:
        if 'media_content' in entry: return entry.media_content[0]['url']
        if 'media_thumbnail' in entry: return entry.media_thumbnail[0]['url']
        soup = BeautifulSoup(entry.get('summary','') + entry.get('description',''), 'html.parser')
        if img := soup.find('img'): return urljoin(base, img.get('src'))
    except: pass
    return None

# =========================== 🚀 MAIN LOOP ===========================

async def worker():
    logging.info("🚀 Hybrid News Bot Started (Premium Edition)")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    while True:
        sched = get_schedule()
        logging.info(f"🔍 Checking... [{sched['mode']}] (Next: {sched['interval']}s)")
        posted_count = 0
        
        for cat, sources in NEWS_SOURCES.items():
            if posted_count >= sched['max']: break
            
            for src in sources:
                if posted_count >= sched['max']: break
                try:
                    feed = feedparser.parse(src['rss'])
                    if not feed.entries: continue
                    
                    # ពិនិត្យ Article ដំបូង
                    e = feed.entries[0]
                    aid = get_hash(e.link)
                    
                    if await is_posted(aid): continue
                    
                    # រៀបចំទិន្នន័យ
                    raw = {
                        "title": e.title,
                        "link": e.link,
                        "summary": BeautifulSoup(e.get('summary','') or e.get('description',''), "html.parser").get_text()[:1500],
                        "image_url": get_img(e, src['url']),
                        "source": src['name'],
                        "category": cat
                    }
                    
                    # ដំណើរការ AI និង Post
                    logging.info(f"🤖 AI Processing: {raw['title'][:20]}...")
                    final = await process_with_ai(raw)
                    
                    if final:
                        success = await post_telegram(bot, final)
                        if success:
                            await save_post(aid, final)
                            logging.info(f"✅ Posted: {final['title_kh']}")
                            posted_count += 1
                            await asyncio.sleep(15) # Delay ខ្លះដើម្បីកុំឲ្យលឿនពេក
                        else:
                            # បើបរាជ័យ ក៏ Save ដែរដើម្បីកុំឲ្យជាប់គាំង Loop
                            await save_post(aid, final)

                except Exception as ex: 
                    logging.error(f"❌ Source Err ({src['name']}): {ex}")
        
        await asyncio.sleep(sched['interval'])

# =========================== 🌐 WEB SERVER ===========================
async def health(req): return web.Response(text="Bot Running - Premium")

async def main():
    app = web.Application()
    app.router.add_get('/', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    
    await asyncio.gather(
        site.start(),
        worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass