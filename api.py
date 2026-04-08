import os
import json
import requests
import re
import urllib.request
import zipfile
import stat
import asyncio
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="AyuPrime Extractor API")

# ==========================================
# ⚡ DENO INSTALLER (For hanime-plugin)
# ==========================================
def install_deno():
    try:
        deno_dir = os.path.expanduser("~/.deno/bin")
        deno_path = os.path.join(deno_dir, "deno")
        if not os.path.exists(deno_path):
            os.makedirs(deno_dir, exist_ok=True)
            url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"
            zip_file = os.path.join(deno_dir, "deno.zip")
            urllib.request.urlretrieve(url, zip_file)
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(deno_dir)
            st = os.stat(deno_path)
            os.chmod(deno_path, st.st_mode | stat.S_IEXEC)
            os.remove(zip_file)
        if deno_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{deno_dir}:{os.environ.get('PATH', '')}"
    except Exception as e: 
        print(f"Deno Error: {e}")

# ==========================================
# 🛡️ PROXY & HEADERS
# ==========================================
PROXY_URL = "http://dLAG1sTQ6:qKE6euVsA@138.249.190.195:62694"
PROXIES_DICT = {"http": PROXY_URL, "https": PROXY_URL}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
YT_HEADERS = (
    f'--user-agent "{USER_AGENT}" '
    f'--add-header "Accept-Language:en-US,en;q=0.9" '
    f'--add-header "Sec-Fetch-Mode:navigate" '
    f'--add-header "Sec-Fetch-Site:cross-site"'
)

@app.on_event("startup")
async def startup_event():
    install_deno()
    print("✅ Deno Installed! Ready to power hanime-plugin.")

# ==========================================
# 🧠 YT-DLP ENGINE (Plugin Supported)
# ==========================================
async def run_yt_dlp(url):
    try:
        cmd = f'yt-dlp --proxy "{PROXY_URL}" {YT_HEADERS} --no-playlist -j "{url}"'
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0: return None
        
        output = stdout.decode('utf-8').strip()
        for line in output.split('\n'):
            if line.strip().startswith('{'):
                try: return json.loads(line)
                except: pass
    except: return None
    return None

# ==========================================
# 🌐 ENDPOINT 1: GET ALL EPISODES
# ==========================================
@app.get("/get_episodes")
async def get_episodes(url: str = Query(..., description="Series or Playlist URL")):
    episodes = []
    try:
        if "hanime.tv" in url:
            slug = url.split('/hentai/')[-1].split('?')[0]
            api_url = f"https://hanime.tv/api/v8/video?id={slug}"
            r = await asyncio.to_thread(requests.get, api_url, headers={'User-Agent': 'Mozilla/5.0'}, proxies=PROXIES_DICT, timeout=10)
            if r.status_code == 200:
                for vid in r.json().get('hentai_franchise_hentai_videos', [{'slug': slug}]):
                    episodes.append(f"https://hanime.tv/videos/hentai/{vid['slug']}")
            else: episodes.append(url)
            
        elif "hentaihaven.com" in url:
            # Archiver Bot wala 1 to 20 Loop Logic
            match = re.search(r'hentaihaven\.com/(?:video|watch|series)/([^/]+)', url)
            if match:
                base_slug = match.group(1).replace('-episode', '').split('-ep-')[0]
                for i in range(1, 21):
                    test_url = f"https://hentaihaven.com/video/{base_slug}/episode-{i}"
                    r = await asyncio.to_thread(requests.head, test_url, headers={'User-Agent': 'Mozilla/5.0'}, proxies=PROXIES_DICT, timeout=5)
                    if r.status_code == 200: episodes.append(test_url)
                    else:
                        if i > 1: break # Episode 2 nahi mila toh aage mat badho
                if not episodes: episodes.append(url)
            else: episodes.append(url)
        else:
            episodes.append(url)
            
        return JSONResponse({"status": "success", "count": len(episodes), "episodes": episodes})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# ==========================================
# 🌐 ENDPOINT 2: CROSS-SCAN & EXTRACT M3U8
# ==========================================
@app.get("/extract")
async def extract_links(url: str = Query(..., description="Single Episode URL")):
    results = {"status": "success", "title": "", "thumbnail": "", "links": {}}
    
    # Cross-Scanning Candidates
    if "hanime.tv" in url:
        slug = url.split('/hentai/')[-1].split('?')[0]
        candidates = [
            f"https://hstream.moe/hentai/{slug}",
            f"https://hanime.tv/videos/hentai/{slug}",
            f"https://oppai.stream/watch?e={slug}"
        ]
    else:
        # HentaiHaven ya koi aur site
        candidates = [url]

    # Run yt-dlp on all candidates parallelly
    tasks = [run_yt_dlp(c_url) for c_url in candidates]
    gathered_data = await asyncio.gather(*tasks)

    for data in gathered_data:
        if not data: continue
        
        # Meta Data
        if not results["title"] and data.get("title"):
            results["title"] = "".join([c for c in data.get('title', '') if c.isalnum() or c in ' -_']).strip()
        if not results["thumbnail"] and data.get("thumbnail"):
            results["thumbnail"] = data.get("thumbnail")
            
        # Parse M3U8 Qualities
        for f in data.get("formats", []):
            if f.get("vcodec") != "none" and f.get("height") and f.get("url"):
                q = f"{f.get('height')}p"
                if q not in results["links"]:
                    results["links"][q] = f.get("url")
                    
        # Fallback master url
        if data.get("url") and not results["links"]:
            results["links"]["master"] = data.get("url")

    if not results["links"]:
        return JSONResponse({"status": "error", "message": "Extraction failed or blocked."})
        
    return JSONResponse(results)

# Health Check
@app.get("/")
def read_root():
    return {"status": "AyuPrime API is ALIVE on Koyeb!"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
