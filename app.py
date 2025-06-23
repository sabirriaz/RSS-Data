from flask import Flask, jsonify, request
from flask_cors import CORS
import feedparser
import requests
from bs4 import BeautifulSoup
import logging
import os
import html
from dateutil import parser as dateparse
import datetime as dt
import csv
import io
import time
import socket
import xml.etree.ElementTree as ET
import re
from datetime import datetime
import json
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import urllib.parse
from contextlib import suppress
import nest_asyncio
import asyncio
import ics
from requests_html import HTMLSession
from waitress import serve

nest_asyncio.apply()
asyncio.set_event_loop(asyncio.new_event_loop())

app = Flask(__name__)

# Configure CORS to allow all origins and necessary headers
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def safe_get_json(url: str, *, params: dict | None = None, timeout: int = 15):
    """Generic JSON fetcher with graceful error handling."""
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch from {url}: {e}"}

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

def _enrich_senator(sen):
    """Profile-page scraper for senator details."""
    try:
        r = requests.get(sen["profile_url"], headers=HEADERS, timeout=10)
        r.raise_for_status()
        psoup = BeautifulSoup(r.text, "html.parser")

        province = division = party = ""

        for li in psoup.select("li"):
            text = li.get_text(" ", strip=True)
            if text.startswith("Province"):
                val = text.split(":", 1)[1].strip()
                if " - " in val:
                    province, division = [v.strip() for v in val.split(" - ", 1)]
                else:
                    province = val
            elif text.lower().startswith(("affiliation", "political affiliation", "caucus")):
                party = text.split(":", 1)[1].strip()

        sen["province"] = province
        sen["division"] = division
        sen["party"] = party
    except Exception:
        pass
    return sen

def fetch_senators_from_sencanada():
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
    senators = list({s["name"]: s for s in senators}.values())

    with ThreadPoolExecutor(max_workers=10) as ex:
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

import requests
from bs4 import BeautifulSoup

def fetch_judicial_appointments():
    try:
        # Step 1: Scrape RSS link from HTML
        index_url = "https://www.justice.gc.ca/eng/news-nouv/rss.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(index_url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Step 2: Get the Judicial Appointments RSS URL
        link_tag = soup.find("a", string=lambda s: s and "Judicial Appointments" in s)
        if not link_tag:
            return {"error": "Judicial Appointments RSS link not found."}

        rss_url = link_tag.get("href")
        if not rss_url.startswith("http"):
            rss_url = "https://www.justice.gc.ca" + rss_url

        # Step 3: Fetch and parse the RSS feed manually
        rss_response = requests.get(rss_url, headers=headers, timeout=15)
        rss_response.raise_for_status()
        rss_soup = BeautifulSoup(rss_response.content, "xml")
        items = rss_soup.find_all("item")

        appointments = []
        for item in items:
            appointments.append({
                "title": item.title.text if item.title else "",
                "summary": item.description.text if item.description else "",
                "link": item.link.text if item.link else "",
                "published": item.pubDate.text if item.pubDate else "",
                "category": "judicial_appointment"
            })

        return {
            "rss_source": rss_url,
            "total_count": len(appointments),
            "appointments": appointments
        }

    except Exception as e:
        return {"error": f"Failed to fetch judicial appointments: {str(e)}"}

def fetch_committees(parl=44, session=1):
    """Scrape Commons committees list from official fragment endpoint."""
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

import requests
import feedparser
from bs4 import BeautifulSoup

