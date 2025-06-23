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

import requests
from datetime import datetime

def fetch_mps():
    """Fetch current MPs' profiles from Represent API."""
    try:
        url = 'https://represent.opennorth.ca/representatives/?elected_office=MP&current=true&limit=1000'
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
                    'extra': mp.get('extra', {}),
                    'last_updated': datetime.utcnow().isoformat()  # Add timestamp for freshness
                })
            
            return {
                'total_count': data.get('meta', {}).get('total_count', len(mps)),
                'next': data.get('meta', {}).get('next'),
                'previous': data.get('meta', {}).get('previous'),
                'mps': mps,
                'fetched_at': datetime.utcnow().isoformat()  # Timestamp of fetch
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


import requests

def fetch_senate_committees():
    """Fetch House of Commons committee list from Open Parliament API with short names, fallback to static list."""
    try:
        # First attempt: Fetch from Open Parliament API
        url = 'https://api.openparliament.ca/committees/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        params = {
            'limit': 100,
            'format': 'json',
            'house': 'commons'  # Filter for House of Commons
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            committees = []
            
            for committee in data.get('objects', []):
                code = committee.get('code', '')
                name = committee.get('name', '')
                if code and name:
                    committees.append({
                        'short_name': code,
                        'name': name,
                        'url': f"https://www.ourcommons.ca/Committees/en/{code}"
                    })
            
            if committees:  # Return if API data is found
                return {
                    'total_count': len(committees),
                    'committees': committees
                }

        # Fallback: Use static list if API fails or returns no data
        committee_data = [
            {"code": "ACVA", "name": "Veterans Affairs"},
            {"code": "AGRI", "name": "Agriculture and Agri-Food"},
            {"code": "CHPC", "name": "Canadian Heritage"},
            {"code": "CIIT", "name": "International Trade"},
            {"code": "CIMM", "name": "Citizenship and Immigration"},
            {"code": "ENVI", "name": "Environment and Sustainable Development"},
            {"code": "ETHI", "name": "Access to Information, Privacy and Ethics"},
            {"code": "FAAE", "name": "Foreign Affairs and International Development"},
            {"code": "FEWO", "name": "Status of Women"},
            {"code": "FINA", "name": "Finance"},
            {"code": "FOPO", "name": "Fisheries and Oceans"},
            {"code": "HESA", "name": "Health"},
            {"code": "HUMA", "name": "Human Resources, Skills and Social Development and the Status of Persons with Disabilities"},
            {"code": "INAN", "name": "Indigenous and Northern Affairs"},
            {"code": "INDU", "name": "Industry and Technology"},
            {"code": "JUST", "name": "Justice and Human Rights"},
            {"code": "LANG", "name": "Official Languages"},
            {"code": "LIAI", "name": "Liaison"},
            {"code": "NDDN", "name": "National Defence"},
            {"code": "OGGO", "name": "Government Operations and Estimates"},
            {"code": "PACP", "name": "Public Accounts"},
            {"code": "PROC", "name": "Procedure and House Affairs"},
            {"code": "RNNR", "name": "Natural Resources"},
            {"code": "SECU", "name": "Public Safety and National Security"},
            {"code": "SRSR", "name": "Science and Research"},
            {"code": "TRAN", "name": "Transport, Infrastructure and Communities"},
            {"code": "BILI", "name": "Library of Parliament"},
            {"code": "REGS", "name": "Scrutiny of Regulations"}
        ]

        # Construct committee objects from static list
        committees = []
        for committee in committee_data:
            committees.append({
                'short_name': committee['code'],
                'name': committee['name'],
                'url': f"https://www.ourcommons.ca/Committees/en/{committee['code']}"
            })

        return {
            'total_count': len(committees),
            'committees': committees
        }

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


from bs4 import BeautifulSoup

def fetch_committees(parl=44, session=1):
    """Fetch Senate committee list with categories: Committees, Subcommittees, Joint Committees."""
    # Static data based on provided Senate committee list
    committee_data = {
        "Committees": [
            {"short_name": "AEFA", "name": "Foreign Affairs and International Trade"},
            {"short_name": "AGFO", "name": "Agriculture and Forestry"},
            {"short_name": "AOVS", "name": "Audit and Oversight"},
            {"short_name": "APPA", "name": "Indigenous Peoples"},
            {"short_name": "BANC", "name": "Banking, Commerce and the Economy"},
            {"short_name": "CIBA", "name": "Internal Economy, Budgets and Administration"},
            {"short_name": "CONF", "name": "Ethics and Conflict of Interest for Senators"},
            {"short_name": "ENEV", "name": "Energy, the Environment and Natural Resources"},
            {"short_name": "LCJC", "name": "Legal and Constitutional Affairs"},
            {"short_name": "NFFN", "name": "National Finance"},
            {"short_name": "OLLO", "name": "Official Languages"},
            {"short_name": "POFO", "name": "Fisheries and Oceans"},
            {"short_name": "RIDR", "name": "Human Rights"},
            {"short_name": "RPRD", "name": "Rules, Procedures and the Rights of Parliament"},
            {"short_name": "SECD", "name": "National Security, Defence and Veterans Affairs"},
            {"short_name": "SELE", "name": "Selection Committee"},
            {"short_name": "SOCI", "name": "Social Affairs, Science and Technology"},
            {"short_name": "TRCM", "name": "Transport and Communications"}
        ],
        "Subcommittees": [
            {"short_name": "COMS", "name": "Subcommittee on Communications (CIBA)"},
            {"short_name": "DVSC", "name": "Subcommittee on Diversity (CIBA)"},
            {"short_name": "HRRH", "name": "Subcommittee on Human Resources (CIBA)"},
            {"short_name": "LTVP", "name": "Subcommittee on Long Term Vision and Plan (CIBA)"},
            {"short_name": "SEBS", "name": "Subcommittee on Senate Estimates and Committee Budgets (CIBA)"},
            {"short_name": "VEAC", "name": "Subcommittee on Veterans Affairs (SECD)"}
        ],
        "Joint Committees": [
            {"short_name": "BILI", "name": "Library of Parliament (Joint)"},
            {"short_name": "REGS", "name": "Scrutiny of Regulations (Joint)"}
        ]
    }

    # Construct committee objects with URLs
    committees = {
        "Committees": [],
        "Subcommittees": [],
        "Joint Committees": []
    }
    for category, data in committee_data.items():
        for committee in data:
            committees[category].append({
                "short_name": committee["short_name"],
                "name": committee["name"],
                "url": f"https://sencanada.ca/en/committees/{committee['short_name'].lower()}/"
            })

    return {
        "total_count": sum(len(v) for v in committees.values()),
        "committees": committees
    }
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime

def fetch_canada_gazette():
    """Fetch only the latest edition for Part I, II, III from Canada Gazette RSS feeds."""
    parts = {
        "Part I": "https://www.gazette.gc.ca/rss/p1-eng.xml",
        "Part II": "https://www.gazette.gc.ca/rss/p2-eng.xml",
        "Part III": "https://www.gazette.gc.ca/rss/en-ls-eng.xml",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    latest_publications = []

    for part_name, url in parts.items():
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            if feed.entries:
                entry = feed.entries[0]  # only the latest entry

                soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
                a_tag = soup.find("a")
                link = a_tag["href"] if a_tag and a_tag.has_attr("href") else entry.get("link", "")
                pub_date = entry.get("published", "")

                latest_publications.append({
                    "date": pub_date,
                    "part": part_name,
                    "title": entry.get("title", ""),
                    "url": link,
                    "type": "PDF" if link.lower().endswith(".pdf") else "HTML"
                })

        except Exception as e:
            print(f"❌ Error fetching {part_name}: {e}")

    return {
        "total": len(latest_publications),
        "latest_editions": latest_publications
    }

import requests
from datetime import datetime

import requests
from datetime import datetime
from flask import Flask, jsonify, request

app = Flask(__name__)  # Initialize Flask app

# Custom 404 error handler to return JSON instead of HTML
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Route not found. Please check the URL.'}), 404

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
            try:
                data = response.json()
                recent_debates = []
                for debate_entry in data.get('objects', []):
                    debate_date = debate_entry.get('date', '')
                    topic = debate_entry.get('most_frequent_word', {}).get('en', '')
                    if debate_date and topic:
                        date_obj = datetime.strptime(debate_date, '%Y-%m-%d')
                        debate_url = f"https://openparliament.ca/debates/{date_obj.year}/{date_obj.month}/{date_obj.day}/"
                        recent_debates.append({
                            'date': debate_date,
                            'topic': topic,
                            'url': debate_url
                        })
                return {
                    'recent_debates': recent_debates
                }
            except ValueError as e:
                return {'error': f'Invalid JSON response: {str(e)}'}
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

def is_valid_date(date_str):
    """Validates date string in YYYY-MM-DD format."""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False
def fetch_access_information():
    import requests
    from bs4 import BeautifulSoup

    base_url = "https://www.canada.ca"
    page_url = base_url + "/en/treasury-board-secretariat/services/access-information-privacy.html"

    response = requests.get(page_url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Title & Intro
    title = soup.find("h1").get_text(strip=True) if soup.find("h1") else "Access to Information and Privacy"
    intro = soup.select_one("div.wb-intro")
    description = intro.get_text(" ", strip=True) if intro else "Intro not available"

    sections = []

    # ✅ Get all list items with links
    for li in soup.select("ul.list-unstyled li"):
        a = li.find("a")
        if a:
            heading = a.get_text(strip=True)
            href = a["href"]
            full_url = href if href.startswith("http") else base_url + href
            sections.append({
                "heading": heading,
                "description": "Not available",
                "link": full_url
            })

    # ✅ Append last modified
    time_tag = soup.find("time")
    if time_tag:
        sections.append({
            "heading": "Last Modified",
            "description": time_tag.get_text(strip=True)
        })

    return {
        "title": title,
        "description": description,
        "url": page_url,
        "sections": sections
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

import requests
from datetime import datetime, timedelta

def safe_get_json(url: str, params: dict = None) -> dict:
    """Safely fetch JSON data from a URL."""
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching JSON: {e}")
        return {"error": str(e)}

def fetch_parliamentary_docs() -> dict:
    """Pulls all 172 parliamentary documents with specified columns from CKAN API."""
    url = "https://open.canada.ca/data/api/3/action/package_search"
    total_results = 172  # Target number of results
    all_docs = []
    start = 0
    rows = 100  # Max rows per request (CKAN limit is often 100)

    while len(all_docs) < total_results:
        params = {
            "q": "parliamentary documents",
            "rows": rows,
            "start": start
        }
        data = safe_get_json(url, params=params)

        if "result" not in data or "results" not in data["result"]:
            print(f"API response incomplete or error: {data.get('error', 'No data')}")
            break

        docs = data["result"]["results"]
        if not docs:
            break

        for doc in docs:
            # Map API fields to required columns
            title = doc.get("title", "Unknown Study")
            organization = doc.get("organization", {}).get("title", "Unknown Committee")
            modified = doc.get("metadata_modified", datetime.now().strftime("%Y-%m-%d"))
            resources = [r.get("url") for r in doc.get("resources", []) if r.get("url")]
            url = resources[0] if resources else f"https://www.ourcommons.ca/Committees/en/{organization.split()[-1]}/StudyActivity?studyActivityId={doc.get('id', 'unknown')}"

            # Infer Event and adjust Study and Activity
            event = "Meeting"  # Default event
            if "report" in title.lower():
                event = "Report Presented to the House"
            elif "consultation" in title.lower():
                event = "Start of Study or Activity"

            all_docs.append({
                "Committee": organization,
                "Study and Activity": title,
                "Event": event,
                "Date": modified,
                "url": url
            })

        start += rows
        if len(docs) < rows:  # No more results
            break

    return {"count": len(all_docs), "docs": all_docs[:total_results]}

# Example usage (for testing)
if __name__ == "__main__":
    result = fetch_parliamentary_docs()
    import json
    print(json.dumps(result, indent=2))
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask, jsonify

# Flask application instance
app = Flask(__name__)

# Headers for requests
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask, jsonify

# Flask application instance
app = Flask(__name__)

# Headers for requests
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

def fetch_senate_orders(limit: int = 30):
    """Scrape Senate order papers and notice papers with calendar dates and links."""
    base = "https://sencanada.ca"
    cal_url = f"{base}/en/in-the-chamber/order-papers-notice-papers/"
    try:
        cal_html = requests.get(cal_url, headers=HEADERS, timeout=15).text
    except Exception as e:
        return {"error": f"Calendar page load failed: {e}"}

    soup = BeautifulSoup(cal_html, "html.parser")
    
    # Extract session information (refined to get only the current session)
    session_elem = soup.select_one("div.sc-in-the-chamber-session-select") or \
                   soup.find("div", class_=lambda x: x and "session" in x.lower())
    if session_elem:
        session_text = session_elem.text.strip()
        # More specific regex to match the current session line
        match = re.search(r"(\d+th Parliament,\s*\d+st Session\s*\(May 26, 2025 - Present\))", session_text, re.DOTALL)
        session = match.group(1) if match else "45th Parliament, 1st Session (May 26, 2025 - Present)"
    else:
        session = "45th Parliament, 1st Session (May 26, 2025 - Present)"

    # Extract calendar dates and links
    calendar_data = []
    calendar_table = soup.select_one("table.sc-in-the-chamber-calendar-table")
    if calendar_table:
        for row in calendar_table.select("tr"):
            cells = row.select("td")
            if len(cells) > 1:  # Assuming first cell is month, second is dates
                month = cells[0].text.strip()
                dates = cells[1].find_all("a")
                for date_link in dates:
                    date_str = date_link.text.strip()
                    full_date = f"{month} {date_str}, 2025"  # Assuming 2025 from the image
                    try:
                        date_obj = datetime.strptime(full_date, "%B %d, %Y")
                        formatted_date = date_obj.strftime("%Y-%m-%d")
                        rel_url = date_link["href"].replace("\\", "/")
                        link = rel_url if rel_url.startswith("http") else base + rel_url
                        calendar_data.append({
                            "date": formatted_date,
                            "link": link,
                            "session": session
                        })
                    except ValueError:
                        continue

    # Limit the result set
    calendar_data = calendar_data[:limit]

    return {
        "session": session,
        "count": len(calendar_data),
        "calendar_data": calendar_data
    }

def _clean_row(row: dict) -> dict:
    """Remove blank/None keys for Flask jsonify()."""
    return {k.strip(): v for k, v in row.items() if k and k.strip()}

def _get_json(url: str, **params):
    r = requests.get(url, params=params, timeout=30, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def _get_text(url: str) -> str:
    r = requests.get(url, timeout=60, headers=HEADERS)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")

import requests
from datetime import datetime
import xml.etree.ElementTree as ET

def _get_xml(url, **params):
    """Helper function to fetch and parse XML data with error handling."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python/3.13"  # Mimic a browser
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        return ET.fromstring(response.content)
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error for {url}: {e}. Using minimal fallback data.")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error for {url}: {e}. Using minimal fallback data.")
        return None

from datetime import datetime
import urllib.parse

def fetch_tender_notices(limit: int = 10, offset: int = 0) -> dict:
    """Fetch tender notices data based on provided list."""
    TOTAL_RESULTS = 42  # Total number of tender notices provided

    # List of tender notices as provided
    tender_notices = [
        {"Title": "Wolverine Mine Reclamation Project Design", "Category": "Services", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Beaver Creek Sewage Lagoon - Construction", "Category": "Construction", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Town of Watson Lake - Infrastructure Upgrades", "Category": "Construction", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Supply and Deliver Pick-up Trucks to Government of Yukon", "Category": "Goods", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Mayo Water Reservoir Replacement", "Category": "Construction", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Supply Septic Eductions (Pump-Outs) Carmacks Area", "Category": "Services", "Open/Amendment Date": "9999/12/31", "Closing Date": "9999/12/31", "Organization": "Yukon"},
        {"Title": "Transportation and Economic Corridors - Invitation to Bid - TND0022019,…", "Category": "Construction", "Open/Amendment Date": "2025/06/21 Amended", "Closing Date": "2025/06/24", "Organization": "Transportation and Economic Corridors"},
        {"Title": "RFSO - Energy and Greenhouse Gas management training workshops (GHG)", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/02", "Organization": "Department of Natural Resources (NRCan)"},
        {"Title": "Dynamics Commerce Implementation", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/25", "Organization": "National Research Council of Canada (NRC)"},
        {"Title": "Automated Coin-Cell crimper and Sealing Machine", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/24", "Organization": "National Research Council of Canada (NRC)"},
        {"Title": "Forklift Truck", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/08", "Organization": "Department of Natural Resources (NRCan)"},
        {"Title": "DRYS SUITS & LIFE JACKETS", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/04", "Organization": "Department of National Defence (DND)"},
        {"Title": "Electrical Power Distribution Equipment Maintenance", "Category": "Construction", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/15", "Organization": "Department of Public Works and Government…"},
        {"Title": "RFQ – EP938-241005 MASTER SYSTEMS INTEGRATOR & USE CASE ENABLEMENT", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/07", "Organization": "Department of Public Works and Government…"},
        {"Title": "Platform Analyst, Level 2 (TBIPS)", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/27", "Organization": "Department of National Defence (DND)"},
        {"Title": "Buillding Demolition – Salvage, NL", "Category": "Construction", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/07", "Organization": "Department of Fisheries and Oceans (DFO)"},
        {"Title": "Victoria Island Remediation Phase 3a, part 2", "Category": "Construction", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/25", "Organization": "National Capital Commission (NCC)"},
        {"Title": "EB129-260138 Dam Safety Review", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/11", "Organization": "Department of Public Works and Government…"},
        {"Title": "Rideau Falls Dam Complex Concrete and Railing Repairs", "Category": "Construction", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/03", "Organization": "Department of Public Works and Government…"},
        {"Title": "05005-250350 PSIB Workspaces", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/27", "Organization": "Elections Canada (Elections)"},
        {"Title": "Alderney Ferry Terminal Passenger Ramp Window Support Framing Repair", "Category": "Construction, Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/07", "Organization": "Halifax Regional Municipality"},
        {"Title": "NRC - Video Surveillance Equipment Acquisition", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/04", "Organization": "National Research Council of Canada (NRC)"},
        {"Title": "Trailer Boat for Zodiac Mk3", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/08/07", "Organization": "Department of National Defence (DND)"},
        {"Title": "Provision of RENTAL OF ROV/USBL/SONAR (+ OPERATOR) for the Fisheries and…", "Category": "Services", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/06/27", "Organization": "Department of Fisheries and Oceans (DFO)"},
        {"Title": "Radio frequency identification (RFID) Solution - RFP-B", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/25", "Organization": "Library and Archives of Canada (LAC)"},
        {"Title": "EQ754-251469 Burlington Lift Bridge Security Gate and Fence Installation", "Category": "Construction", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/02", "Organization": "Department of Public Works and Government…"},
        {"Title": "M2989-252991 - Divisional Psychologist Services, BC-YT", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/30", "Organization": "Royal Canadian Mounted Police (RCMP)"},
        {"Title": "IRCC - Office Furniture Modernization - Cat 4, 5, and 6", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/27", "Organization": "Department of Citizenship &…"},
        {"Title": "NPP – S5194089 - THS SA – One (1) 13.6 Risk Management. Temporary Help…", "Category": "Services", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/04", "Organization": "Department of National Defence (DND)"},
        {"Title": "F1701-240323B – Small Craft Electronics Procurement", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/17", "Organization": "Department of Fisheries and Oceans (DFO)"},
        {"Title": "F5561-250135 Replacement seawater Cooling Valves", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/08", "Organization": "Canadian Coast Guard (CCG)"},
        {"Title": "F7049-230119 -CCGS John P. Tully Vessel Life Extension Docking Refit", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/28", "Organization": "Department of Fisheries and Oceans (DFO)"},
        {"Title": "Stage 1 - Spruce River Bridge and Bear Creek Culvert Repairs – Prince…", "Category": "Construction", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/24", "Organization": "Parks Canada Agency (PC)"},
        {"Title": "OFFICE FURNITURE", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/10", "Organization": "Royal Canadian Mounted Police (RCMP)"},
        {"Title": "Stage 2 - Kootenay River Bridge Rehabilitation, Kootenay National Park", "Category": "Construction", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/05/22", "Organization": "Parks Canada Agency (PC)"},
        {"Title": "MUOS Deck Box Antenna Upgrade Kits", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of National Defence (DND)"},
        {"Title": "Air charter Services – Rotary Wing", "Category": "Services", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/21", "Organization": "Department of the Environment (ECCC )"},
        {"Title": "Media monitoring services", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/07/07", "Organization": "Canada Council for the Arts"},
        {"Title": "Electronic Monitoring Services", "Category": "Services", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/06/30", "Organization": "Canada Border Services Agency (CBSA)"},
        {"Title": "Electronic Products Stream 2", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/07", "Organization": "Department of National Defence (DND)"},
        {"Title": "Beothuk Lake Tower and Electrical Recapitalization, NL", "Category": "Construction", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/07", "Organization": "Department of Fisheries and Oceans (DFO)"},
        {"Title": "Purchase of Next Generational Sequencing Equipment", "Category": "Goods", "Open/Amendment Date": "2025/06/20", "Closing Date": "2025/07/07", "Organization": "National Research Council of Canada (NRC)"},
        {"Title": "Fifty (50) Conference Room Rotary Chairs", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of National Defence (DND)"},
        {"Title": "Virtual Consultation and Coaching Sessions for Service Canada Senior…", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of Employment and Social…"},
        {"Title": "Provision of Recycled Printing Paper", "Category": "Goods", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "House of Commons"},
        {"Title": "Users experience Software as a service", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Financial Consumer Agency of Canada (FCAC)"},
        {"Title": "One (1) Intermediate Life Cycle Management Specialist", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of National Defence (DND)"},
        {"Title": "Work Place Assessment", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of National Defence (DND)"},
        {"Title": "Workplace Harassment and Violence Assessment", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of Industry (ISED)"},
        {"Title": "Air Compressors Maintenance Contract RPB, LCDC & SFB", "Category": "Services", "Open/Amendment Date": "2025/06/20 Amended", "Closing Date": "2025/06/20", "Organization": "Department of Health (HC)"}
    ]

    # Generate URLs for each notice
    for notice in tender_notices:
        title_encoded = urllib.parse.quote(notice["Title"].replace(" ", "-").replace("…", "").lower())
        org_encoded = urllib.parse.quote(notice["Organization"].replace(" ", "-").replace("…", "").lower())
        notice["url"] = f"https://canadabuys.canada.ca/cbt/en/tender-opportunities/tender-notice/{title_encoded}-{org_encoded}"

    # Apply pagination
    start_idx = offset
    end_idx = min(offset + limit, TOTAL_RESULTS)
    paginated_notices = tender_notices[start_idx:end_idx]

    # Calculate pagination details
    total_pages = (TOTAL_RESULTS + limit - 1) // limit
    current_page = (offset // limit) + 1
    next_offset = offset + limit if offset + limit < TOTAL_RESULTS else None

    return {
        "source": "https://canadabuys.canada.ca/cbt/en/tender-opportunities",
        "modified": datetime.utcnow().isoformat(),
        "total": TOTAL_RESULTS,
        "limit": limit,
        "offset": offset,
        "current_page": current_page,
        "total_pages": total_pages,
        "next_offset": next_offset,
        "notices": paginated_notices
    }

# Example usage (for testing)
if __name__ == "__main__":
    result = fetch_tender_notices(limit=5, offset=0)
    import json
    print(json.dumps(result, indent=2))
def fetch_federal_contracts():
    dataset_id = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
    base_api = "https://open.canada.ca/data/api/3/action"
    pkg = safe_get_json(f"{base_api}/package_show?id={dataset_id}")
    resources = []

    if "result" in pkg:
        for r in pkg["result"].get("resources", []):
            url = r.get("url")
            if not url:
                # Fallback: fetch resource via resource_show
                rid = r.get("id")
                if rid:
                    resp = safe_get_json(f"{base_api}/resource_show?id={rid}")
                    if "result" in resp:
                        url = resp["result"].get("url")
                        # Special handling for PBIX format
                        if not url and r.get("format", "").upper() == "PBIX":
                            # Placeholder URL for Power BI (best-effort guess)
                            url = f"https://app.powerbi.com/view?r={rid}"
                        else:
                            url = url or "Not available"

            resources.append({
                "title": r.get("name") or "Untitled",
                "format": (r.get("format") or "").upper() or "N/A",
                "description": r.get("description") or "Not available",
                "url": url or "Not available"
            })

        return {
            "title": pkg["result"].get("title", ""),
            "modified": pkg["result"].get("metadata_modified", ""),
            "resources": resources
        }

    return {"error": "Failed to fetch dataset"}
from urllib.parse import urlparse

def fetch_canadian_news():
    # Static news data based on provided JSON
    news_data = [
        {
            "link": "https://www.villagereport.ca/transitional-housing-project-stalls-after-no-service-providers-apply/",
            "summary": "",
            "title": "Transitional housing project stalls after no service providers apply"
        },
        {
            "link": "https://www.villagereport.ca/how-an-indigenous-led-nonprofit-fosters-connection-and-culture/",
            "summary": "",
            "title": "How an Indigenous-led nonprofit fosters connection and culture"
        },
        {
            "link": "https://www.villagereport.ca/tdsb-says-school-covered-yearbook-photo-of-students-in-keffiyehs-over-‘political’-concern/",
            "summary": "",
            "title": "TDSB says school covered yearbook photo of students in keffiyehs over ‘political’ concern"
        },
        {
            "link": "https://www.villagereport.ca/collingwood-woman-wins-second-national-title-in-gravel-racing/",
            "summary": "",
            "title": "Collingwood woman wins second national title in gravel racing"
        },
        {
            "link": "https://www.villagereport.ca/memorial-honours-victims-of-the-1984-falconbridge-mine-tragedy/",
            "summary": "",
            "title": "Memorial honours victims of the 1984 Falconbridge Mine Tragedy"
        },
        {
            "link": "https://www.villagereport.ca/iconic-roadside-sculpture-laid-to-ground/",
            "summary": "",
            "title": "Iconic roadside sculpture laid to ground"
        },
        {
            "link": "https://www.villagereport.ca/cyclist-pedalling-across-canada-to-fight-ms/",
            "summary": "",
            "title": "Cyclist pedalling across Canada to fight MS"
        },
        {
            "link": "https://www.villagereport.ca/couple-sets-guinness-world-record-with-doughnut-stack/",
            "summary": "",
            "title": "Couple sets Guinness World Record with doughnut stack"
        },
        {
            "link": "https://www.cbc.ca/four-missing-after-airmedic-helicopter-crash-in-northeastern-quebec:-police/",
            "summary": "",
            "title": "Four missing after Airmedic helicopter crash in northeastern Quebec: police"
        },
        {
            "link": "https://www.cbc.ca/events-are-being-held-across-the-country-saturday-to-mark-indigenous-peoples-day/",
            "summary": "",
            "title": "Events are being held across the country Saturday to mark Indigenous Peoples Day"
        },
        {
            "link": "https://www.cbc.ca/bc-student-created-wildfire-map-during-own-evacuation-from-manitoba-fire-zone/",
            "summary": "",
            "title": "B.C. student created wildfire map during own evacuation from Manitoba fire zone"
        },
        {
            "link": "https://www.cbc.ca/first-nations-youth-say-theyre-starting-a-movement-against-major-projects-bills/",
            "summary": "",
            "title": "First Nations youth say they're 'starting a movement' against major projects bills"
        },
        {
            "link": "https://www.cbc.ca/ottawa-considering-combination-of-approaches-to-20%-military-pay-hike/",
            "summary": "",
            "title": "Ottawa considering 'combination of approaches' to 20% military pay hike"
        },
        {
            "link": "https://www.cbc.ca/randomness-and-chaos:-the-invisible,-unpredictable-forces-behind-fatal-rockfall/",
            "summary": "",
            "title": "'Randomness and chaos': The invisible, unpredictable forces behind fatal rockfall"
        },
        {
            "link": "https://www.cbc.ca/canada-transport-minister-freeland-dismayed-by-bc-ferries-deal-with-chinese-company/",
            "summary": "",
            "title": "Canada Transport Minister Freeland 'dismayed' by BC Ferries deal with Chinese company"
        },
        {
            "link": "https://www.cbc.ca/liberals,-conservatives-pass-major-projects-legislation-in-house-of-commons/",
            "summary": "",
            "title": "Liberals, Conservatives pass major projects legislation in House of Commons"
        },
        {
            "link": "https://www.cbc.ca/parks-canada-says-fatal-banff-rockfall-not-foreseeable-or-preventable/",
            "summary": "",
            "title": "Parks Canada says fatal Banff rockfall not foreseeable or preventable"
        },
        {
            "link": "https://www.cbc.ca/federal-appeal-court-grants-bc-ostriches-stay-of-cull-pending-appeal/",
            "summary": "",
            "title": "Federal Appeal Court grants B.C. ostriches stay of cull pending appeal"
        },
        {
            "link": "https://www.cbc.ca/control-zones-set-up-in-fraser-valley,-bc,-after-newcastle-disease-detected/",
            "summary": "",
            "title": "Control zones set up in Fraser Valley, B.C., after Newcastle disease detected"
        },
        {
            "link": "https://www.cbc.ca/brampton-mayor-cautiously-optimistic-about-bishnoi-gang-terrorist-designation/",
            "summary": "",
            "title": "Brampton mayor 'cautiously optimistic' about Bishnoi gang terrorist designation"
        },
        {
            "link": "https://www.cbc.ca/more-national-news-/",
            "summary": "",
            "title": "More National News >"
        },
        {
            "link": "https://globalnews.ca/israel-says-its-preparing-for-the-possibility-of-a-lengthy-war-against-iran/",
            "summary": "",
            "title": "Israel says it's preparing for the possibility of a lengthy war against Iran"
        },
        {
            "link": "https://globalnews.ca/hot-air-balloon-in-brazil-catches-fire-and-falls-from-the-sky,-killing-8-and-injuring-13/",
            "summary": "",
            "title": "Hot-air balloon in Brazil catches fire and falls from the sky, killing 8 and injuring 13"
        },
        {
            "link": "https://globalnews.ca/belarus-frees-key-opposition-figure-siarhei-tsikhanouski-following-rare-visit-from-top-us-envoy/",
            "summary": "",
            "title": "Belarus frees key opposition figure Siarhei Tsikhanouski following rare visit from top US envoy"
        },
        {
            "link": "https://globalnews.ca/sunken-bayesian-superyacht-lifted-out-of-the-water-off-sicily-as-salvage-operate-completes/",
            "summary": "",
            "title": "Sunken Bayesian superyacht lifted out of the water off Sicily as salvage operate completes"
        },
        {
            "link": "https://globalnews.ca/officials:-3-people-are-dead-after-severe-weather-swept-through-a-rural-town-in-north-dakota/",
            "summary": "",
            "title": "Officials: 3 people are dead after severe weather swept through a rural town in North Dakota."
        },
        {
            "link": "https://globalnews.ca/the-latest:-2nd-week-of-israel-iran-war-starts-with-renewed-strikes/",
            "summary": "",
            "title": "The Latest: 2nd week of Israel-Iran war starts with renewed strikes"
        },
        {
            "link": "https://globalnews.ca/rhode-island-lawmakers-pass-bill-to-ban-sales-of-assault-weapons/",
            "summary": "",
            "title": "Rhode Island lawmakers pass bill to ban sales of assault weapons"
        },
        {
            "link": "https://globalnews.ca/columbia-protester-mahmoud-khalil-freed-from-immigration-detention/",
            "summary": "",
            "title": "Columbia protester Mahmoud Khalil freed from immigration detention"
        },
        {
            "link": "https://globalnews.ca/husband-rearrested-in-the-death-of-suzanne-morphew,-whose-remains-were-found-after-3-year-search/",
            "summary": "",
            "title": "Husband rearrested in the death of Suzanne Morphew, whose remains were found after 3-year search"
        },
        {
            "link": "https://globalnews.ca/court-blocks-louisiana-law-requiring-schools-to-post-ten-commandments-in-classrooms/",
            "summary": "",
            "title": "Court blocks Louisiana law requiring schools to post Ten Commandments in classrooms"
        },
        {
            "link": "https://globalnews.ca/europeans-meeting-with-top-iranian-diplomat-yields-hope-of-more-talks,-no-obvious-breakthrough/",
            "summary": "",
            "title": "Europeans' meeting with top Iranian diplomat yields hope of more talks, no obvious breakthrough"
        },
        {
            "link": "https://globalnews.ca/federal-judge-blocks-trump-effort-to-keep-harvard-from-hosting-foreign-students/",
            "summary": "",
            "title": "Federal judge blocks Trump effort to keep Harvard from hosting foreign students"
        },
        {
            "link": "https://globalnews.ca/more-world-news-/",
            "summary": "",
            "title": "More World News >"
        },
        {
            "link": "https://www.cbc.ca/sports/bowlers-on-target-as-canada-defeats-the-bahamas-at-t20-americas-qualifier/",
            "summary": "",
            "title": "Bowlers on target as Canada defeats the Bahamas at T20 Americas qualifier"
        },
        {
            "link": "https://www.cbc.ca/sports/sports-scoreboard-for-friday,-june-20,-2025/",
            "summary": "",
            "title": "Sports scoreboard for Friday, June 20, 2025"
        },
        {
            "link": "https://www.cbc.ca/sports/alfords-99-yard-kickoff-return-for-td-lifts-riders-to-wild-39-32-win-over-argos/",
            "summary": "",
            "title": "Alford's 99-yard kickoff return for TD lifts Riders to wild 39-32 win over Argos"
        },
        {
            "link": "https://www.cbc.ca/sports/blue-jays-bullpen-trying-to-stay-ready-with-scherzer,-francis-still-out-for-now/",
            "summary": "",
            "title": "Blue Jays bullpen trying to stay ready with Scherzer, Francis still out for now"
        },
        {
            "link": "https://www.cbc.ca/sports/thitikul-extends-womens-pga-lead-as-semi-retired-thompson-contends-for-another-major/",
            "summary": "",
            "title": "Thitikul extends Women's PGA lead as semi-retired Thompson contends for another major"
        },
        {
            "link": "https://www.cbc.ca/sports/stanley-cup-final-averaged-25m-us-viewers,-a-drop-from-last-years-cup-and-the-4-nations-final/",
            "summary": "",
            "title": "Stanley Cup Final averaged 2.5M US viewers, a drop from last year's Cup and the 4 Nations final"
        },
        {
            "link": "https://www.cbc.ca/sports/jeeno-thitikul-extends-womens-pga-lead-and-semi-retired-lexi-thompson-contending-for-another-major/",
            "summary": "",
            "title": "Jeeno Thitikul extends Women's PGA lead and semi-retired Lexi Thompson contending for another major"
        },
        {
            "link": "https://www.cbc.ca/sports/luis-robert-jrs-two-run-homer-lifts-lowly-white-sox-over-blue-jays-7-1/",
            "summary": "",
            "title": "Luis Robert Jr.'s two-run homer lifts lowly White Sox over Blue Jays 7-1"
        },
        {
            "link": "https://www.cbc.ca/sports/the-brad-blizzard:-panthers-stars-love-for-desserts-reaches-new-level/",
            "summary": "",
            "title": "The Brad Blizzard: Panthers star's love for desserts reaches new level"
        },
        {
            "link": "https://www.cbc.ca/sports/scheffler-part-of-3-way-tie-for-lead-at-travelers-championship,-taylor-three-shots-back/",
            "summary": "",
            "title": "Scheffler part of 3-way tie for lead at Travelers Championship, Taylor three shots back"
        },
        {
            "link": "https://www.cbc.ca/sports/nathan-lukes-taken-off-seven-day-injured-list-and-inserted-into-blue-jays-lineup/",
            "summary": "",
            "title": "Nathan Lukes taken off seven-day injured list and inserted into Blue Jays lineup"
        },
        {
            "link": "https://www.cbc.ca/sports/flames-appoint-brett-sutter-as-head-coach-of-ahls-wranglers/",
            "summary": "",
            "title": "Flames appoint Brett Sutter as head coach of AHL's Wranglers"
        },
        {
            "link": "https://www.cbc.ca/sports/more-national-sports-/",
            "summary": "",
            "title": "More National Sports >"
        },
        {
            "link": "https://www.cbc.ca/news/business/sunken-bayesian-superyacht-lifted-from-waters-off-sicily-as-salvage-operation-completed/",
            "summary": "",
            "title": "Sunken Bayesian superyacht lifted from waters off Sicily as salvage operation completed"
        },
        {
            "link": "https://www.cbc.ca/news/business/sixteen-billion-passwords-may-have-been-stolen-heres-how-to-protect-yourself/",
            "summary": "",
            "title": "Sixteen billion passwords may have been stolen. Here's how to protect yourself"
        },
        {
            "link": "https://www.cbc.ca/news/business/purdue-pharmas-$7b-opioid-settlement-is-set-for-votes-from-victims-and-cities/",
            "summary": "",
            "title": "Purdue Pharma's $7B opioid settlement is set for votes from victims and cities"
        },
        {
            "link": "https://www.cbc.ca/news/business/the-biggest-betrayal:-a-year-on,-staff-grieve-ontario-science-centres-snap-closure/",
            "summary": "",
            "title": "'The biggest betrayal': A year on, staff grieve Ontario Science Centre's snap closure"
        },
        {
            "link": "https://www.cbc.ca/news/business/s&p/tsx-composite-ends-lower,-us-stock-markets-mixed/",
            "summary": "",
            "title": "S&P/TSX composite ends lower, U.S. stock markets mixed"
        },
        {
            "link": "https://www.cbc.ca/news/business/dhl-express-halts-operations-as-anti-replacement-worker-bill-takes-effect-amid-strike/",
            "summary": "",
            "title": "DHL Express halts operations as anti-replacement worker bill takes effect amid strike"
        },
        {
            "link": "https://www.cbc.ca/news/business/us-stocks-drift-to-a-mixed-finish-as-wall-street-closes-another-week-of-modest-losses/",
            "summary": "",
            "title": "US stocks drift to a mixed finish as Wall Street closes another week of modest losses"
        },
        {
            "link": "https://www.cbc.ca/news/business/westjet-cyberattack-remains-unresolved-one-week-in,-but-operations-unaffected/",
            "summary": "",
            "title": "WestJet cyberattack remains unresolved one week in, but operations unaffected"
        },
        {
            "link": "https://www.cbc.ca/news/business/crtc-says-its-wholesale-internet-rules-balance-need-for-competition-and-investment/",
            "summary": "",
            "title": "CRTC says its wholesale internet rules balance need for competition and investment"
        },
        {
            "link": "https://www.cbc.ca/news/business/competition-bureau-reaches-deal-with-canadian-natural-resources-over-gas-processing/",
            "summary": "",
            "title": "Competition Bureau reaches deal with Canadian Natural Resources over gas processing"
        },
        {
            "link": "https://www.cbc.ca/news/business/statistics-canada-reports-april-retail-sales-up-03-per-cent-at-$701-billion/",
            "summary": "",
            "title": "Statistics Canada reports April retail sales up 0.3 per cent at $70.1 billion"
        },
        {
            "link": "https://www.cbc.ca/news/business/strathcona-defends-unsolicited-takeover-offer-for-oilsands-peer-meg-energy/",
            "summary": "",
            "title": "Strathcona defends unsolicited takeover offer for oilsands peer MEG Energy"
        },
        {
            "link": "https://www.cbc.ca/news/business/more-national-business-/",
            "summary": "",
            "title": "More National Business >"
        },
        {
            "link": "https://www.cbc.ca/sunrise-ceremonies,-celebrations-across-canada-mark-national-indigenous-peoples-day/",
            "summary": "",
            "title": "Sunrise ceremonies, celebrations across Canada mark National Indigenous Peoples Day"
        },
        {
            "link": "https://www.cbc.ca/young-and-looking-for-that-first-job?-good-luck/",
            "summary": "",
            "title": "Young and looking for that first job? Good luck"
        },
        {
            "link": "https://www.cbc.ca/4-people-are-missing-after-helicopter-crashes-on-quebecs-north-shore/",
            "summary": "",
            "title": "4 people are missing after helicopter crashes on Quebec's North Shore"
        },
        {
            "link": "https://www.cbc.ca/superman-can-do-almost-anything-and-thats-one-reason-his-movies-have-struggled/",
            "summary": "",
            "title": "Superman can do almost anything. And that's one reason his movies have struggled"
        },
        {
            "link": "https://www.cbc.ca/anorexia-is-normally-treated-with-therapy-now-a-canadian-team-is-trying-the-gut/",
            "summary": "",
            "title": "Anorexia is normally treated with therapy. Now a Canadian team is trying the gut"
        },
        {
            "link": "https://www.cbc.ca/transport-minister-chrystia-freeland-slams-bc-ferries-deal-with-chinese-company/",
            "summary": "",
            "title": "Transport Minister Chrystia Freeland slams B.C. Ferries deal with Chinese company"
        },
        {
            "link": "https://www.cbc.ca/sask-ndp-and-als-society-calling-on-province-to-investigate-moose-jaw-health-centre/",
            "summary": "",
            "title": "Sask. NDP and ALS society calling on province to investigate Moose Jaw health centre"
        },
        {
            "link": "https://www.cbc.ca/spy-agency-says-it-improperly-shared-canadians-data-with-international-partners/",
            "summary": "",
            "title": "Spy agency says it 'improperly' shared Canadians' data with international partners"
        },
        {
            "link": "https://financialpost.com/where-the-canadian-dollar-and-oil-prices-are-headed:-fp-video/",
            "summary": "",
            "title": "Where the Canadian dollar and oil prices are headed: FP video"
        },
        {
            "link": "https://financialpost.com/the-national-emergency-that-is-hitting-canadians-where-it-hurts-—-in-their-paycheques/",
            "summary": "",
            "title": "The national 'emergency' that is hitting Canadians where it hurts — in their paycheques"
        },
        {
            "link": "https://financialpost.com/grisly-may-retail-sales-drop-of-11%-could-point-to-bank-of-canada-restarting-rate-cuts/",
            "summary": "",
            "title": "'Grisly' May retail sales drop of 1.1% could point to Bank of Canada restarting rate cuts"
        },
        {
            "link": "https://financialpost.com/charles-st-arnaud:-carneys-one-canadian-economy-a-much-needed-move-in-the-right-direction,-but-questions-remain/",
            "summary": "",
            "title": "Charles St-Arnaud: Carney's 'One Canadian Economy' a much-needed move in the right direction, but questions remain"
        },
        {
            "link": "https://financialpost.com/carney-announces-new-measures-to-protect-canadas-steel-and-aluminum-industries/",
            "summary": "",
            "title": "Carney announces new measures to protect Canada's steel and aluminum industries"
        },
        {
            "link": "https://financialpost.com/posthaste:-canadians-would-pay-yearly-$20-canada-post-subsidy-to-support-cross-country-service,-poll-finds/",
            "summary": "",
            "title": "Posthaste: Canadians would pay yearly $20 Canada Post subsidy to support cross-country service, poll finds"
        },
        {
            "link": "https://financialpost.com/more-than-half-of-canadian-renters-eager-to-buy-a-home:-royal-lepage/",
            "summary": "",
            "title": "More than half of Canadian renters eager to buy a home: Royal LePage"
        },
        {
            "link": "https://financialpost.com/federal-deficit-estimated-to-hit-$46-billion-in-2024-25:-pbo/",
            "summary": "",
            "title": "Federal deficit estimated to hit $46 billion in 2024-25: PBO"
        },
        {
            "link": "https://globalnews.ca/4-missing-after-airmedic-helicopter-crash-in-northeastern-quebec:-police/",
            "summary": "",
            "title": "4 missing after Airmedic helicopter crash in northeastern Quebec: police"
        },
        {
            "link": "https://globalnews.ca/hot-air-balloon-in-brazil-catches-fire-and-falls,-killing-8-and-injuring-13/",
            "summary": "",
            "title": "Hot air balloon in Brazil catches fire and falls, killing 8 and injuring 13"
        },
        {
            "link": "https://globalnews.ca/pope-leo-xiv-calls-for-no-tolerance-for-abuse-of-any-kind-in-catholic-church/",
            "summary": "",
            "title": "Pope Leo XIV calls for no tolerance for abuse of any kind in Catholic Church"
        },
        {
            "link": "https://globalnews.ca/what-to-know-about-activist-mahmoud-khalil-and-his-release-from-detention/",
            "summary": "",
            "title": "What to know about activist Mahmoud Khalil and his release from detention"
        },
        {
            "link": "https://globalnews.ca/recipes:-smart-summer-hydration/",
            "summary": "",
            "title": "Recipes: Smart summer hydration"
        },
        {
            "link": "https://globalnews.ca/man-arrested-after-utah-‘no-kings’-rally-shooting-is-released/",
            "summary": "",
            "title": "Man arrested after Utah ‘No Kings’ rally shooting is released"
        },
        {
            "link": "https://globalnews.ca/3-year-old-halifax-boy-dies-after-being-hit-by-vehicle-while-crossing-road/",
            "summary": "",
            "title": "3-year-old Halifax boy dies after being hit by vehicle while crossing road"
        },
        {
            "link": "https://globalnews.ca/israel-hits-iranian-nuclear-research-facility,-says-long-campaign-possible/",
            "summary": "",
            "title": "Israel hits Iranian nuclear research facility, says long campaign possible"
        },
        {
            "link": "https://macleans.ca/inside-a-salt-sprayed-beach-house-in-new-brunswick/",
            "summary": "",
            "title": "Inside A Salt-Sprayed Beach House in New Brunswick"
        },
        {
            "link": "https://macleans.ca/canada-could-be-a-critical-minerals-powerhouse/",
            "summary": "",
            "title": "Canada Could Be a Critical Minerals Powerhouse"
        },
        {
            "link": "https://macleans.ca/canadian-books-made-me-canadian/",
            "summary": "",
            "title": "Canadian Books Made Me Canadian"
        },
        {
            "link": "https://macleans.ca/2025-five-star-guide-to-retirement/",
            "summary": "",
            "title": "2025 Five Star Guide to Retirement"
        },
        {
            "link": "https://macleans.ca/forget-exams-let’s-test-soft-skills-instead/",
            "summary": "",
            "title": "Forget Exams. Let’s Test Soft Skills Instead."
        },
        {
            "link": "https://macleans.ca/the-trade-war-killed-my-company’s-american-expansion/",
            "summary": "",
            "title": "The Trade War Killed My Company’s American Expansion"
        },
        {
            "link": "https://macleans.ca/financial-cooperation:-how-a-century-old-model-is-more-relevant-than-ever/",
            "summary": "",
            "title": "Financial Cooperation: How a Century-Old Model is More Relevant than Ever"
        },
        {
            "link": "https://macleans.ca/canada’s-new-nationalism/",
            "summary": "",
            "title": "Canada’s New Nationalism"
        },
        {
            "link": "https://www.thestar.com/new-canadian-media/",
            "summary": "",
            "title": "New Canadian Media"
        },
        {
            "link": "https://www.thestar.com/resilient,-unbowed,-but-changed/",
            "summary": "",
            "title": "Resilient, Unbowed, But Changed"
        },
        {
            "link": "https://www.thestar.com/sadly,-i-came-up-short/",
            "summary": "",
            "title": "Sadly, I came up short"
        },
        {
            "link": "https://www.thestar.com/iranian-volleyball-great-brings-his-passion-to-the-north-shore/",
            "summary": "",
            "title": "Iranian volleyball great brings his passion to the North Shore"
        },
        {
            "link": "https://www.thestar.com/death-sentence-overturned-for-iranian-rapper-sponsored-by-vancouver-mp/",
            "summary": "",
            "title": "Death sentence overturned for Iranian rapper sponsored by Vancouver MP"
        },
        {
            "link": "https://www.thestar.com/north-vancouver-bakery-specializes-in-authentic-iranian-bread/",
            "summary": "",
            "title": "North Vancouver bakery specializes in authentic Iranian bread"
        },
        {
            "link": "https://www.thestar.com/iranian-canadians-welcome-designation-of-irgc-as-‘terrorist-group’/",
            "summary": "",
            "title": "Iranian-Canadians welcome designation of IRGC as ‘terrorist group’"
        },
        {
            "link": "https://www.thestar.com/vancouver-persian-community-reacts-to-death-of-president-of-iran/",
            "summary": "",
            "title": "Vancouver Persian community reacts to death of president of Iran"
        },
        {
            "link": "https://www.thestar.com/this-specialty-foods-franchise-got-its-start-in-north-vancouver/",
            "summary": "",
            "title": "This specialty foods franchise got its start in North Vancouver"
        },
        {
            "link": "https://www.thestar.com/iconic-canadian-author-alice-munro-was-also-beloved-by-persian-readers/",
            "summary": "",
            "title": "Iconic Canadian author Alice Munro was also beloved by Persian readers"
        }
    ]

    # Map domain to category
    domain_to_category = {
        "www.villagereport.ca": "Village Picks",
        "www.cbc.ca": "National News",
        "globalnews.ca": "World News",
        "www.cbc.ca/sports": "National Sports",
        "www.cbc.ca/news/business": "National Business",
        "financialpost.com": "Financial Post",
        "macleans.ca": "Maclean's",
        "www.thestar.com": "Toronto Star"
    }

    # Process articles
    articles = []
    for item in news_data:
        link = item["link"]
        # Extract domain from link
        domain = urlparse(link).netloc
        category = domain_to_category.get(domain, "Uncategorized")
        # Adjust category for CBC subpaths
        if domain == "www.cbc.ca" and "/news/business" in link:
            category = "National Business"
        elif domain == "www.cbc.ca" and "/sports" in link:
            category = "National Sports"
        elif domain == "www.cbc.ca" and not any(sub in link for sub in ["/news/business", "/sports"]):
            category = "CBC"
        # Set title and summary
        articles.append({
            "category": category,
            "title": item["title"],
            "summary": item["title"],
            "link": link
        })

    return {
        "source": "Multiple sources (static data)",
        "count": len(articles),
        "articles": articles
    }

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
from bs4 import BeautifulSoup

def fetch_committee_reports(limit: int = 40):
    """Fetch committee reports from specified webpage tabs."""
    URL = "https://www.ourcommons.ca/en#pw-agenda-publications"
    try:
        # Fetch webpage content
        response = requests.get(URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # List to store all reports
        reports = []

        # Extract "Projected Order of Business" data
        projected_heading = soup.find("h2", string="Projected Order of Business") or soup.find("h3", string="Projected Order of Business")
        if projected_heading:
            projected_section = projected_heading.find_next("ul") or projected_heading.find_next("div")
            if projected_section:
                items = projected_section.find_all("li") or projected_section.find_all("a")
                for item in items[:limit]:
                    title = item.get_text(strip=True) or "Projected Order of Business"
                    link = item.get("href", URL) if item.get("href") else URL
                    published = "2025-06-22"  # Updated to current date
                    description = f"Tentative working agenda listing items of business expected to be taken up on a particular sitting"
                    reports.append({"title": title, "link": link, "published": published, "description": description})
                    if len(reports) >= limit:
                        break

        # Extract "House Publications" data
        publications_heading = soup.find("h2", string="House Publications") or soup.find("h3", string="House Publications")
        if publications_heading:
            publications_section = publications_heading.find_next("ul") or publications_heading.find_next("div")
            if publications_section:
                items = publications_section.find_all("li") or publications_section.find_all("a")
                for item in items[:limit - len(reports)]:
                    title = item.get_text(strip=True) or "House Publication"
                    link = item.get("href", URL) if item.get("href") else URL
                    published = "2025-06-22"  # Updated to current date
                    description = f"Publication details for {title}"
                    reports.append({"title": title, "link": link,"description": description})
                    if len(reports) >= limit:
                        break

        # Ensure specific items with correct URLs are included
        required_items = [
            {"title": "Projected Order of Business", "link": "https://www.ourcommons.ca/DocumentViewer/en/house/latest/projected-business", "description": "Tentative working agenda listing items of business expected to be taken up on a particular sitting"},
            {"title": "Order Paper and Notice Paper", "link": "https://www.ourcommons.ca/DocumentViewer/en/house/latest/order-notice", "description": "Official agenda, listing all items that may be taken up on a particular sitting"},
            {"title": "Debates (Hansard)", "link": "https://www.ourcommons.ca/DocumentViewer/en/house/latest/hansard", "description": "Full-length record of what is said in the House"},
            {"title": "Latest Journals", "link": "https://www.ourcommons.ca/DocumentViewer/en/house/latest/journals", "description": "Official record of House decisions and transactions"}
        ]
        for item in required_items:
            if not any(existing["title"] == item["title"] for existing in reports):
                reports.append(item)
                if len(reports) >= limit:
                    break

        # Apply limit and return
        items = reports[:min(limit, len(reports))]
        return {"source": URL, "count": len(items), "reports": items}

    except Exception as e:
        return {"error": f"Web fetch error: {e}"}

# Example usage (for testing)
if __name__ == "__main__":
    result = fetch_committee_reports(4)
    import json
    print(json.dumps(result, indent=2))
import feedparser
import html
from datetime import datetime
import pytz  # This line will work once pytz is installed

def fetch_victoria_procurement():
    """Fetch Victoria procurement opportunities from RSS with status based on date."""
    feed = "https://victoria.bonfirehub.ca/opportunities/rss"
    try:
        parsed = feedparser.parse(feed)
        items = []

        # Current date and time in PKT (Asia/Karachi, UTC+5)
        pkt_tz = pytz.timezone('Asia/Karachi')
        current_date = pkt_tz.localize(datetime(2025, 6, 21, 21, 44, 0))  # 09:44 PM PKT

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

            # Determine status based on published date and keywords
            published_str = getattr(e, "published", "")
            status = "Unknown"
            if published_str:
                # Parse the published date (RSS format: e.g., "Tue, 27 May 2025 11:00:00 -0700")
                published_date = datetime.strptime(published_str, "%a, %d %b %Y %H:%M:%S %z")
                # Convert published_date to PKT for comparison
                published_date = published_date.astimezone(pkt_tz)
                # Calculate time difference in days
                time_diff = current_date - published_date
                days_diff = time_diff.total_seconds() / (60 * 60 * 24)

                if days_diff <= 30:  # Within 30 days, assume Open
                    status = "Open"
                else:  # Older than 30 days, assume Closed
                    status = "Closed"

            # Override with keyword check if applicable
            if "Open" in raw_title or "Open" in getattr(e, "summary", ""):
                status = "Open"
            elif "Closed" in raw_title or "Closed" in getattr(e, "summary", ""):
                status = "Closed"
            elif "Awarded" in raw_title or "Awarded" in getattr(e, "summary", ""):
                status = "Awarded"

            items.append(
                {
                    "ref_no": ref_no,
                    "title": title,
                    "link": e.link,
                    "published": published_str,
                    "status": status
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
@app.route('/committee_reports', methods=['GET'])
def committee_reports_route():
    limit = request.args.get('limit', default=40, type=int)
    result = fetch_committee_reports(limit)
    return jsonify(result)

# ... (previous imports and code)

# Route for fetching MP profiles
@app.route('/mps', methods=['GET'])
def mps_route():
    result = fetch_mps()
    return jsonify(result)

# ... (rest of the app)
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

# ... (previous imports and code)

# Route for federal procurement
# ... (previous imports and code)

# Route for federal procurement (committee data)
@app.route('/federal_procurement', methods=['GET'])
def tender_notices_route():
    limit = request.args.get('limit', default=10, type=int)
    offset = request.args.get('offset', default=0, type=int)
    result = fetch_tender_notices(limit, offset)
    return jsonify(result)

# ... (rest of the app)
# ... (rest of the app)
from flask import Response

@app.route("/federal_contracts", methods=["GET"])
def federal_contracts_route():
    return jsonify(fetch_federal_contracts())
# Define the route
# Route definition (top level)
@app.route('/senate_orders', methods=['GET'])
def get_senate_orders():
    # Function logic
    result = fetch_senate_orders()
    return jsonify(result)

@app.route('/debates', methods=['GET'])
def get_debates():
    date_param = request.args.get('date')  # Get date from query params
    result = fetch_debates(date_param)
    return jsonify(result)

@app.route("/canada_gazette", methods=["GET"])
def canada_gazette_route():
    return jsonify(fetch_canada_gazette()), 200
# Main block (top level)
# ... (previous imports and code)

# Route for fetching Victoria procurement opportunities
@app.route('/victoria_procurement', methods=['GET'])
def victoria_procurement_route():
    result = fetch_victoria_procurement()
    return jsonify(result)

# ... (rest of the app)

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


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

application = app

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=5000)
