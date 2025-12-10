"""
Thai Conflict Monitor Bot v1.0
==============================
🎯 Objective: Monitor & Summarize Thai Perspective on the Conflict
🛡️ Role: Intelligence Analyst (Neutral Reporting of "Their" Claims)
"""

import os
import asyncio
import json
import hashlib
import re
import logging
import ssl
import io
from datetime import datetime
from typing import Optional, Dict

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from PIL import Image

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

# Config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash" # Fast & Smart

# Telegram (You might want a separate channel for this, or use the same)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID") 

ICT = pytz.timezone('Asia/Phnom_Penh')

# ═══════════════════════════════════════════════════════════════════════════
# 2. THAI SOURCES & FILTERS
# ═══════════════════════════════════════════════════════════════════════════

# Only Thai English News Sources (Easier for AI to analyze accurately)
THAI_SOURCES = [
    {"name": "Bangkok Post",    "rss": "https://www.bangkokpost.com/rss/data/topstories.xml"},
    {"name": "Thai PBS World",  "rss": "https://www.thaipbsworld.com/feed/"},
    {"name": "The Nation",      "rss": "https://www.nationthailand.com/rss/300"},
    {"name": "Khaosod English", "rss": "https://www.khaosodenglish.com/feed/"}
]

# Keywords to ensure we only get news about the CONFLICT (Not Thai local news)
CONFLICT_KEYWORDS = [
    "cambodia", "khmer", "border", "military", "clash", "skirmish", "preah vihear", 
    "soldier", "army", "shelling", "attack", "dispute", "evacuation", "surin", "sisaket"
]

# ═══════════════════════════════════════════════════════════════════════════
# 3. CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
genai.configure(api_key=GEMINI_API_KEY)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Initialize Firebase (Check if already initialized by the other bot script)
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDENTIALS")))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    logging.error(f"Firebase Error: {e}")

async def fetch_rss(url: str):
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as s:
            async with s.get(url, timeout=15) as r:
                return feedparser.parse(await r.text()) if r.status == 200 else None
    except: return None

async def analyze_thai_perspective(article: Dict) -> Dict:
    """
    AI Persona: Intelligence Analyst.
    Task: Extract the 'Thai Narrative' and translate to Khmer.
    """
    prompt = f"""You are a Strategic Intelligence Analyst monitoring Thai media.
Task: Summarize this news article for a Cambodian audience to understand the Thai perspective.

Article: {article['title']}
Context: {article['summary'][:2000]}
Source: {article['source']} (Thai Media)

GUIDELINES:
1. LANGUAGE: Translate to Khmer.
2. TONE: Objective but clear that these are THAI claims. Use phrases like "ប្រព័ន្ធផ្សព្វផ្សាយថៃអះអាងថា..." (Thai media claims...), "យោធាថៃបានថ្លែងថា..." (Thai military stated...).
3. FOCUS: What is their justification? What are they telling their people?
4. OUTPUT: JSON Only.

JSON Structure:
{{
    "headline_kh": "Headline in Khmer (labeled as Thai Source)",
    "summary_kh": "Summary of their narrative in Khmer"
}}"""

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        text = re.sub(r"^```json\s*|```$", "", resp.text.strip(), flags=re.M)
        data = json.loads(text)
        return data
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return None

async def worker():
    logging.info("🕵️ Thai Conflict Monitor Started...")
    
    while True:
        for src in THAI_SOURCES:
            try:
                feed = await fetch_rss(src['rss'])
                if not feed or not feed.entries: continue
                
                entry = feed.entries[0]
                
                # 1. RELEVANCE FILTER (Only Conflict News)
                full_text = (entry.title + " " + entry.get('summary', '')).lower()
                if not any(k in full_text for k in CONFLICT_KEYWORDS):
                    continue # Skip unrelated news (e.g., Thai politics, sports)

                aid = hashlib.md5(f"THAI_{entry.link}".encode()).hexdigest()
                
                # 2. DB Check
                doc = await asyncio.to_thread(db.collection('thai_monitor_logs').document(aid).get)
                if doc.exists: continue
                
                # 3. Build Article Data
                article = {
                    "title": entry.title,
                    "summary": BeautifulSoup(entry.get('summary', ''), 'html.parser').get_text(),
                    "source": src['name'],
                    "link": entry.link
                }
                
                # 4. Analyze with AI
                analysis = await analyze_thai_perspective(article)
                if not analysis: continue
                
                # 5. Post to Telegram
                msg = (
                    f"🇹🇭 **ព័ត៌មានពីជ្រុងខាងថៃ (Thai Perspective)**\n"
                    f"⚠️ *ចំណាំ: នេះជាការចុះផ្សាយរបស់សារព័ត៌មាន {src['name']}*\n\n"
                    f"📰 **{analysis['headline_kh']}**\n\n"
                    f"{analysis['summary_kh']}\n\n"
                    f"🔗 [ប្រភពដើម (Original)]({entry.link})\n"
                    f"🗓 {datetime.now(ICT):%d/%m/%Y • %H:%M}"
                )
                
                # Button to original source only (No cross-links needed for intel)
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("មើលប្រភពដើម 🇹🇭", url=entry.link)]])
                
                await bot.send_message(TELEGRAM_CHANNEL_ID, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=btn)
                logging.info(f"✅ Thai Intel Posted: {entry.title[:30]}")
                
                # 6. Save to DB
                await asyncio.to_thread(db.collection('thai_monitor_logs').document(aid).set, {
                    "title": entry.title, "posted_at": firestore.SERVER_TIMESTAMP
                })
                
            except Exception as e:
                logging.error(f"Source Error {src['name']}: {e}")
                
        await asyncio.sleep(300) # Check every 5 minutes (Don't need real-time urgency like the main bot)

if __name__ == "__main__":
    asyncio.run(worker())