#!/usr/bin/env python3
"""
Coursera Video Downloader
Opens the course landing page, clicks 'Log in', completes the two-step
login form, clicks 'Go to course', then finds all Video items in the
course outline and downloads each one using Coursera's own signed links.

Requirements:
    uv sync  (or: pip install selenium webdriver-manager requests)

Usage:
    uv run python coursera_downloader.py
    (You will be prompted for your Coursera email and password)
"""

import re
import json
import time
import getpass
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# ── Configuration ─────────────────────────────────────────────────────────────
COURSE_SLUG  = "illinois-tech-statistical-learning"
OUTPUT_DIR   = Path("/Users/ellenlee/Library/CloudStorage/OneDrive-ESMTBerlin/data_science/courses/statistical-learning/videos")
LINKS_FILE   = OUTPUT_DIR / "video_links.json"
WAIT_TIMEOUT = 10   # seconds to wait for page elements
# ──────────────────────────────────────────────────────────────────────────────


def make_driver(headless: bool = False) -> webdriver.Chrome:
    """Create a Chrome WebDriver (visible by default so you can handle MFA/CAPTCHA)."""
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_experimental_option("detach", False)
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def login(driver: webdriver.Chrome, email: str, password: str):
    """
    Navigate to the course landing page, click 'Log in', complete the
    two-step login form, then click 'Go to course'.
    Waits up to 2 min for CAPTCHA/MFA if needed.
    """
    course_url = f"https://www.coursera.org/learn/{COURSE_SLUG}?authMode=login"
    print(f"[*] Opening course page: {course_url}")
    driver.get(course_url)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    time.sleep(3)

    # Click the "Log in" button on the course landing page
    try:
        login_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space(text())='Log in'] | //a[normalize-space(text())='Log in']")
        ))
        login_btn.click()
        print("[*] Clicked 'Log in'.")
        time.sleep(3)
    except TimeoutException:
        print("[*] No 'Log in' button found — may already be showing the login form.")

    # Step 1: email — wait until clickable, then click to focus before typing
    email_field = wait.until(EC.element_to_be_clickable((By.NAME, "email")))
    email_field.click()
    email_field.clear()
    email_field.send_keys(email)
    email_field.submit()
    time.sleep(10)

    # Step 2: password (appears after email submission)
    pwd_field = wait.until(EC.element_to_be_clickable((By.NAME, "password")))
    pwd_field.click()
    pwd_field.clear()
    pwd_field.send_keys(password)
    pwd_field.submit()

    # Wait for login to complete (URL leaves the login/authMode flow)
    try:
        WebDriverWait(driver, 30).until(
            lambda d: "authMode=login" not in d.current_url and "login" not in d.current_url
        )
        time.sleep(3)
    except TimeoutException:
        time.sleep(120)  # extra wait for CAPTCHA / MFA
        if "login" in driver.current_url:
            raise RuntimeError("Login failed – check credentials or solve CAPTCHA manually.")

    print("[+] Logged in successfully.")


def navigate_to_course(driver: webdriver.Chrome):
    """
    Click 'Go to course' (or Resume / Continue) on the course landing page.
    Falls back to navigating directly to the course home URL.
    """
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    print("[*] Looking for 'Go to course' / 'Resume' button …")

    course_home = f"https://www.coursera.org/learn/{COURSE_SLUG}/home/"

    try:
        go_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button[data-e2e='enroll-button']")
        ))
        print(f"[+] Clicking '{go_btn.text.strip()}' …")
        go_btn.click()
    except TimeoutException:
        print(f"[*] Button not found — navigating directly to course home: {course_home}")
        driver.get(course_home)

    time.sleep(4)
    print(f"[+] Course page: {driver.current_url}")


def collect_video_item_links(driver: webdriver.Chrome) -> List[Tuple[str, str]]:
    """
    Iterate modules 1–9, collect all lecture links (href contains '/lecture/').
    Only video items use /lecture/ in their URL; readings use /supplement/,
    quizzes use /quiz/ — so this naturally filters to videos only.
    Returns list of (title, url) in module order.
    """
    all_links: List[Tuple[str, str]] = []
    seen: set = set()

    for module_num in range(1, 10):
        module_url = (
            f"https://www.coursera.org/learn/{COURSE_SLUG}"
            f"/home/module/{module_num}"
        )
        print(f"[*] Scanning module {module_num} …")
        driver.get(module_url)
        time.sleep(4)

        # Expand any collapsed sections within this module
        toggles = driver.find_elements(By.CSS_SELECTOR, "button[aria-expanded='false']")
        for t in toggles:
            try:
                driver.execute_script("arguments[0].click();", t)
                time.sleep(0.3)
            except Exception:
                pass
        time.sleep(2)

        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/lecture/']")
        module_links = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            title = a.text.strip() or href.split("/")[-1]
            if href and href not in seen:
                seen.add(href)
                module_links.append((title, href))

        print(f"    → {len(module_links)} video(s) found in module {module_num}.")
        all_links.extend(module_links)

    print(f"[+] Total: {len(all_links)} video(s) across all modules.")
    return all_links


