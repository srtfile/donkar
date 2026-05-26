"""
Auto Downloader — Raja Shivaji 2026 (fojik.com)
================================================
Automatically navigates the full download chain by replaying the exact
click sequence captured in your session data:

  Step 1 → fojik.com            : click the "Download" <a> (form submit)
  Step 2 → sharelink-1.shop     : click .myButton (submit button)
  Step 3 → freethemesy.com      : click .download-text span
  Step 4 → technews24.site      : click the "GDS" <a> link
  Step 5 → sharelink-3.shop     : click .butt.btn (generateDownloadLink)
  Step 6 → boabd.com            : click "Resume Supported Direct Link" button

Uses the SAME profile-loading logic as the original capturer script
(real Firefox profile + uBlock Origin active).

REQUIREMENTS:
    pip install selenium webdriver-manager

USAGE:
    python auto_downloader.py
"""

import os
import sys
import time
import signal
import platform
import subprocess
from pathlib import Path
from datetime import datetime

# ── auto-install deps ─────────────────────────────────────────────────────────
def ensure(pkg, import_as=None):
    name = import_as or pkg.replace("-", "_")
    try:
        __import__(name)
    except ImportError:
        print(f"  Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               pkg, "-q", "--disable-pip-version-check"])

ensure("selenium")
ensure("webdriver_manager")

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
TARGET_URL   = "https://fojik.com/movie/jana-nayagan-2026/"
SAVE_DIR     = r"C:\Users\AC\Desktop\NARUTO_SHIPPUDEN"
WAIT_TIMEOUT = 20     # seconds to wait for each element
STEP_DELAY   = 3.0    # seconds to pause between steps (let pages settle)

os.makedirs(SAVE_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PROFILE LOADER  (identical to capturer)
# ─────────────────────────────────────────────────────────────────────────────
def get_firefox_profile():
    if platform.system() == "Windows":
        base = os.path.join(os.environ["APPDATA"], "Mozilla", "Firefox")
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/Firefox")
    else:
        base = os.path.expanduser("~/.mozilla/firefox")

    ini = os.path.join(base, "profiles.ini")
    print(f"  Reading profiles.ini: {ini}")
    if not os.path.exists(ini):
        raise FileNotFoundError(f"profiles.ini not found at: {ini}")

    profile_rel = None
    with open(ini, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Default=") and "Profiles/" in line:
                profile_rel = line.strip().split("=", 1)[1]
                break

    if not profile_rel:
        with open(ini, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Default=") and ("." in line or "/" in line):
                    val = line.strip().split("=", 1)[1]
                    if val and val not in ("0", "1"):
                        profile_rel = val
                        break

    if not profile_rel:
        raise Exception(
            "Could not find Firefox profile path in profiles.ini.\n"
            f"Please open {ini} and check which line starts with 'Default='"
        )

    profile_path = os.path.join(base, profile_rel.replace("/", os.sep))
    profile_path = os.path.normpath(profile_path)

    if not os.path.isdir(profile_path):
        raise FileNotFoundError(
            f"Profile directory does not exist: {profile_path}\n"
            f"Raw value from profiles.ini: {profile_rel}"
        )
    return profile_path

# ─────────────────────────────────────────────────────────────────────────────
# KILL EXISTING FIREFOX
# ─────────────────────────────────────────────────────────────────────────────
def kill_firefox():
    print("  Closing any running Firefox ... ", end="", flush=True)
    if platform.system() == "Windows":
        os.system("taskkill /F /IM firefox.exe /T >nul 2>&1")
    else:
        os.system("pkill -9 -f firefox 2>/dev/null; true")
    time.sleep(3)
    print("done")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def page_ready(driver, timeout=15):
    for _ in range(int(timeout / 0.3)):
        try:
            if driver.execute_script("return document.readyState;") == "complete":
                return True
        except:
            return False
        time.sleep(0.3)
    return False

def switch_to_latest_tab(driver):
    """Switch focus to the most recently opened tab."""
    handles = driver.window_handles
    driver.switch_to.window(handles[-1])
    page_ready(driver, 15)
    time.sleep(1.5)
    return driver.current_url

def log(step, msg, ok=True):
    icon = "✔" if ok else "✘"
    print(f"  [{icon}] Step {step}: {msg}")

def wait_and_click(driver, by, selector, step_label, timeout=WAIT_TIMEOUT):
    """Wait for an element, scroll to it, and click it."""
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.4)
        # Green flash so you can see what's being clicked
        driver.execute_script(
            "arguments[0].style.outline='4px solid #00e676';"
            "arguments[0].style.outlineOffset='4px';", el
        )
        time.sleep(0.3)
        el.click()
        log(step_label, f"Clicked  [{selector}]")
        return True
    except Exception as e:
        log(step_label, f"FAILED to click [{selector}] — {e}", ok=False)
        return False

def js_click(driver, selector_js, step_label):
    """Click an element using JS evaluation."""
    try:
        driver.execute_script(selector_js)
        log(step_label, f"JS click executed")
        return True
    except Exception as e:
        log(step_label, f"JS click FAILED — {e}", ok=False)
        return False

# ─────────────────────────────────────────────────────────────────────────────
# THE DOWNLOAD CHAIN — 6 steps
# ─────────────────────────────────────────────────────────────────────────────
def run_download_chain(driver):
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    # ── STEP 1 ──────────────────────────────────────────────────────────────
    # URL  : https://fojik.com/movie/raja-shivaji-2026/
    # Click: <a href="javascript:document.getElementById('113240').submit();">
    # The link calls JS to submit a hidden form with id="113240".
    print("\n" + "─"*60)
    print("  STEP 1 — fojik.com  →  click Download (form submit)")
    print("─"*60)
    driver.get(TARGET_URL)
    page_ready(driver, 20)
    time.sleep(2)

    # Try direct JS form submit first (most reliable)
    submitted = js_click(
        driver,
        "document.getElementById('113240').submit();",
        "1"
    )
    if not submitted:
        # Fallback: click the <a> that calls the same JS
        wait_and_click(
            driver,
            By.XPATH,
            "/html/body/div[1]/div[2]/div[3]/div[2]/div[6]/div[2]/div[1]/div[1]/table[1]/tbody[1]/tr[1]/td[1]/a[1]",
            "1-fallback"
        )

    time.sleep(STEP_DELAY)
    cur_url = switch_to_latest_tab(driver)
    print(f"         Now at: {cur_url}")

    # ── STEP 2 ──────────────────────────────────────────────────────────────
    # URL  : sharelink-1.shop/dld.php?i=...
    # Click: <button class="myButton" type="submit">Download</button>
    print("\n" + "─"*60)
    print("  STEP 2 — sharelink-1.shop  →  click .myButton")
    print("─"*60)

    ok = wait_and_click(driver, By.CSS_SELECTOR, "button.myButton", "2")
    if not ok:
        # Fallback: any submit button
        wait_and_click(driver, By.CSS_SELECTOR, "button[type='submit']", "2-fallback")

    time.sleep(STEP_DELAY)
    cur_url = switch_to_latest_tab(driver)
    print(f"         Now at: {cur_url}")

    # ── STEP 3 ──────────────────────────────────────────────────────────────
    # URL  : freethemesy.com/dld.php
    # Click: <span class="download-text" style="display: inline-block;">Download</span>
    print("\n" + "─"*60)
    print("  STEP 3 — freethemesy.com  →  click .download-text")
    print("─"*60)

    ok = wait_and_click(driver, By.CSS_SELECTOR, "span.download-text", "3")
    if not ok:
        # Fallback: any element with text "Download"
        wait_and_click(
            driver,
            By.XPATH,
            "//*[normalize-space(text())='Download' or normalize-space(.)='Download']",
            "3-fallback"
        )

    time.sleep(STEP_DELAY)
    cur_url = switch_to_latest_tab(driver)
    print(f"         Now at: {cur_url}")

    # ── STEP 4 ──────────────────────────────────────────────────────────────
    # URL  : technews24.site/links/...
    # Click: <a target="_blank" href="https://en.technews24.site/go.php?...">GDS</a>
    # (second <a> inside a <strong> inside <p[5]>)
    print("\n" + "─"*60)
    print("  STEP 4 — technews24.site  →  click 'GDS' link")
    print("─"*60)

    # Try exact XPath first
    ok = wait_and_click(
        driver,
        By.XPATH,
        "/html/body/div[3]/div[1]/div[1]/main[1]/article[1]/div[2]/div[1]/p[5]/strong[1]/a[2]",
        "4"
    )
    if not ok:
        # Fallback: any <a> whose text is "GDS"
        ok = wait_and_click(
            driver,
            By.XPATH,
            "//a[normalize-space(text())='GDS']",
            "4-fallback-text"
        )
    if not ok:
        # Fallback: any <a> whose href contains "go.php"
        wait_and_click(
            driver,
            By.XPATH,
            "//a[contains(@href,'go.php')]",
            "4-fallback-href"
        )

    time.sleep(STEP_DELAY)
    cur_url = switch_to_latest_tab(driver)
    print(f"         Now at: {cur_url}")

    # ── STEP 5 ──────────────────────────────────────────────────────────────
    # URL  : sharelink-3.shop/blog/
    # Click: <a class="butt btn ..." onclick="generateDownloadLink(event);">DOWNLOAD LINK</a>
    print("\n" + "─"*60)
    print("  STEP 5 — sharelink-3.shop  →  click .butt.btn (DOWNLOAD LINK)")
    print("─"*60)

    ok = wait_and_click(driver, By.CSS_SELECTOR, "a.butt.btn", "5")
    if not ok:
        # Fallback: any <a> with onclick containing generateDownloadLink
        ok = wait_and_click(
            driver,
            By.XPATH,
            "//a[contains(@onclick,'generateDownloadLink')]",
            "5-fallback"
        )
    if not ok:
        # Fallback: any <a> whose text contains "DOWNLOAD"
        wait_and_click(
            driver,
            By.XPATH,
            "//a[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'DOWNLOAD')]",
            "5-fallback-text"
        )

    time.sleep(STEP_DELAY)
    cur_url = switch_to_latest_tab(driver)
    print(f"         Now at: {cur_url}")

    # ── STEP 6 ──────────────────────────────────────────────────────────────
    # URL  : boabd.com/file/...
    # Click: <button class="btn btn-primary" name="submit" ...>Resume Supported Direct Link</button>
    print("\n" + "─"*60)
    print("  STEP 6 — boabd.com  →  click 'Resume Supported Direct Link'")
    print("─"*60)

    ok = wait_and_click(driver, By.CSS_SELECTOR, "button[name='submit']", "6")
    if not ok:
        ok = wait_and_click(driver, By.CSS_SELECTOR, "button.btn-primary", "6-fallback")
    if not ok:
        wait_and_click(
            driver,
            By.XPATH,
            "//button[contains(.,'Resume') or contains(.,'Direct Link')]",
            "6-fallback-text"
        )

    time.sleep(STEP_DELAY)
    # After step 6, switch to whatever tab/page appeared
    try:
        cur_url = switch_to_latest_tab(driver)
    except:
        cur_url = driver.current_url
    print(f"         Now at: {cur_url}")

    print("\n" + "="*60)
    print("  ✔  All 6 steps completed!")
    print(f"     Final page: {cur_url}")
    print("="*60)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
driver = None

def cleanup():
    try:
        if driver:
            driver.quit()
    except:
        pass

def sig_handler(sig, frame):
    print(f"\n  [Signal {sig}] Quitting ...")
    cleanup()
    sys.exit(0)

def main():
    global driver

    print("\n" + "="*60)
    print("  Auto Downloader — Raja Shivaji 2026")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # ── Profile ───────────────────────────────────────────────────────────────
    print()
    try:
        profile_path = get_firefox_profile()
    except Exception as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)
    print(f"  Profile : {profile_path}")

    # ── Kill existing Firefox ─────────────────────────────────────────────────
    kill_firefox()

    # ── GeckoDriver ──────────────────────────────────────────────────────────
    print("  GeckoDriver ... ", end="", flush=True)
    try:
        gecko = GeckoDriverManager().install()
        print("ok")
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)

    # ── Launch Firefox ────────────────────────────────────────────────────────
    options = Options()
    options.add_argument("-profile")
    options.add_argument(profile_path)

    print("  Launching Firefox ...")
    try:
        svc    = FirefoxService(gecko, log_output=subprocess.DEVNULL)
        driver = webdriver.Firefox(service=svc, options=options)
        driver.maximize_window()
    except Exception as e:
        print(f"\n  [ERROR] Could not launch Firefox: {e}")
        sys.exit(1)
    print("  Firefox launched  (uBlock Origin active)")

    # ── Signal hooks ──────────────────────────────────────────────────────────
    signal.signal(signal.SIGTERM, sig_handler)
    try:
        signal.signal(signal.SIGINT, sig_handler)
    except:
        pass

    # ── Run the chain ─────────────────────────────────────────────────────────
    try:
        run_download_chain(driver)
    except KeyboardInterrupt:
        print("\n  [Ctrl+C] Stopped by user.")
    except Exception as e:
        print(f"\n  [FATAL] {e}")
    finally:
        print("\n  Browser will stay open so you can grab the final link.")
        print("  Press Enter here to quit Firefox and exit ...")
        try:
            input()
        except:
            pass
        cleanup()


if __name__ == "__main__":
    main()