def fetch_canada_gazette():
    """Return ALL available items from Canada Gazette RSS feeds."""
    parts = {
        "Part I": "https://www.gazette.gc.ca/rss/p1-eng.xml",
        "Part II": "https://www.gazette.gc.ca/rss/p2-eng.xml",
        "Part III": "https://www.gazette.gc.ca/rss/en-ls-eng.xml",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"  # simulate browser
    }

    publications = []

    for part_name, url in parts.items():
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            feed = feedparser.parse(response.content)  # important: use response.content
            print(f"[{part_name}] Entries fetched: {len(feed.entries)}")

            for entry in feed.entries:
                soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
                a_tag = soup.find("a")
                link = a_tag["href"] if a_tag and a_tag.has_attr("href") else entry.get("link", "")

                publications.append({
                    "part": part_name,
                    "title": entry.get("title", ""),
                    "url": link,
                    "published": entry.get("published", ""),
                    "type": "PDF" if link.lower().endswith(".pdf") else "HTML"
                })
        except Exception as e:
            print(f"❌ Error in {part_name}: {e}")

    print(f"✅ Total items collected: {len(publications)}")
    return {
        "total_count": len(publications),
        "publications": publications
    }

def fetch_debates(date=None):
    """Fetches parliamentary debates from the OpenParliament API."""
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

def fetch_legal_info(query="federal", limit=10):
    """Scrape CanLII public legal info search page."""
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
    """Static information about Access to Information."""
    return {
        'message': 'Access to Information and Privacy',
        'description': 'Information about how to access government information and protect privacy',
        'url': 'https://www.canada.ca/en/treasury-board-secretariat/services/access-information-privacy.html',
        'contact': 'Contact the relevant department directly for specific requests'
    }

import requests
from bs4 import BeautifulSoup
import re

def fetch_senate_calendar(limit: int = 10):
    """Scrape Senate calendar for Annual Calendar PDF links with proper text and year."""
    try:
        url = "https://sencanada.ca/en/calendar/"
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "html.parser")
        events = []

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.endswith(".pdf") and "calendar" in href.lower():
                # Get parent element text (like h3 or p) which may include the year
                parent_block = link.find_parent()
                context_text = parent_block.get_text(separator=" ", strip=True) if parent_block else ""
                
                # Extract the year from context
                year_match = re.search(r"\b(20\d{2})\b", context_text)
                year = year_match.group(0) if year_match else ""

                # Clean link text
                link_text = link.get_text(strip=True)
                if len(link_text) < 5 or link_text.lower() == "pdf version":
                    # Replace with context if link text is too short or generic
                    text = context_text
                else:
                    text = link_text

                full_link = href if href.startswith("http") else "https://sencanada.ca" + href

                events.append({
                    "year": year,
                    "text": text,
                    "type": "Annual Calendar PDF",
                    "link": full_link
                })

                if len(events) >= limit:
                    break

        return {"total": len(events), "events": events}

    except Exception as e:
        return {"error": f"Failed to fetch Senate calendar PDFs: {e}"}

def fetch_bills_legislation():
    """Alias of the /bills feed."""
    return fetch_bills()

def fetch_parliamentary_docs():
    """Pulls top 20 parliamentary documents from CKAN API."""
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
    """Scrape Senate order papers and notice papers."""
    base = "https://sencanada.ca"
    cal_url = f"{base}/en/in-the-chamber/order-papers-notice-papers/"
    try:
        cal_html = requests.get(cal_url, headers=HEADERS, timeout=15).text
    except Exception as e:
        return {"error": f"Calendar page load failed: {e}"}

    soup = BeautifulSoup(cal_html, "html.parser")
    date_links = [
        a["href"].replace("\\", "/")
        for a in soup.select("table.sc-in-the-chamber-calendar-table a[href]")
    ][:limit]

    pdfs = []
    seen = set()

    for rel in date_links:
        page_url = rel if rel.startswith("http") else base + rel
        try:
            page_html = requests.get(page_url, headers=HEADERS, timeout=15).text
        except Exception:
            continue

        for href in re.findall(r'"([^"]+\.pdf[^"]*)"', page_html, re.I):
            full = href if href.startswith("http") else base + href
            if full in seen:
                continue
            seen.add(full)

            title = full.split("/")[-1]
            pdfs.append({"title": title, "link": full})
            break

        if len(pdfs) >= limit:
            break

    return {"count": len(pdfs), "pdfs": pdfs}

BROWSER_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

