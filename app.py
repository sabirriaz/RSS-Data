from flask import Flask, jsonify, request, current_app
from flask_cors import CORS
import feedparser
import requests, concurrent.futures
from bs4 import BeautifulSoup
import logging
import os
import feedparser
import html
from flask_cors import CORS
from dateutil import parser as dateparse
import datetime as dt
import csv, io, time, socket
import xml.etree.ElementTree as ET
import re
from datetime import datetime
import json
from xml.etree import ElementTree
from datetime import datetime
# from senate_calendar_scraper import fetch_senate_calendar
import nest_asyncio
import requests, ics
from bs4 import BeautifulSoup
import requests, xml.etree.ElementTree as ET
from waitress import serve
from requests_html import HTMLSession
import subprocess, time, json, sys, signal
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import urllib.parse
from contextlib import suppress
import nest_asyncio, asyncio
nest_asyncio.apply()
asyncio.set_event_loop(asyncio.new_event_loop())
import os

app = Flask(__name__)
CORS(app)  

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def safe_get_json(url: str, *, params: dict | None = None, timeout: int = 15):
    "Generic JSON fetcher with graceful error handling."
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch from {url}: {e}"}

app = Flask(__name__)
CORS(app, resources={
    r"/pm_updates": {"origins": "https://transparencyproject.ca"},
    r"/bills": {"origins": "https://transparencyproject.ca"},
    r"/*": {"origins": "https://transparencyproject.ca"},
})

def is_valid_date(date_str):
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    return bool(re.match(pattern, date_str))

def fetch_pm_updates():
    """Fetch PM updates from RSS feed - WORKING"""
    try:
        feed = feedparser.parse('https://www.pm.gc.ca/en/news.rss')
        updates = []
        for entry in feed.entries:
            updates.append({
                'title': entry.title,
                'summary': entry.summary,
                'link': entry.link,
                'published': entry.published
            })
        return updates
    except Exception as e:
        return {'error': f'Failed to fetch PM updates: {str(e)}'}

def fetch_bills():
    """Fetch bills from Parliament API - WORKING"""
    try:
        url = 'https://www.parl.ca/legisinfo/en/bills/json'
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return {'error': 'Failed to fetch bills'}
    except Exception as e:
        return {'error': f'Failed to fetch bills: {str(e)}'}

def fetch_mps():
    """Fetch MPs from Represent API - CORRECTED URL"""
    try:
        url = 'https://represent.opennorth.ca/representatives/?elected_office=MP&limit=500'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            mps = []
            
            for mp in data.get('objects', []):
                offices = []
                if 'offices' in mp and mp['offices']:
                    for office in mp['offices']:
                        offices.append({
                            'type': office.get('type', ''),
                            'postal': office.get('postal', ''),
                            'tel': office.get('tel', ''),
                            'fax': office.get('fax', '')
                        })
                
                mps.append({
                    'name': mp.get('name', ''),
                    'first_name': mp.get('first_name', ''),
                    'last_name': mp.get('last_name', ''),
                    'party_name': mp.get('party_name', ''),
                    'district_name': mp.get('district_name', ''),
                    'elected_office': mp.get('elected_office', ''),
                    'email': mp.get('email', ''),
                    'url': mp.get('url', ''),
                    'source_url': mp.get('source_url', ''),
                    'photo_url': mp.get('photo_url', ''),
                    'personal_url': mp.get('personal_url', ''),
                    'gender': mp.get('gender', ''),
                    'district_id': mp.get('district_id', ''),
                    'offices': offices,
                    'extra': mp.get('extra', {})
                })
            
            return {
                'total_count': data.get('meta', {}).get('total_count', len(mps)),
                'next': data.get('meta', {}).get('next'),
                'previous': data.get('meta', {}).get('previous'),
                'mps': mps
            }
        
        return {'error': f'Failed to fetch MPs - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch MPs: {str(e)}'}


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)
HEADERS = {"User-Agent": UA}

