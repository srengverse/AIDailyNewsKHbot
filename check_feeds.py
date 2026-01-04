import feedparser
import asyncio
import aiohttp

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive'
}

FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "http://feeds.reuters.com/reuters/environment",
    "https://www.sciencedaily.com/rss/earth_climate/climate.xml",
    "https://www.reutersagency.com/feed/?best-topics=environment&post_type=best",
    "https://www.reutersagency.com/feed/?best-topics=technology&post_type=best"
]

async def check():
    for url in FEEDS:
        print(f"Checking {url}...")
        try:
            d = feedparser.parse(url, request_headers=HEADERS)
            if d.entries:
                print(f"✅ SUCCESS: {len(d.entries)} entries")
            else:
                print(f"❌ FAIL: No entries (Status: {d.get('status', 'unknown')})")
        except Exception as e:
            print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(check())