def _clean_row(row: dict) -> dict:
    """Remove blank/None keys for Flask jsonify()."""
    return {k.strip(): v for k, v in row.items() if k and k.strip()}

def _get_json(url: str, **params):
    r = requests.get(url, params=params, timeout=30, headers=BROWSER_HDRS)
    r.raise_for_status()
    return r.json()

def _get_text(url: str) -> str:
    r = requests.get(url, timeout=60, headers=BROWSER_HDRS)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")

def fetch_federal_procurement(limit: int = 100) -> dict:
    """Fetch CanadaBuys tender notices."""
    PACKAGE_ID = "6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2"
    BASE = "https://open.canada.ca/data/api/3/action"

    meta = _get_json(f"{BASE}/package_show", id=PACKAGE_ID).get("result", {})
    resources = meta.get("resources", [])

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

    csv_res = next(
        (
            r for r in resources
            if r.get("format", "").upper() == "CSV"
            and "opentendernotice" in (r.get("name") or "").lower()
        ),
        None,
    ) or next(
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
    """Fetch Proactive Contracts dataset."""
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
        feed = feedparser.parse(feed_url)
        if feed.bozo == 0 and feed.entries:
            articles = []
            for e in feed.entries[:limit]:
                summary = BeautifulSoup(getattr(e, "summary", ""), "html.parser").get_text(" ", strip=True)
                articles.append({"title": e.title, "summary": summary, "link": e.link})
            return {"source": feed_url, "count": len(articles), "articles": articles}
    except Exception:
        pass

    url = "https://www.villagereport.ca"
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    articles = []
    for card in soup.select("div.widget-area div.card")[:limit]:
        a = card.find("a", href=True)
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        link = a["href"]
        if not link.startswith("http"):
            link = url.rstrip("/") + link
        articles.append({"title": title, "summary": "", "link": link})
    return {"source": url, "count": len(articles), "articles": articles}

def fetch_bc_procurement():
    """Scrape BC Bid open opportunities."""
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
    """Fetch municipal councillors from Represent API."""
    url = "https://represent.opennorth.ca/representatives/"
    params = {"elected_office": "Councillor", "limit": limit}
    return safe_get_json(url, params=params)

import requests
import feedparser
from bs4 import BeautifulSoup

def fetch_committee_reports():
    """Fetch committee-related news articles from the Commons News RSS."""
    url = "https://www.ourcommons.ca/publicationsearch/en/?PubType=37"
    
    try:
        feed = feedparser.parse(url)
        reports = []

        for entry in feed.entries:
            reports.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()
            })

        return {
            "source": url,
            "count": len(reports),
            "reports": reports
        }

    except Exception as ex:
        return {
            "source": url,
            "count": 0,
            "error": str(ex),
            "reports": []
        }
def fetch_victoria_procurement():
    """Fetch Victoria procurement opportunities from RSS."""
    feed = "https://victoria.bonfirehub.ca/opportunities/rss"
    try:
        parsed = feedparser.parse(feed)
        items = []

        for e in parsed.entries:
            raw_title = html.unescape(getattr(e, "title", ""))
            if ". Name:" in raw_title:
                ref_no, title = [part.strip() for part in raw_title.split(". Name:", 1)]
            elif " | " in raw_title:
                parts = [p.strip() for p in raw_title.split(" | ")]
                ref_no, title = parts[0], " | ".join(parts[1:])
            else:
                ref_no, title = raw_title, ""

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
            '/legal_info',
            '/access_information',
            '/federal_procurement',
            '/federal_contracts',
            '/canadian_news',
            '/bc_procurement',
            '/municipal_councillors',
            '/committee_reports',
            '/victoria_procurement',
            '/senate_calendar',
            '/bills_legislation',
            '/parliamentary_docs',
            '/senate_orders'
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
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "message": "Welcome to RSS Data API!",
        "status": "running",
        "health_check": "/health"
    }), 200

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
    serve(app, host='0.0.0.0', port=5000)