# ---------- helper: profile‑page scraper ----------
def _enrich_senator(sen):
    """Profile‑page se province, division, party bhar de."""
    try:
        r = requests.get(sen["profile_url"], headers=HEADERS, timeout=10)
        r.raise_for_status()
        psoup = BeautifulSoup(r.text, "html.parser")

        province = division = party = ""

        for li in psoup.select("li"):
            text = li.get_text(" ", strip=True)
            if text.startswith("Province"):
                # “Quebec - Wellington” → province + optional division
                val = text.split(":", 1)[1].strip()
                if " - " in val:
                    province, division = [v.strip() for v in val.split(" - ", 1)]
                else:
                    province = val
            elif text.lower().startswith(("affiliation", "political affiliation", "caucus")):
                party = text.split(":", 1)[1].strip()

        sen["province"] = province
        sen["division"] = division
        sen["party"]    = party
    except Exception:
        pass
    return sen


# ---------- main ----------
def fetch_senators_from_sencanada():
    # Selenium setup
    opts = Options()
    opts.headless = True
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"user-agent={UA}")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )
    try:
        driver.get("https://sencanada.ca/en/senators/")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/en/senators/']"))
        )
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    # list page: names + links
    base = "https://sencanada.ca"
    senators = []
    for a in soup.select("a[href*='/en/senators/']"):
        href = a.get("href", "")
        if "/en/senators/" in href and href.count("/") >= 4:
            name = a.get_text(strip=True)
            if " " in name and len(name) > 4:
                senators.append(
                    {"name": name, "profile_url": base + href if href.startswith("/") else href}
                )
    senators = list({s["name"]: s for s in senators}.values())  # dedup

    # parallel‑fetch profiles (max 10 threads)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        senators = list(ex.map(_enrich_senator, senators))

    return {"total_count": len(senators), "senators": senators}

def fetch_senate_committees():
    """Fetch Senate committees - ENHANCED"""
    try:
        url = 'https://sencanada.ca/en/committees/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            committees = []
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                if ('committee' in href.lower() or 'committees' in href.lower()) and text and len(text) > 10:
                    committees.append({
                        'name': text,
                        'url': f"https://sencanada.ca{href}" if href.startswith('/') else href
                    })
            
            seen_names = set()
            unique_committees = []
            for committee in committees:
                if committee['name'] not in seen_names:
                    seen_names.add(committee['name'])
                    unique_committees.append(committee)
            
            return {
                'total_count': len(unique_committees),
                'committees': unique_committees
            }
        
        return {'error': f'Failed to fetch senate committees - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch senate committees: {str(e)}'}

def fetch_judicial_appointments():
    """Fetch judicial appointments from Justice Canada RSS - CORRECTED URL"""
    try:
        feed = feedparser.parse('https://www.justice.gc.ca/eng/news-nouv/rss/ja-nj.aspx')
        appointments = []
        for entry in feed.entries:
            title_lower = entry.title.lower()
            if any(keyword in title_lower for keyword in ['appoint', 'nomination', 'judge', 'court']):
                appointments.append({
                    'title': entry.title,
                    'summary': getattr(entry, 'summary', ''),
                    'link': entry.link,
                    'published': getattr(entry, 'published', ''),
                    'category': 'judicial_appointment'
                })
        return {
            'total_count': len(appointments),
            'appointments': appointments
        }
    except Exception as e:
        return {'error': f'Failed to fetch judicial appointments: {str(e)}'}

