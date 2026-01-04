# 🤖 AI Daily News KH Bot (Facebook Edition)

**An intelligent, automated news publisher for the Cambodian audience.**

This bot aggregates news from trusted local and global sources, uses **Dual-Engine AI** (Groq + Gemini) to summarize and translate content into engaging Khmer posts, and publishes them specifically for Facebook.

---

## 🚀 Key Features

*   **Dual-AI Architecture**:
    *   **Primary Engine**: **Groq** (Llama 3.3 70B) for lightning-fast speeds.
    *   **Fallback Engine**: **Google Gemini** (2.5 Flash) for robust failover reliability.
    *   *System automatically switches if rate limits or errors occur.*
*   **Smart Content curation**:
    *   **Cambodia Context**: Filters global news to find mentions of Cambodia, ASEAN, or Major Powers affecting the region.
    *   **Topic Relevance**: Specifically targets **Technology** (AI/Scams), **Business** (Gold/Oil/Dollar), and **Environment** (Climate/Flood).
*   **Diverse Sources**:
    *   🇰🇭 **Local**: Koh Santepheap, Khmer Times, CamboJA.
    *   🌍 **Global**: CNN, The Guardian, DW, CNA, Reuters.
    *   💻 **Specialized**: TechCrunch, The Verge, CNBC, ScienceDaily.
*   **Resilience**:
    *   Firebase Cloud Firestore for state tracking (prevents duplicates).
    *   Auto-retry mechanism with exponential backoff.
    *   Docker/Render ready.

---

## 🛠️ Installation & Setup

### Prerequisites
*   Python 3.12+
*   Firebase Admin SDK Key (`firebase_key.json`)
*   Groq & Gemini API Keys
*   Facebook Page Access Token

### 1. Clone Repository
```bash
git clone https://github.com/Srengnx007/AIDailyNewsKHbot.git
cd AIDailyNewsKHbot
```

### 2. Install Dependencies
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file:
```env
# AI Keys
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIzaSy...

# Facebook Graph API
FACEBOOK_ACCESS_TOKEN=EAAB...
FACEBOOK_PAGE_ID=123456789

# Database
# Option A: Path to file
FIREBASE_CRED_PATH=firebase_key.json
# Option B: Raw JSON string (for Render/Cloud)
FIREBASE_CREDENTIALS={"type": "service_account", ...}

# Server
PORT=8080
```

### 4. Run the Bot
```bash
python botnews.py
```

---

## ☁️ Deployment (Render.com)

1.  **New Web Service**: Connect your GitHub repo.
2.  **Runtime**: Python 3.
3.  **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
4.  **Start Command**: `python botnews.py`
5.  **Environment Variables**: copy all keys from your `.env`.

---

## 🧠 How It Works

1.  **Fetch**: RSS Feeds are polled every 10-30 minutes.
2.  **Filter**: Articles are checked against `is_relevant_content()` logic.
3.  **Process**:
    *   Groq attempts to summarize & translate to Khmer.
    *   If Groq fails (429/500), Gemini takes over.
    *   Images are optimized/generated.
4.  **Publish**: Content is posted to the Facebook Page via Graph API.

---

## 📝 License
This project is for educational and personal use.
