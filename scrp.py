import requests
from bs4 import BeautifulSoup
import json
import time
import re
from urllib.parse import urljoin
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://darkegy.cam"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}

def get_soup(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def extract_listing(page_url):
    print(f"Scraping listing: {page_url}")
    soup = get_soup(page_url)
    
    videos = []
    blocks = soup.select(".thumb-block")
    
    for block in blocks:
        try:
            # Real title
            title_el = block.select_one("header.entry-header span")
            title = title_el.get_text(strip=True) if title_el else None
            
            # Fallback: title attribute on the main link
            if not title:
                link = block.select_one("a[title]")
                title = link.get("title") if link else None
            
            # Page link
            link_el = block.select_one("a[href]")
            page_link = urljoin(BASE_URL, link_el["href"]) if link_el else None
            
            # Thumbnail
            img = block.select_one("img")
            thumb = None
            if img:
                thumb = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if thumb:
                    thumb = urljoin(BASE_URL, thumb)
            
            if title and page_link:
                videos.append({
                    "title": title,
                    "thumbnail": thumb,
                    "page_link": page_link,
                    "video_link": None
                })
        except Exception as e:
            print(f"  Error parsing card: {e}")
    
    print(f"Found {len(videos)} videos")
    return videos

def unpack_jwplayer(html):
    """Unpack the common Dean Edwards style packer used by luluvdo"""
    m = re.search(r"return p\}\('(.+?)',(\d+),(\d+),'(.+?)'\.split\('\|'\)", html, re.DOTALL)
    if not m:
        return None
    
    p, a, c, kstr = m.groups()
    a, c = int(a), int(c)
    k = kstr.split('|')
    
    def to_base(n, base):
        if n == 0:
            return '0'
        alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
        s = ''
        while n > 0:
            s = alphabet[n % base] + s
            n //= base
        return s
    
    for i in range(c - 1, -1, -1):
        if i < len(k) and k[i]:
            p = re.sub(r'\b' + to_base(i, a) + r'\b', k[i], p)
    
    # Look for the master.m3u8 or mp4
    match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', p)
    if match:
        return match.group(1)
    
    match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', p)
    if match:
        return match.group(1)
    
    return None

def extract_video_info(page_url):
    """Returns both the temporary m3u8 and the more stable embed URL"""
    result = {
        "video_link": None,
        "embed_url": None
    }
    
    try:
        soup = get_soup(page_url)
        
        # Find the luluvdo iframe
        iframe = soup.select_one("iframe[src*='luluvdo.com'], iframe[src*='lulu']")
        if not iframe:
            iframe = soup.select_one("iframe[src*='/e/']")
        
        if not iframe:
            print("    No iframe found")
            return result
        
        embed_url = iframe.get("src")
        if not embed_url.startswith("http"):
            embed_url = "https:" + embed_url
        
        result["embed_url"] = embed_url
        print(f"    Embed: {embed_url}")
        
        # Try to get a fresh m3u8
        r = requests.get(embed_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        
        video_url = unpack_jwplayer(r.text)
        result["video_link"] = video_url
        
    except Exception as e:
        print(f"    Error: {e}")
    
    return result
def main():
    # Read numbers from GitHub Actions, fallback to default values if running locally
    START_PAGE = int(os.environ.get("START_PAGE", 11))
    END_PAGE = int(os.environ.get("END_PAGE", 7138))
    
    print(f"Running scraper from page {START_PAGE} to {END_PAGE}")
    
    # Make sure your output JSON file name is dynamic so files don't overwrite
    output_file = f"results_pages_{START_PAGE}_to_{END_PAGE}.json"
    DELAY_BETWEEN_PAGES = 0.5
    DELAY_BETWEEN_VIDEOS = 0.2
    
    # output_file = "darkegy_all.json"
    
    # Load existing data safely
    all_videos = []
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    all_videos = json.loads(content)
                    print(f"Loaded {len(all_videos)} existing videos from {output_file}")
                else:
                    print("Existing file is empty. Starting fresh.")
        except json.JSONDecodeError:
            print("Existing JSON file is corrupted. Starting fresh.")
            all_videos = []
    else:
        print("No existing file found. Starting fresh.")
    
    for page_num in range(START_PAGE, END_PAGE + 1):
        listing_url = f"https://darkegy.cam/page/{page_num}/"
        
        print(f"\n{'='*60}")
        print(f"Scraping page {page_num}/{END_PAGE}")
        print(f"{'='*60}")
        
        try:
            videos = extract_listing(listing_url)
            
            if not videos:
                print(f"No videos found on page {page_num}, skipping...")
                time.sleep(DELAY_BETWEEN_PAGES)
                continue
            
            print(f"Found {len(videos)} videos. Extracting embeds...")
            
            for i, v in enumerate(videos, 1):
                try:
                    print(f"  [{i}/{len(videos)}] {v['title'][:60]}...")
                except:
                    print(f"  [{i}/{len(videos)}] ...")
                
                info = extract_video_info(v["page_link"])
                v["video_link"] = info["video_link"]
                v["embed_url"] = info["embed_url"]
                v["page_number"] = page_num
                
                time.sleep(DELAY_BETWEEN_VIDEOS)
            
            all_videos.extend(videos)
            
            # Save progress after every page
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(all_videos, f, ensure_ascii=False, indent=2)
            
            print(f"Progress saved → {len(all_videos)} videos total so far")
            
        except Exception as e:
            print(f"Error on page {page_num}: {e}")
            # Still save what we have
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(all_videos, f, ensure_ascii=False, indent=2)
        
        time.sleep(DELAY_BETWEEN_PAGES)
    
    print(f"\nFinished! Total videos collected: {len(all_videos)}")
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    main()
