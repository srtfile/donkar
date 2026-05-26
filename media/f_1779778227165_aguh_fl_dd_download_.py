"""
direct_downloader.py
=====================
Direct download link extractor — no browser, no clicking, no waiting.

Based on analysis of MITM captured data from captures/20260524_133203/

DISCOVERY:
  fast-dl.org/dl/<id> accepts POST with empty cf-turnstile-response
  and returns the final download link in <a id="vd" href="...">
  No CAPTCHA solving required.

CHAIN PATTERN (from MITM analysis):
  fojik.site → search.technews24.site/blog.php (POST FU=token)
             → sharelink-1.shop/dld.php?i=token (GET)
             → freethemesy.com/dld.php (POST FU2=token)
             → technews24.site/links/<b64> (GET)
             → en.technews24.site/go.php?i=b64&hash=b64 (GET)
             → sharelink-3.shop/dld.php (POST FU5=token)
             → sharelink-3.shop/blog/ (POST FU7=token)
             → sharelink-3.shop/l/api/m (XHR POST s=b64,v=ver)
             → boabd.com/file/<b64> (POST clouddownload=)
             → fast-dl.org/dl/<id> (GET then POST)
             → video-downloads.googleusercontent.com/... (FINAL)

STRATEGY:
  Since fast-dl.org accepts empty Turnstile, we can:
  1. GET the fast-dl.org page to get the link ID
  2. POST with empty token → get final URL from <a id="vd">
  3. Done — no browser needed

Usage:
  python direct_downloader.py
  python direct_downloader.py <fast-dl-url>
  python direct_downloader.py https://fast-dl.org/dl/2dd685
"""

import re
import sys
import json
import base64
import urllib.parse
from pathlib import Path
from datetime import datetime

try:
    from curl_cffi import requests
    SESSION_TYPE = "curl_cffi"
except ImportError:
    import requests
    SESSION_TYPE = "requests"

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Output folder ─────────────────────────────────────────────────────────────
OUT = Path("extracted_links")
OUT.mkdir(exist_ok=True)

# ── Headers that mimic a real Chrome browser ──────────────────────────────────
HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/147.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;"
                       "q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT":             "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
    "sec-ch-ua":       '"Google Chrome";v="147", "Not.A/Brand";v="8"',
    "sec-ch-ua-mobile":"?0",
    "sec-ch-ua-platform": '"Windows"',
}

# ── Resolution server patterns ────────────────────────────────────────────────
LINK_PATTERNS = {
    "google_video":  re.compile(
        r'https://video-downloads\.googleusercontent\.com/[^\s"\'<>]+'),
    "gdrive":        re.compile(
        r'https://drive\.google\.com/[^\s"\'<>]+'),
    "r2_storage":    re.compile(
        r'https://[a-z0-9]+\.[a-z0-9]+\.r2\.cloudflarestorage\.com/[^\s"\'<>]+'),
    "s3":            re.compile(
        r'https://s3\.[a-z0-9-]+\.amazonaws\.com/[^\s"\'<>]+'),
    "direct_file":   re.compile(
        r'https://[^\s"\'<>]+\.(?:mkv|mp4|avi|zip|rar|mp3|aac)[^\s"\'<>]*',
        re.I),
    "mega":          re.compile(r'https://mega\.nz/[^\s"\'<>]+'),
    "mediafire":     re.compile(
        r'https://www\.mediafire\.com/[^\s"\'<>]+'),
    "pixeldrain":    re.compile(r'https://pixeldrain\.com/[^\s"\'<>]+'),
    "cf_worker":     re.compile(
        r'https://[a-z0-9-]+\.[a-z0-9]+\.workers\.dev/[^\s"\'<>]*'),
}

def log(msg, tag=""):
    icons = {"ok":"✅","err":"❌","find":"🔍","info":"ℹ","warn":"⚠"}
    print(f"  {icons.get(tag,' ')} {msg}")

def make_session():
    if SESSION_TYPE == "curl_cffi":
        s = requests.Session(impersonate="chrome120")
    else:
        s = requests.Session()
    s.headers.update(HEADERS)
    return s

def b64d(v):
    try:
        return base64.b64decode(
            urllib.parse.unquote(str(v)) + "==").decode("utf-8")
    except Exception:
        return v

def extract_links(html: str, url: str = "") -> dict:
    """Extract all download links from HTML using multiple methods."""
    found = {}

    # Method 1: <a id="vd" href="..."> — the primary fast-dl.org pattern
    m = re.search(r'<a[^>]+id=["\']vd["\'][^>]+href=["\']([^"\']+)["\']',
                  html, re.I)
    if not m:
        m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]+id=["\']vd["\']',
                      html, re.I)
    if m:
        found["vd_link"] = m.group(1)
        log(f"<a id=vd> link: {m.group(1)[:100]}", "find")

    # Method 2: cf-cache attribute (Cloudflare worker proxy URL, base64)
    m = re.search(r'cf-cache=["\']([A-Za-z0-9+/=]+)["\']', html)
    if m:
        decoded = b64d(m.group(1))
        found["cf_cache_worker"] = decoded
        log(f"cf-cache worker: {decoded[:100]}", "find")

    # Method 3: All known resolution server patterns
    for name, pat in LINK_PATTERNS.items():
        matches = [m.group(0).rstrip("\"'>,;)")
                   for m in pat.finditer(html)]
        if matches:
            found[name] = list(dict.fromkeys(matches))
            for u in matches[:2]:
                log(f"[{name}] {u[:100]}", "find")

    # Method 4: BeautifulSoup — all <a href> with download-like URLs
    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        dl_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(k in href for k in ["download", "file", "dl",
                                        "video-downloads", "drive.google",
                                        "mega.nz", "mediafire",
                                        "cloudflarestorage", "amazonaws"]):
                dl_links.append(href)
        if dl_links:
            found["bs4_links"] = list(dict.fromkeys(dl_links))

    return found