def extract_download_links(driver: webdriver.Chrome, title: str, item_url: str) -> Optional[Dict]:
    """
    Visit a lecture page, click the Downloads tab, and extract:
      - video URL (720p preferred) + filename
      - transcript URL + filename (named after the lecture title)
    Returns a dict or None if the Downloads tab / video link is not found.
    """
    driver.get(item_url)
    time.sleep(6)

    # Click the "Downloads" tab
    try:
        downloads_tab = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 "//span[contains(@class,'cds-tab-wrapper')"
                 " and normalize-space(text())='Downloads']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", downloads_tab)
        downloads_tab.click()
        print("  [*] Clicked 'Downloads' tab.")
        time.sleep(3)
    except TimeoutException:
        print("  [!] 'Downloads' tab not found — skipping.")
        return None

    # ── Video URL (720p preferred) ────────────────────────────────────────────
    video_url = ""
    video_filename = ""
    for selector in [
        "a[data-track-component='download_video'][href*='720p']",
        "a[data-click-key*='download_video'][href*='720p']",
        "a[download][href*='720p']",
        "a[data-track-component='download_video']",
        "a[data-click-key*='download_video']",
        "a[download][href*='cloudfront.net']",
    ]:
        anchors = driver.find_elements(By.CSS_SELECTOR, selector)
        for a in anchors:
            u = a.get_attribute("href") or ""
            f = a.get_attribute("download") or ""
            if u and f:
                video_url, video_filename = u, f
                print(f"  [✓] Video matched: {selector}")
                break
        if video_url:
            break

    if not video_url:
        print("  [!] No video download link found.")
        return None

    # ── Transcript URL ────────────────────────────────────────────────────────
    transcript_url = ""
    transcript_filename = ""
    for selector in [
        "a[data-track-component='focused_lex_download_transcript']",
        "a[data-click-key*='download_transcript']",
        "a[download='transcript.txt']",
    ]:
        anchors = driver.find_elements(By.CSS_SELECTOR, selector)
        for a in anchors:
            href = a.get_attribute("href") or ""
            if href:
                # href may be relative (/api/...) — make it absolute
                if href.startswith("/"):
                    href = "https://www.coursera.org" + href
                transcript_url = href
                transcript_filename = sanitise_filename(title) + ".txt"
                print(f"  [✓] Transcript matched: {selector}")
                break
        if transcript_url:
            break

    return {
        "title":               title,
        "video_url":           video_url,
        "video_filename":      video_filename,
        "transcript_url":      transcript_url,
        "transcript_filename": transcript_filename,
    }


def sanitise_filename(name: str) -> str:
    """Strip characters unsafe in file/folder names."""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip(". ")[:200]


def already_downloaded(filename: str, out_dir: Path) -> bool:
    """Return True if the file already exists in out_dir."""
    return (out_dir / sanitise_filename(filename)).exists()


def download_file(url: str, filename: str, out_dir: Path):
    """
    Download a signed CloudFront URL to out_dir.
    The URL is self-authenticating (signature is in the query string).
    """
    safe = sanitise_filename(filename)
    dest = out_dir / safe
    print(f"  [↓] Downloading: {safe}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        print(f"\r    {downloaded / total * 100:.1f}%", end="", flush=True)
        print()

    print(f"  [✓] Saved: {safe}")


def save_links(items: List[Dict]):
    """Save extracted video/transcript info to LINKS_FILE as JSON."""
    with open(LINKS_FILE, "w") as f:
        json.dump(items, f, indent=2)
    print(f"[+] Saved {len(items)} item(s) to {LINKS_FILE}")


def load_links() -> List[Dict]:
    """Load video/transcript info from LINKS_FILE."""
    with open(LINKS_FILE) as f:
        items = json.load(f)
    print(f"[+] Loaded {len(items)} item(s) from {LINKS_FILE} — skipping browser scan.")
    return items


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: scan (only if links file doesn't exist) ─────────────────────
    if LINKS_FILE.exists():
        items = load_links()
    else:
        email    = input("Coursera email: ").strip()
        password = getpass.getpass("Coursera password: ")

        driver = make_driver(headless=False)
        try:
            login(driver, email, password)
            navigate_to_course(driver)
            lecture_links = collect_video_item_links(driver)

            if not lecture_links:
                print("[!] No lecture links found. The page structure may have changed.")
                return

            print(f"\n[*] Extracting download URLs for {len(lecture_links)} lecture(s) …\n")
            items = []
            for idx, (title, lecture_url) in enumerate(lecture_links, 1):
                print(f"\n── [{idx}/{len(lecture_links)}] {title}")
                result = extract_download_links(driver, title, lecture_url)
                if result:
                    items.append(result)
                else:
                    print("  [→] Skipped (no download links found).")
        finally:
            driver.quit()

        if not items:
            print("[!] No downloadable items found.")
            return

        save_links(items)

    # ── Phase 2: download video + transcript (requests only, no browser) ──────
    print(f"\n[*] Downloading {len(items)} item(s) to: {OUTPUT_DIR}\n")

    downloaded_videos = 0
    downloaded_transcripts = 0

    for idx, item in enumerate(items, 1):
        title               = item["title"]
        video_url           = item.get("video_url", "")
        video_filename      = item.get("video_filename", "")
        transcript_url      = item.get("transcript_url", "")
        transcript_filename = item.get("transcript_filename", "")

        print(f"\n── [{idx}/{len(items)}] {title}")

        if video_url and video_filename:
            if already_downloaded(video_filename, OUTPUT_DIR):
                print(f"  [→] Video already exists, skipping.")
            else:
                download_file(video_url, video_filename, OUTPUT_DIR)
                downloaded_videos += 1

        if transcript_url and transcript_filename:
            if already_downloaded(transcript_filename, OUTPUT_DIR):
                print(f"  [→] Transcript already exists, skipping.")
            else:
                download_file(transcript_url, transcript_filename, OUTPUT_DIR)
                downloaded_transcripts += 1

        time.sleep(1)

    print(f"\n[*] Done. Videos: {downloaded_videos} new, Transcripts: {downloaded_transcripts} new.")


if __name__ == "__main__":
    main()
