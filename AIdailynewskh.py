# bot_hybrid_fb_final.py – Production Ready Version
# Updates: Added JSON Cleaner, Font Check, and Enhanced Error Logs

import os
import asyncio
import json
import hashlib
import logging
import html
import io
import re  # បន្ថែម re សម្រាប់សម្អាត JSON
import sys
from datetime import datetime
from urllib.parse import urljoin

# Third-party
import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from aiohttp import web, FormData
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import firebase_admin
from firebase_admin import credentials, firestore

# =========================== ⚙️ CONFIGURATION ===========================
load_dotenv()

# --- Credentials ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "firebase_key.json")
FB_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
FB_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")

# --- Settings ---
CHANNEL_LINK = "[https://t.me/AIDailyNewsKH](https://t.me/AIDailyNewsKH)"
GEMINI_MODEL = "gemini-2.5-flash" 
ICT = pytz.timezone('Asia/Phnom_Penh')
FONT_PATH = "Battambang-Bold.ttf"

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# =========================== 🛡️ SYSTEM CHECKS ===========================
# 1. Check Font
if not os.path.exists(FONT_PATH):
    logging.warning(f"⚠️ WARNING: '{FONT_PATH}' not found! Text on posters will be broken (□□□).")
    logging.warning("👉 Please upload a Khmer .ttf file renamed to 'KhmerOS.ttf'.")

# 2. Check Keys
if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, FIREBASE_CRED_PATH]):
    logging.critical("❌ CRITICAL: Missing API Keys or Firebase Config.")
    sys.exit(1)

# =========================== 🔥 INITIALIZATION ===========================
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase Connected")
except Exception as e:
    logging.critical(f"❌ Firebase Error: {e}")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# =========================== 📰 SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "[https://thmeythmey.com/feed](https://thmeythmey.com/feed)",                   "url": "[https://thmeythmey.com](https://thmeythmey.com)"},
        {"name": "Koh Santepheap", "rss": "[https://kohsantepheapdaily.com.kh/feed](https://kohsantepheapdaily.com.kh/feed)",        "url": "[https://kohsantepheapdaily.com.kh](https://kohsantepheapdaily.com.kh)"},
        {"name": "Khmer Times",    "rss": "[https://www.khmertimeskh.com/feed/](https://www.khmertimeskh.com/feed/)",            "url": "[https://www.khmertimeskh.com](https://www.khmertimeskh.com)"},
        {"name": "Cambodianess",   "rss": "[https://cambodianess.com/rss](https://cambodianess.com/rss)",                  "url": "[https://cambodianess.com](https://cambodianess.com)"},
    ],
    "thailand": [
        {"name": "Bangkok Post",   "rss": "[https://www.bangkokpost.com/rss/feed/topstories](https://www.bangkokpost.com/rss/feed/topstories)", "url": "[https://www.bangkokpost.com](https://www.bangkokpost.com)"},
        {"name": "Thai PBS World", "rss": "[https://world.thaipbs.or.th/feed](https://world.thaipbs.or.th/feed)",                "url": "[https://world.thaipbs.or.th](https://world.thaipbs.or.th)"},
        {"name": "Khaosod English","rss": "[https://www.khaosodenglish.com/feed](https://www.khaosodenglish.com/feed)",             "url": "[https://www.khaosodenglish.com](https://www.khaosodenglish.com)"},
    ]
}