def fetch_fast_dl(session, url: str) -> dict:
    """
    Fetch a fast-dl.org link using the discovered mechanism:
    GET → POST with empty cf-turnstile-response → extract <a id=vd>
    """
    log(f"Fetching: {url}", "info")

    # Step 1: GET the page
    try:
        r = session.get(url, timeout=20)
        log(f"GET {url} → {r.status_code}", "ok" if r.status_code == 200 else "warn")
    except Exception as e:
        log(f"GET failed: {e}", "err")
        return {}

    # Check if already has the link (cached response)
    links = extract_links(r.text, url)
    if links.get("vd_link") or links.get("google_video"):
        log("Link found in GET response (cached)", "ok")
        return links

    # Step 2: POST with empty Turnstile token
    # DISCOVERY: server accepts empty cf-turnstile-response
    log("POSTing with empty cf-turnstile-response...", "info")
    try:
        post_headers = {
            **HEADERS,
            "Content-Type":  "application/x-www-form-urlencoded",
            "Origin":        urllib.parse.urlparse(url).scheme + "://" +
                             urllib.parse.urlparse(url).netloc,
            "Referer":       url,
            "Sec-Fetch-Site":"same-origin",
            "Cache-Control": "max-age=0",
        }
        r2 = session.post(
            url,
            data="cf-turnstile-response=",
            headers=post_headers,
            timeout=30,
        )
        log(f"POST → {r2.status_code}  ({len(r2.text):,} chars)", "ok")
    except Exception as e:
        log(f"POST failed: {e}", "err")
        return links

    # Extract links from POST response
    links2 = extract_links(r2.text, url)
    links.update(links2)

    return links


def resolve_fast_dl_id(session, link_id: str) -> dict:
    """Resolve a fast-dl.org short ID."""
    url = f"https://fast-dl.org/dl/{link_id}"
    return fetch_fast_dl(session, url)


def process_any_url(session, url: str) -> dict:
    """
    Process any URL — auto-detect the type and extract download links.
    Supports: fast-dl.org, direct links, and other known patterns.
    """
    parsed = urllib.parse.urlparse(url)
    host   = parsed.netloc.lower()

    # fast-dl.org
    if "fast-dl.org" in host:
        return fetch_fast_dl(session, url)

    # Direct file URL — just return it
    if any(url.lower().endswith(ext)
           for ext in [".mkv",".mp4",".avi",".zip",".rar",".mp3"]):
        log(f"Direct file URL: {url}", "ok")
        return {"direct": url}

    # Google video CDN — already final
    if "video-downloads.googleusercontent.com" in host:
        log(f"Google video CDN URL (already final): {url[:80]}", "ok")
        return {"google_video": [url]}

    # Cloudflare R2 / S3 — already final
    if "cloudflarestorage.com" in host or "amazonaws.com" in host:
        log(f"Cloud storage URL (already final): {url[:80]}", "ok")
        return {"cloud_storage": [url]}

    # Generic — fetch and extract
    log(f"Generic URL — fetching and extracting links...", "info")
    try:
        r = session.get(url, timeout=20)
        return extract_links(r.text, url)
    except Exception as e:
        log(f"Fetch error: {e}", "err")
        return {}


def save_results(results: dict, source_url: str):
    """Save extracted links to JSON file."""
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "source":    source_url,
        "timestamp": ts,
        "links":     results,
    }
    out = OUT / f"links_{ts}.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log(f"Saved → {out}", "ok")
    return out


def print_results(results: dict):
    """Print all found links clearly."""
    if not results:
        log("No links found", "warn")
        return

    print(f"\n{'═'*60}")
    print(f"  EXTRACTED DOWNLOAD LINKS")
    print(f"{'═'*60}")

    priority = ["vd_link", "google_video", "r2_storage", "s3",
                "direct_file", "gdrive", "mega", "mediafire",
                "pixeldrain", "cf_worker", "cf_cache_worker",
                "bs4_links"]

    shown = set()
    for key in priority + [k for k in results if k not in priority]:
        val = results.get(key)
        if not val:
            continue
        urls = [val] if isinstance(val, str) else val
        for u in urls:
            if u in shown:
                continue
            shown.add(u)
            print(f"\n  [{key}]")
            print(f"  {u}")

    print(f"\n{'═'*60}")
    print(f"  Total unique links: {len(shown)}")
    print(f"{'═'*60}\n")


def main():
    # Default: use the fast-dl.org URL from the MITM capture
    default_url = "https://fast-dl.org/dl/a45d08"
    url = sys.argv[1] if len(sys.argv) > 1 else default_url

    print(f"\n{'═'*60}")
    print(f"  DIRECT DOWNLOAD LINK EXTRACTOR")
    print(f"  Session: {SESSION_TYPE}  |  bs4: {HAS_BS4}")
    print(f"{'═'*60}")
    print(f"  URL: {url}\n")

    session = make_session()
    results = process_any_url(session, url)

    print_results(results)
    if results:
        save_results(results, url)

    # Return the best link for use in other scripts
    best = (results.get("vd_link")
            or (results.get("google_video") or [None])[0]
            or (results.get("r2_storage") or [None])[0]
            or (results.get("direct_file") or [None])[0])
    if best:
        log(f"Best link: {best[:120]}", "ok")
    return best


if __name__ == "__main__":
    main()
