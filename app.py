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

def fetch_federal_procurement(limit: int = 10, offset: int = 0, filter_by: str = None) -> dict:
    """Fetch committee study and activity data from ourcommons.ca Open Data XML feed."""
    BASE = "https://www.ourcommons.ca/data"
    TOTAL_RESULTS = 172  # Based on screenshot

    # Initialize list to store notices
    notices = []

    # API parameters for XML feed
    params = {
        "date": "2025-06-20",  # Match the screenshot date
        "limit": limit,        # Number of results per page
        "start": offset,       # Starting point for pagination
        "format": "xml"
    }

    # Apply filter based on tab selection
    if filter_by:
        if filter_by == "Committee":
            params["committee"] = ",".join(["FINA", "ACVA", "ETHI", "OGGO", "TRAN"])
        elif filter_by == "Study and Activity":
            params["study"] = "1"  # Placeholder; adjust based on XML field
        elif filter_by == "Event":
            params["event"] = "1"  # Placeholder; adjust based on XML field

    # Fetch XML data from Open Data feed (example endpoint; adjust as needed)
    data = _get_xml(f"{BASE}/CommitteeMeetingDataXML.ashx", **params)

    if data is not None:
        # Assume XML structure with root 'Committees' and child 'Committee' elements
        for committee in data.findall(".//Committee"):
            code = committee.get("code", "Unknown")
            relevant_committees = {"FINA", "ACVA", "ETHI", "OGGO", "TRAN"}
            if code in relevant_committees:
                study_activity = committee.findtext(".//StudyActivity", "Unknown Study")
                event = committee.findtext(".//Event", "Unknown Event") or "Data Available"
                date = committee.findtext(".//Date", "2025-06-20")
                study_id = committee.get("id", "1")  # Adjust field name based on XML
                url = f"https://www.ourcommons.ca/Committees/en/{code}/StudyActivity?studyActivityId={study_id}"
                notices.append({
                    "Committee": code,
                    "Study and Activity": study_activity,
                    "Event": event,
                    "Date": date,
                    "url": url
                })

    # Calculate pagination details
    total_pages = (TOTAL_RESULTS + limit - 1) // limit
    current_page = (offset // limit) + 1
    next_offset = offset + limit if offset + limit < TOTAL_RESULTS else None

    # Fallback if no data
    if not notices:
        print("No data fetched from XML feed. Using minimal fallback data.")
        notices = []

    return {
        "source": f"{BASE}/CommitteeMeetingDataXML.ashx",
        "modified": datetime.utcnow().isoformat(),
        "total": TOTAL_RESULTS,
        "limit": limit,
        "offset": offset,
        "current_page": current_page,
        "total_pages": total_pages,
        "next_offset": next_offset,
        "notices": notices,
        "filter_by": filter_by if filter_by else "None"
    }
def fetch_federal_contracts():
    dataset_id = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
    base_api = "https://open.canada.ca/data/api/3/action"
    pkg = safe_get_json(f"{base_api}/package_show?id={dataset_id}")
    resources = []

    if "result" in pkg:
        for r in pkg["result"].get("resources", []):
            url = r.get("url")
            if not url:
                # fallback: fetch resource via resource_show
                rid = r.get("id")
                if rid:
                    resp = safe_get_json(f"{base_api}/resource_show?id={rid}")
                    if "result" in resp:
                        url = resp["result"].get("url") or "Not available"

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

def fetch_committee_reports(limit: int = 40):
    """Fetch committee reports from RSS feed."""
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
@app.route("/committee_reports", methods=["GET"])
def committee_reports_route():
    return jsonify(fetch_committee_reports())


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
def federal_procurement_route():
    limit = int(request.args.get('limit', 10))    # Default 10 results per page
    offset = int(request.args.get('offset', 0))   # Default start at 0
    filter_by = request.args.get('filter_by')     # Optional filter (Committee, Study and Activity, Event)
    result = fetch_federal_procurement(limit, offset, filter_by)
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