# =========================== 🎨 VISUAL ENGINE ===========================
async def download_image_bytes(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200: return await resp.read()
    except: pass
    return None

async def generate_poster(image_bytes, title, source_name, is_breaking=False):
    if not image_bytes: return None
    try:
        # Setup Image
        target_size = (1200, 800)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        
        # Resize & Crop
        ratio = max(target_size[0] / img.width, target_size[1] / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        left = (img.width - target_size[0]) / 2
        top = (img.height - target_size[1]) / 2
        img = img.crop((left, top, left + target_size[0], top + target_size[1]))
        
        # Darken & Gradient
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.85)
        overlay = Image.new('RGBA', img.size, (0,0,0,0))
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
            # Silent fallback if check passed but load failed
            font_title = ImageFont.load_default()
            font_meta = ImageFont.load_default()
            font_badge = ImageFont.load_default()

        # Badge
        badge_text = "BREAKING NEWS" if is_breaking else "AI DAILY UPDATE"
        color = (220, 20, 60) if is_breaking else (0, 102, 204)
        draw.rectangle([50, 530, 270 if is_breaking else 260, 570], fill=color)
        draw.text((65, 535), badge_text, font=font_badge, fill="white")

        # Title
        text_x, text_y = 50, 590
        words = title.split()
        lines, current = [], ""
        for word in words:
            if len(current + word) <= 38: current += word + " "
            else: lines.append(current); current = word + " "
        lines.append(current)
        
        for line in lines[:3]:
            draw.text((text_x+2, text_y+2), line, font=font_title, fill="black")
            draw.text((text_x, text_y), line, font=font_title, fill="white")
            text_y += 70

        # Footer
        draw.rectangle([text_x, text_y+20, text_x+5, text_y+50], fill=(255,204,0))
        draw.text((text_x+20, text_y+22), f"{source_name} • {datetime.now(ICT):%d %b %Y}", font=font_meta, fill=(220,220,220))

        bio = io.BytesIO()
        out.convert("RGB").save(bio, format='JPEG', quality=95)
        return bio.getvalue()
    except Exception as e:
        logging.error(f"Poster Error: {e}")
        return None

# =========================== 🧠 AI ENGINE ===========================
async def process_with_ai(article: dict) -> dict:
    prompt = f"""
    Role: News Editor.
    Task: Process for Cambodia/Thailand audience.
    Source: {article['title']}
    Content: {article['summary']}
    
    Output JSON ONLY:
    {{
        "title_kh": "Formal Khmer Headline",
        "body_kh": "Summary in Khmer (3-4 sentences)",
        "analysis": "One sentence context analysis",
        "sentiment": "Neutral/Positive/Negative/Warning",
        "hashtags": "#Cambodia #News (3-4 tags)"
    }}
    """
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt, generation_config={"response_mime_type": "application/json"})
        
        # ✅ FIX: Clean JSON (Remove backticks if present)
        text_content = resp.text
        if "```" in text_content:
            text_content = re.sub(r"```json|```", "", text_content).strip()
            
        data = json.loads(text_content)
        article.update(data)
        return article
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return None

# =========================== 📨 POSTING (TG + FB) ===========================