def fetch_global_affairs(news_type='all'):
    """Fetch general news from the Canada.ca news API."""
    try:
        base_url = 'https://api.io.canada.ca/io-server/gc/news/en/v2'
        params = {
            'pick': 500000,
            'format': 'json'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            news = []
            
            for item in data.get('feed', {}).get('entry', []):
                news.append({
                    'title': item.get('title', ''),
                    'teaser': item.get('teaser', ''),
                    'link': item.get('link', ''),
                    'publishedDate': item.get('publishedDate', ''),
                    'category': 'general_canada_news',
                    'source': 'Canada.ca News'
                })
            
            return {
                'total_count': len(news),
                'news': news
            }
        elif response.status_code == 404:
            return {'error': 'API endpoint not found or invalid. Please check the URL.'}
        else:
            return {'error': f'Failed to fetch news from Canada.ca - Status: {response.status_code}'}
    except requests.exceptions.Timeout:
        return {'error': 'Failed to fetch news from Canada.ca: Request timed out.'}
    except requests.exceptions.RequestException as e:
        return {'error': f'Failed to fetch news from Canada.ca: {str(e)}'}
    except Exception as e:
        return {'error': f'An unexpected error occurred: {str(e)}'}

def fetch_committees(parl=44, session=1):
    """
    Scrape Commons committees list from official fragment endpoint.
    """
    url = (
        "https://www.ourcommons.ca/Committees/en/List"
        f"?parl={parl}&session={session}"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        return {"error": f"Failed – Status {r.status_code}"}

    soup = BeautifulSoup(r.text, "html.parser")
    committees = []
    for li in soup.select("li.committee-list__item"):
        link_tag = li.select_one("a")
        if not link_tag:
            continue
        name = link_tag.get_text(" ", strip=True)
        href = link_tag["href"]
        if not href.startswith("http"):
            href = "https://www.ourcommons.ca" + href
        acronym = li.select_one(".committee-list__acronym")
        committees.append({
            "name": name,
            "short_name": acronym.get_text(strip=True) if acronym else "",
            "url": href
        })

    return {"total_count": len(committees), "committees": committees}

def fetch_canada_gazette():
    """
    Return ALL available items from Canada Gazette RSS feeds:
    - Part I  (Notices and Proposed Regulations)
    - Part II (Regulations)
    - Part III (Acts of Parliament)
    """
    parts = {
        "Part I":  "https://www.gazette.gc.ca/rss/p1-eng.xml",
        "Part II": "https://www.gazette.gc.ca/rss/p2-eng.xml",
        "Part III": "https://www.gazette.gc.ca/rss/en-ls-eng.xml",
    }

    publications = []

    for part_name, url in parts.items():
        feed = feedparser.parse(url)

        # Loop over *all* entries (no slicing)
        for entry in feed.entries:
            # summary کے اندر پہلا <a href="">... PDF/HTML ...</a> نکال لو
            soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
            a_tag = soup.find("a")
            link  = a_tag["href"] if a_tag and a_tag.has_attr("href") else entry.get("link", "")

            publications.append({
                "part": part_name,
                "title": entry.get("title", ""),
                "url":   link,
                "published": entry.get("published", ""),
                "type": "PDF" if link.lower().endswith(".pdf") else "HTML"
            })

    return {
        "total_count": len(publications),
        "publications": publications
    }



# app  = Flask(__name__)
# HDRS = {"User-Agent": "Mozilla/5.0"}

# # ────────────────────────────────────────────────────────────────────
# # 1. 🔹  Ek din ki speeches (Lipad)
# # --------------------------------------------------------------------
# def fetch_debate_transcripts(date: str) -> dict:
#     """Return speeches for a given date (YYYY-MM-DD)."""
#     y, m, d = date.split("-")
#     base = f"https://www.lipad.ca/api/hansard/{date}/"

#     # ❶ JSON endpoint (fastest)
#     r = requests.get(base, headers=HDRS, timeout=30)
#     if r.ok and r.headers.get("Content-Type", "").startswith("application/json"):
#         js = r.json()
#         return {
#             "date": js.get("date", date),
#             "total_count": js.get("total_count", 0),
#             "speeches": js.get("speeches", []),
#         }

#     # ❷ Fallback: HTML scrape
#     speeches, page = [], 0
#     while True:
#         url = f"https://www.lipad.ca/full/{y}/{m}/{d}" + ("/fullview" if page == 0 else f"/{page+1}")
#         r = requests.get(url, headers=HDRS, timeout=30)
#         if r.status_code != 200:
#             break
#         soup  = BeautifulSoup(r.text, "lxml")
#         main  = soup.find(id="content") or soup

#         speaker, buf = None, []
#         for el in main.find_all(["h3", "h4", "p"]):
#             t = el.get_text(" ", strip=True)
#             if el.name in {"h3", "h4"}:
#                 if speaker and buf:
#                     speeches.append({"speaker": speaker, "text": " ".join(buf)})
#                 speaker, buf = t.lstrip("#").strip(), []
#             elif el.name == "p":
#                 buf.append(t)
#         if speaker and buf:
#             speeches.append({"speaker": speaker, "text": " ".join(buf)})

#         nxt = soup.find("a", string=re.compile(r"›|Next"))
#         if nxt and nxt.get("href"):
#             page += 1
#         else:
#             break

#     return {"date": date, "total_count": len(speeches), "speeches": speeches}


def fetch_debates(date=None):
    """
    Fetches parliamentary debates from the OpenParliament API.
    Accepts optional date filter YYYY-MM-DD.
    """
    try:
        base_url = 'https://api.openparliament.ca/debates/'
        params = {}
        if date:
            if not is_valid_date(date):
                return {'error': 'Invalid date format for debates. Use YYYY-MM-DD.'}
            params['date'] = date

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        response = requests.get(base_url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            debates = []
            for debate_entry in data.get('objects', []):
                debates.append({
                    'date': debate_entry.get('date', ''),
                    'number': debate_entry.get('number', ''),
                    'most_frequent_word_en': debate_entry.get('most_frequent_word', {}).get('en', ''),
                    'url': f"https://api.openparliament.ca{debate_entry.get('url', '')}" if debate_entry.get('url', '').startswith('/') else debate_entry.get('url', '')
                })
            return {
                'total_count': data.get('pagination', {}).get('total_count', len(debates)),
                'next_page_url': data.get('pagination', {}).get('next_url'),
                'previous_page_url': data.get('pagination', {}).get('previous_url'),
                'debates': debates
            }
        elif response.status_code == 404:
            return {'error': 'No debates found for the specified date or endpoint.'}
        else:
            return {'error': f'Failed to fetch debates - Status: {response.status_code}'}
    except requests.exceptions.Timeout:
        return {'error': 'Failed to fetch debates: Request timed out.'}
    except requests.exceptions.RequestException as e:
        return {'error': f'Failed to fetch debates: {str(e)}'}
    except Exception as e:
        return {'error': f'Unexpected error while fetching debates: {str(e)}'}

app = Flask(__name__)
def fetch_legal_info(query="federal", limit=10):
    """Scrape CanLII public legal info search page"""
    try:
        base_url = "https://www.canlii.org/en/search"
        params = {
            "searchType": "text",
            "searchTitle": "",
            "searchText": query
        }
        search_url = f"{base_url}?{urllib.parse.urlencode(params)}"

        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        for li in soup.select("ol.search-results > li.result")[:limit]:
            title = li.select_one(".result_title").get_text(strip=True) if li.select_one(".result_title") else ""
            link = li.select_one("a")["href"] if li.select_one("a") else ""
            snippet = li.select_one(".snippet").get_text(" ", strip=True) if li.select_one(".snippet") else ""
            results.append({
                "title": title,
                "link": "https://www.canlii.org" + link,
                "snippet": snippet
            })

        return {
            "query": query,
            "total": len(results),
            "results": results
        }

    except Exception as e:
        return {"error": str(e)}

def fetch_access_information():
    """Static information about Access to Information"""
    return {
        'message': 'Access to Information and Privacy',
        'description': 'Information about how to access government information and protect privacy',
        'url': 'https://www.canada.ca/en/treasury-board-secretariat/services/access-information-privacy.html',
        'contact': 'Contact the relevant department directly for specific requests'
    }


def fetch_senate_calendar(limit: int = 10):
    """
    Scrape https://sencanada.ca/en/calendar/ and return latest 'Annual Calendar'
    PDF links with year label. Returns at most `limit` entries.
    """
    try:
        url = "https://sencanada.ca/en/calendar/"
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "html.parser")

        events = []
        for a in soup.find_all("a", string=re.compile(r"PDF version", re.I)):
            # The text node just before anchor usually contains the year
            year_text = a.find_previous(string=re.compile(r"\d{4} Annual Calendar"))
            year = re.search(r"\d{4}", year_text).group(0) if year_text else ""
            pdf_link = a["href"]
            if not pdf_link.startswith("http"):
                pdf_link = "https://sencanada.ca" + pdf_link
            events.append({
                "year": year,
                "type": "Annual Calendar PDF",
                "link": pdf_link
            })
            if len(events) >= limit:
                break

        return {"total": len(events), "events": events}

    except Exception as e:
        return {"error": f"Failed to fetch Senate calendar PDFs: {e}"}

def fetch_bills_legislation():
    """
    Alias of the /bills feed but exposed under /bills_legislation
    to satisfy your endpoint list.
    """
    return fetch_bills()  # you already wrote this


def fetch_parliamentary_docs():
    """
    Pulls the top 20 'parliamentary documents' datasets
    from the federal CKAN API on open.canada.ca.
    """
    url = "https://open.canada.ca/data/api/3/action/package_search"
    params = {"q": "parliamentary documents", "rows": 20}
    data = safe_get_json(url, params=params)
    if "result" in data:
        docs = [
            {
                "title": d.get("title", ""),
                "id": d.get("id", ""),
                "organization": d.get("organization", {}).get("title", ""),
                "modified": d.get("metadata_modified", ""),
                "resources": [
                    r.get("url") for r in d.get("resources", []) if r.get("url")
                ],
            }
            for d in data["result"].get("results", [])
        ]
        return {"count": len(docs), "docs": docs}
    return data


def fetch_senate_orders(limit: int = 30):
    """
    1️⃣  Calendar page se saare date‑links nikaalta hai  
    2️⃣  Har date page open karke .pdf ka direct link pull karta hai  
    3️⃣  Pehle 30 results return karta hai
    """
    base = "https://sencanada.ca"
    cal_url = f"{base}/en/in-the-chamber/order-papers-notice-papers/"
    try:
        cal_html = requests.get(cal_url, headers=HEADERS, timeout=15).text
    except Exception as e:
        return {"error": f"Calendar page load failed: {e}"}

    soup = BeautifulSoup(cal_html, "html.parser")

    # --- Step 1: all calendar <a> links (relative paths) -----------
    date_links = [
        a["href"].replace("\\", "/")               # back‑slash ko slash
        for a in soup.select("table.sc-in-the-chamber-calendar-table a[href]")
    ][:limit]                                      # zyada links ki zaroorat nahin

    pdfs = []
    seen = set()

    # --- Step 2: visit each date page and pull .pdf ---------------
    for rel in date_links:
        page_url = rel if rel.startswith("http") else base + rel
        try:
            page_html = requests.get(page_url, headers=HEADERS, timeout=15).text
        except Exception:
            continue

        # find first .pdf in this page
        for href in re.findall(r'"([^"]+\.pdf[^"]*)"', page_html, re.I):
            full = href if href.startswith("http") else base + href
            if full in seen:
                continue
            seen.add(full)

            title = full.split("/")[-1]  # file name as title
            pdfs.append({"title": title, "link": full})
            break                        # ek hi pdf ek date page se

        if len(pdfs) >= limit:
            break

    return {"count": len(pdfs), "pdfs": pdfs}


# def fetch_federal_procurement():
#     """
#     Grabs the most recent tender notices from the CanadaBuys
#     open‑data endpoint (JSON).
#     """
#     url = (
#         "https://open.canada.ca/data/api/3/action/package_show"
#         "?id=6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2"  # CanadaBuys tender notices
#     )
#     data = safe_get_json(url)
#     if "result" in data:
#         rec = data["result"]
#         return {
#             "title": rec.get("title"),
#             "modified": rec.get("metadata_modified"),
#             "resources": [
#                 r.get("url") for r in rec.get("resources", []) if r.get("url")
#             ],
#         }
#     return data



BROWSER_HDRS = {
    # Cloudflare usually needs a UA + Accept + Accept-Language
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

def _clean_row(row: dict) -> dict:
    """Remove blank/None keys so Flask jsonify() won't choke."""
    return {k.strip(): v for k, v in row.items() if k and k.strip()}

def _get_json(url: str, **params):
    r = requests.get(url, params=params, timeout=30, headers=BROWSER_HDRS)
    r.raise_for_status()
    return r.json()

def _get_text(url: str) -> str:
    r = requests.get(url, timeout=60, headers=BROWSER_HDRS)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")   # handles BOM

# ---------------------------------------------------------------------------
# Main fetcher
# ---------------------------------------------------------------------------
def fetch_federal_procurement(limit: int = 100) -> dict:
    """
    CanadaBuys ≥ 2025 tender notices ko JSON me return karta hai.
    ❶ DataStore JSON agar available
    ❷ Warna CSV download with Cloudflare‑friendly headers
    """
    PACKAGE_ID = "6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2"
    BASE  = "https://open.canada.ca/data/api/3/action"

    # 1️⃣ Dataset meta
    meta = _get_json(f"{BASE}/package_show", id=PACKAGE_ID).get("result", {})
    resources = meta.get("resources", [])

    # 2️⃣ Try a DataStore‑enabled resource first
    ds_res = next((r for r in resources if r.get("datastore_active")), None)
    if ds_res:
        ds_url = (
            f"{BASE}/datastore_search"
            f"?resource_id={ds_res['id']}&limit={limit}"
        )
        ds_data = _get_json(ds_url)["result"]
        return {
            "source": ds_url,
            "modified": meta.get("metadata_modified"),
            "total": ds_data["total"],
            "notices": ds_data["records"],
        }

    # 3️⃣ Pick best CSV (open tenders preferred)
    csv_res = next(
        (
            r for r in resources
            if r.get("format", "").upper() == "CSV"
            and "opentendernotice" in (r.get("name") or "").lower()
        ),
        None,
    ) or next(                 # fallback: first CSV in list
        (r for r in resources if r.get("format", "").upper() == "CSV"),
        None,
    )
    if not csv_res:
        return {"error": "No suitable CSV or DataStore resource found."}

    csv_text = _get_text(csv_res["url"])
    reader = csv.DictReader(io.StringIO(csv_text))

    notices = [_clean_row(row) for _, row in zip(range(limit), reader)]

    return {
        "source": csv_res["url"],
        "modified": meta.get("metadata_modified"),
        "total": len(notices),
        "notices": notices,
    }


def fetch_federal_contracts():
    """
    Uses the Proactive Contracts dataset (consolidated contract
    publication reports) and returns basic metadata.
    """
    dataset_id = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
    url = f"https://open.canada.ca/data/api/3/action/package_show?id={dataset_id}"
    data = safe_get_json(url)
    if "result" in data:
        rec = data["result"]
        return {
            "title": rec.get("title"),
            "modified": rec.get("metadata_modified"),
            "resources": [
                r.get("url") for r in rec.get("resources", []) if r.get("url")
            ],
        }
    return data



def fetch_canadian_news(limit=10):
    headers = {"User-Agent": "Mozilla/5.0"}
    feed_url = "https://www.villagereport.ca/feed"
    try:
        import feedparser
        feed = feedparser.parse(feed_url)
        if feed.bozo == 0 and feed.entries:
            articles = []
            for e in feed.entries[:limit]:
                summary = BeautifulSoup(getattr(e, "summary", ""), "html.parser").get_text(" ", strip=True)
                articles.append({"title": e.title, "summary": summary, "link": e.link})
            return {"source": feed_url, "count": len(articles), "articles": articles}
    except Exception:
        pass

    # Fallback: scrape homepage
    url = "https://www.villagereport.ca"
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    articles = []
    for card in soup.select("div.widget-area div.card")[:limit]:
        a = card.find("a", href=True)
        if not a: continue
        title = a.get_text(" ", strip=True)
        link = a["href"]
        if not link.startswith("http"):
            link = url.rstrip("/") + link
        articles.append({"title": title, "summary": "", "link": link})
    return {"source": url, "count": len(articles), "articles": articles}

def fetch_bc_procurement():
    """
    Returns open opportunities scraped from the BC Bid public
    search page (HTML).
    NOTE: BC Bid has no unauthenticated JSON endpoint, so we
    just grab the first table rows the public site exposes.
    """
    try:
        url = "https://www.bcbid.gov.bc.ca/page.aspx/en/oa/allOpportunitiesList"
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")
        opps = []
        for row in rows[:50]:
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) >= 5:
                opps.append(
                    {
                        "opportunity_no": cols[0],
                        "description": cols[1],
                        "organization": cols[2],
                        "closing_date": cols[3],
                        "status": cols[4],
                    }
                )
        return {"total": len(opps), "opportunities": opps}
    except Exception as e:
        return {"error": f"Failed to scrape BC Bid: {e}"}


def fetch_municipal_councillors(limit=500):
    """
    Calls the Represent API and returns all elected municipal
    councillors (up to `limit`).
    """
    url = "https://represent.opennorth.ca/representatives/"
    params = {"elected_office": "Councillor", "limit": limit}
    return safe_get_json(url, params=params)


def fetch_committee_reports(limit: int = 40):
    FEED = "https://www.ourcommons.ca/Committees/en/AllReports/RSS?format=RSS"
    try:
        parsed = feedparser.parse(FEED)
        items = [
            {
                "title": e.title,
                "link": e.link,
                "published": e.published,
                "description": BeautifulSoup(e.summary, "html.parser").get_text(),
            }
            for e in parsed.entries[:limit]
        ]
        return {"source": FEED, "count": len(items), "reports": items}
    except Exception as e:
        return {"error": f"Committee reports RSS error: {e}"}

def fetch_victoria_procurement():
    feed = "https://victoria.bonfirehub.ca/opportunities/rss"
    try:
        parsed = feedparser.parse(feed)
        items = []

        for e in parsed.entries:
            raw_title = html.unescape(getattr(e, "title", ""))

            # 1️⃣  Bonfire feeds jahan ". Name:" ho
            if ". Name:" in raw_title:
                ref_no, title = [part.strip() for part in raw_title.split(". Name:", 1)]

            # 2️⃣  Agar kabhī " | " separator mil jāy
            elif " | " in raw_title:
                parts = [p.strip() for p in raw_title.split(" | ")]
                ref_no, title = parts[0], " | ".join(parts[1:])

            # 3️⃣  Fallback: pūrā string ref_no, title empty
            else:
                ref_no, title = raw_title, ""

            # 4️⃣  Agar phir bhī title khālī ho to summary le lo
            if not title:
                title = html.unescape(getattr(e, "summary", "")).strip()

            items.append(
                {
                    "ref_no": ref_no,
                    "title": title,
                    "link": e.link,
                    "published": getattr(e, "published", ""),
                }
            )

        return {"source": feed, "total": len(items), "opportunities": items}

    except Exception as ex:
        return {"error": f"Victoria procurement fetch failed: {ex}"}
    
@app.route('/pm_updates', methods=['GET'])
def pm_updates_route():
    return jsonify(fetch_pm_updates())

@app.route('/bills', methods=['GET'])
def bills_route():
    return jsonify(fetch_bills())

@app.route('/mps', methods=['GET'])
def mps_route():
    return jsonify(fetch_mps())

@app.route("/senators", methods=["GET"])
def senators_route():
    return jsonify(fetch_senators_from_sencanada())

@app.route('/senate_committees', methods=['GET'])
def senate_committees_route():
    return jsonify(fetch_senate_committees())

@app.route('/judicial_appointments', methods=['GET'])
def judicial_appointments_route():
    return jsonify(fetch_judicial_appointments())

@app.route('/global_affairs', methods=['GET'])
def global_affairs_route():
    news_type = request.args.get('type', 'all')
    return jsonify(fetch_global_affairs(news_type))

@app.route("/committees", methods=["GET"])
def committees_route():
    return jsonify(fetch_committees())

@app.route("/canada_gazette", methods=["GET"])
def canada_gazette_route():
    return jsonify(fetch_canada_gazette()), 200

# @app.route("/debate_transcripts")
# def route_transcripts():
#     date = request.args.get("date")
#     if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
#         return jsonify({"error": "?date=YYYY-MM-DD missing/invalid"}), 400
#     return jsonify(fetch_debate_transcripts(date))

@app.route('/debates', methods=['GET'])
def debates_route():
    date = request.args.get('date')
    return jsonify(fetch_debates(date))

@app.route("/legal_info", methods=["GET"])
def legal_info_route():
    query = request.args.get("query", "federal")
    return jsonify(fetch_legal_info(query=query))

@app.route('/access_information', methods=['GET'])
def access_information_route():
    return jsonify(fetch_access_information())

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'available_endpoints': [
            '/pm_updates',
            '/bills', 
            '/mps',
            '/senators',
            '/senate_committees',
            '/judicial_appointments',
            '/global_affairs',
            '/committees',
            '/canada_gazette',
            '/debates',
            '/debates/<date>',
            '/legal_info',
            '/access_information',
            '/federal_procurement',
            '/federal_contracts',
        ]
    })