async def post_telegram(bot: Bot, article: dict, image_bytes=None) -> bool:
    title = html.escape(article['title_kh'])
    body = html.escape(article['body_kh'])
    analysis = html.escape(article['analysis'])
    
    flag = "🇰🇭" if article['category'] == 'cambodia' else "🇹🇭"
    emoji = {"Positive":"🎉","Negative":"😔","Warning":"⚠️"}.get(article['sentiment'], "📰")
    
    caption = (
        f"{flag} {emoji} <b>{title}</b>\n\n"
        f"{body}\n\n"
        f"💡 <i>{analysis}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {html.escape(article['source'])}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("អានពេញ 🔗", url=article['link'])]])
    
    try:
        if image_bytes:
            await bot.send_photo(TELEGRAM_CHANNEL_ID, image_bytes, caption=caption, parse_mode=ParseMode.HTML, reply_markup=btn)
        else:
            await bot.send_message(TELEGRAM_CHANNEL_ID, caption, parse_mode=ParseMode.HTML, reply_markup=btn, disable_web_page_preview=False)
        return True
    except Exception as e:
        logging.error(f"Telegram Error: {e}")
        return False

async def post_facebook(article: dict, image_bytes=None) -> bool:
    if not FB_ACCESS_TOKEN or not FB_PAGE_ID:
        return False
        
    flag = "🇰🇭" if article['category'] == 'cambodia' else "🇹🇭"
    message = (
        f"{flag} {article['title_kh']}\n\n"
        f"{article['body_kh']}\n\n"
        f"💡 {article.get('analysis', '')}\n\n"
        f"🔗 {article['link']}\n\n"
        f"{article.get('hashtags', '#News')}"
    )

    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos" if image_bytes else f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
    
    try:
        async with aiohttp.ClientSession() as session:
            data = FormData()
            data.add_field('access_token', FB_ACCESS_TOKEN)
            data.add_field('message', message)
            
            if image_bytes:
                data.add_field('source', image_bytes, filename='news.jpg', content_type='image/jpeg')
            else:
                data.add_field('link', article['link'])

            async with session.post(url, data=data) as resp:
                result = await resp.json()
                if 'id' in result:
                    logging.info(f"✅ Posted to Facebook: ID {result['id']}")
                    return True
                else:
                    logging.error(f"❌ Facebook API Error: {result}")
                    return False
    except Exception as e:
        logging.error(f"❌ Facebook Connection Error: {e}")
        return False

# =========================== 🚀 MAIN WORKER ===========================
async def worker():
    logging.info("🚀 Hybrid Bot (Telegram + Facebook) Started")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    while True:
        h = datetime.now(ICT).hour
        if 0 <= h < 5: interval, limit = 1800, 1
        elif 5 <= h < 9 or 11 <= h < 14 or 17 <= h < 20: interval, limit = 300, 4
        else: interval, limit = 600, 2
        
        logging.info(f"🔍 Scanning... (Limit: {limit}, Next: {interval}s)")
        posted_count = 0
        
        for cat, sources in NEWS_SOURCES.items():
            if posted_count >= limit: break
            for src in sources:
                if posted_count >= limit: break
                try:
                    feed = feedparser.parse(src['rss'])
                    if not feed.entries: continue
                    e = feed.entries[0]
                    
                    aid = hashlib.md5(e.link.encode()).hexdigest()
                    doc = await asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).get())
                    if doc.exists: continue
                    
                    raw = {
                        "title": e.title, "link": e.link, 
                        "summary": BeautifulSoup(e.get('summary',''), "html.parser").get_text()[:1500],
                        "source": src['name'], "category": cat
                    }
                    
                    # Deduplication check again just in case
                    if await asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).get()).exists: continue

                    img_url = None
                    if 'media_content' in e: img_url = e.media_content[0]['url']
                    elif soup := BeautifulSoup(e.get('summary',''), 'html.parser').find('img'): img_url = urljoin(src['url'], soup['src'])
                    
                    final = await process_with_ai(raw)
                    if final:
                        raw_bytes = await download_image_bytes(img_url) if img_url else None
                        poster_bytes = await generate_poster(raw_bytes, final['title_kh'], final['source'], final['sentiment']=='Warning')
                        final_img = poster_bytes if poster_bytes else raw_bytes
                        
                        tg_ok = await post_telegram(bot, final, final_img)
                        fb_ok = await post_facebook(final, final_img)
                        
                        if tg_ok or fb_ok:
                            await asyncio.to_thread(lambda: db.collection('posted_articles').document(aid).set({
                                "title": final['title'], "posted_at": firestore.SERVER_TIMESTAMP,
                                "platforms": {"telegram": tg_ok, "facebook": fb_ok}
                            }))
                            logging.info(f"✅ Posted: {final['title_kh']}")
                            posted_count += 1
                            await asyncio.sleep(15)
                            
                except Exception as ex: logging.error(f"Err {src['name']}: {ex}")
        
        await asyncio.sleep(interval)

# =========================== SERVER ===========================
async def health(req): return web.Response(text="Bot Running (TG+FB)")
async def main():
    app = web.Application(); app.router.add_get('/', health)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080)))
    await asyncio.gather(site.start(), worker())

if __name__ == "__main__": asyncio.run(main())