@app.route("/senate_calendar", methods=["GET"])
def senate_calendar_route():
    data = fetch_senate_calendar()
    return jsonify(data), 200 if "error" not in data else 500

@app.route("/bills_legislation", methods=["GET"])
def bills_legislation_route():
    return jsonify(fetch_bills_legislation())

@app.route("/parliamentary_docs", methods=["GET"])
def parliamentary_docs_route():
    return jsonify(fetch_parliamentary_docs())

@app.route("/senate_orders", methods=["GET"])
def senate_orders_route():
    return jsonify(fetch_senate_orders())

@app.route("/federal_procurement", methods=["GET"])
def federal_procurement_route():
    return jsonify(fetch_federal_procurement())

@app.route("/federal_contracts", methods=["GET"])
def federal_contracts_route():
    return jsonify(fetch_federal_contracts())

@app.route("/canadian_news", methods=["GET"])
def canadian_news_route():
    return jsonify(fetch_canadian_news())

@app.route("/bc_procurement", methods=["GET"])
def bc_procurement_route():
    return jsonify(fetch_bc_procurement())

@app.route("/municipal_councillors", methods=["GET"])
def municipal_councillors_route():
    limit = int(request.args.get("limit", 500))
    return jsonify(fetch_municipal_councillors(limit=limit))

@app.route("/committee_reports", methods=["GET"])
def committee_reports_route():
    return jsonify(fetch_committee_reports())

@app.route("/victoria_procurement", methods=["GET"])
def victoria_procurement_route():
    return jsonify(fetch_victoria_procurement())

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=False)


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=5000)

if __name__ == "__main__":
    app.run(debug=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)    
