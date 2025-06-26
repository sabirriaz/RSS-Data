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
from datetime import datetime, timedelta
import logging
import chromedriver_autoinstaller

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


nest_asyncio.apply()
asyncio.set_event_loop(asyncio.new_event_loop())

app = Flask(__name__)

# ✅ CORS setup for your frontend domain
CORS(app, resources={
    r"/*": {
        "origins": ["https://transparencyproject.ca"],
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
    url = "https://sencanada.ca/en/senators/"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        base = "https://sencanada.ca"
        senators = []

        for a in soup.select("a[href*='/en/senators/']"):
            href = a.get("href", "")
            name = a.get_text(strip=True)
            if "/en/senators/" in href and name and len(name) > 4:
                senators.append({
                    "name": name,
                    "profile_url": base + href if href.startswith("/") else href
                })

        # Remove duplicates
        senators = list({s["name"]: s for s in senators}.values())

        return {"total_count": len(senators), "senators": senators}

    except Exception as e:
        return {"error": f"Failed to fetch senators: {e}"}

def fetch_senate_committees():
    """
    Fetches committee data from https://www.ourcommons.ca/Committees/en/Home,
    including detailed content from each committee's detail page.
    Returns a dictionary containing a list of committees and total count.
    """
    url = "https://www.ourcommons.ca/Committees/en/Home"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        result = {
            "committees": [],
            "total_count": 0
        }

        committee_section = soup.find("div", class_="committees-home-list")
        if committee_section:
            committee_links = committee_section.find_all("a", class_="list-group-linked-item")
            for link in committee_links:
                acronym = link.find("span", class_="committee-acronym-cell")
                acronym = acronym.get_text(strip=True) if acronym else "Unknown"
                name = link.find("span", class_="committee-name")
                name = name.get_text(strip=True) if name else "Unknown"
                href = link.get("href")
                if href and not href.startswith("http"):
                    href = f"https://www.ourcommons.ca{href}" if href.startswith("/") else f"https://www.ourcommons.ca/{href}"

                detailed_content = fetch_detail_page_contents(href, headers)

                result["committees"].append({
                    "acronym": acronym,
                    "name": name,
                    "url": href,
                    "detailed_content": detailed_content
                })

        result["total_count"] = len(result["committees"])
        return result

    except requests.RequestException as e:
        return {"error": f"Failed to fetch committee list: {str(e)}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred: {str(e)}"}

def fetch_detail_page_contents(url, headers):
    """
    Fetches detailed content from a committee's detail page, including recent business and members.
    """
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        result = {
            "recent_business": [],
            "members": [],
            "profile_images": {
                "desktop": "Not available",
                "mobile": "Not available"
            }
        }

        recent_work_section = soup.find("div", id="recent-work-section")
        if recent_work_section:
            items = recent_work_section.find_all("a", class_="list-group-linked-item")
            for item in items:
                title_div = item.find("div", class_="work-title")
                title = title_div.get_text(strip=True) if title_div else "Untitled"

                info_div = item.find("div", class_="additional-info")
                additional_info = info_div.get_text(strip=True) if info_div else "Not available"

                href = item.get("href", "")
                if href.startswith("//"):
                    href = f"https:{href}"
                elif href.startswith("/"):
                    href = f"https://www.ourcommons.ca{href}"
                elif not href.startswith("http"):
                    href = f"https://www.ourcommons.ca/{href}"

                result["recent_business"].append({
                    "title": title,
                    "url": href,
                    "additional_info": additional_info
                })

        members_panel = soup.find("div", id="committeeMembersPanel")
        if members_panel:
            member_sections = members_panel.find_all("div", class_="member-section")
            for section in member_sections:
                role = section.find("h2", class_="title")
                role = role.get_text(strip=True) if role else "Unknown"

                cards = section.find_all("span", class_="committee-member-card")
                for card in cards:
                    info = card.find("span", class_="member-info")
                    if not info:
                        continue

                    full_name_span = info.find("span", class_="full-name")
                    full_name = " ".join(
                        span.get_text(strip=True) for span in full_name_span.find_all(["span"])
                    ) if full_name_span else "Unknown"

                    caucus = info.find("span", class_="caucus")
                    caucus = caucus.get_text(strip=True) if caucus else "Not available"

                    constituency = info.find("span", class_="constituency")
                    constituency = constituency.get_text(strip=True) if constituency else "Not available"

                    province = info.find("span", class_="province")
                    province = province.get_text(strip=True) if province else "Not available"

                    img = card.find("img", class_="picture")
                    photo_url = img.get("src") if img else "Not available"
                    if photo_url:
                        if photo_url.startswith("//"):
                            photo_url = f"https:{photo_url}"
                        elif photo_url.startswith("/"):
                            photo_url = f"https://www.ourcommons.ca{photo_url}"

                    a_tag = card.find("a")
                    member_url = a_tag.get("href") if a_tag else "Not available"
                    if member_url:
                        if member_url.startswith("//"):
                            member_url = f"https:{member_url}"
                        elif member_url.startswith("/"):
                            member_url = f"https://www.ourcommons.ca{member_url}"

                    result["members"].append({
                        "role": role,
                        "name": full_name,
                        "caucus": caucus,
                        "constituency": constituency,
                        "province": province,
                        "photo_url": photo_url,
                        "member_url": member_url
                    })

        # --- Final fallback if empty ---
        if not result["recent_business"] and not result["members"]:
            return {"content": "No main content section found on the page"}

        return result

    except requests.RequestException as e:
        return {"error": f"Failed to fetch detail page {url}: {str(e)}"}
    except Exception as e:
        return {"error": f"An error occurred while processing {url}: {str(e)}"}


def fetch_detail_page_content(detail_url, headers):
    """
    Fetches and extracts detailed content from a committee's detail page.
    Returns a dictionary with extracted content or an error message.
    """
    try:
        response = requests.get(detail_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        content_section = soup.find("div", class_="content") or soup.find("main") or soup.find("div", id="content")
        if content_section:
            paragraphs = content_section.find_all(["p", "h1", "h2", "h3", "h4"])
            content_text = " ".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
            if content_text:
                return {"content": content_text}
            else:
                return {"content": "No detailed content found on the page"}
        else:
            return {"content": "No main content section found on the page"}

    except requests.RequestException as e:
        return {"error": f"Failed to fetch detail page {detail_url}: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing detail page {detail_url}: {str(e)}"}
    
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


def fetch_committees():
    """
    Fetches committee data from https://sencanada.ca/en/committees/,
    including detailed content from each committee's detail page.
    Returns a dictionary with lists of committees, subcommittees, joint committees, and total count.
    """
    base_url = "https://sencanada.ca/en/committees/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        result = {
            "committees": [],
            "subcommittees": [],
            "joint_committees": [],
            "total_count": 0
        }

        ajax_url = "https://sencanada.ca/en/CommitteesAjax/GetCommitteeListPartialView"
        ajax_params = {
            "parlsession": "45-1",
            "forMenu": "false"
        }
        ajax_response = requests.get(ajax_url, headers=headers, params=ajax_params)
        ajax_response.raise_for_status()

        ajax_soup = BeautifulSoup(ajax_response.text, "html.parser")

        committee_links = ajax_soup.find_all("a", href=True)
        for link in committee_links:
            href = link.get("href")
            name = link.get_text(strip=True)
            if not name or not href:
                continue
            if not href.startswith("http"):
                href = f"https://sencanada.ca{href}"

            acronym = href.split("/")[-1] if "/" in href else name[:4].upper()

            is_subcommittee = acronym in ["COMS", "DVSC", "HRRH", "LTVP", "SEBS", "VEAC"]
            is_joint_committee = acronym in ["BILI", "REGS"]

            detailed_content = fetch_detail_page_content(href, headers)

            committee_entry = {
                "acronym": acronym,
                "name": name,
                "url": href,
                "detailed_content": detailed_content
            }

            if is_subcommittee:
                result["subcommittees"].append(committee_entry)
            elif is_joint_committee:
                result["joint_committees"].append(committee_entry)
            else:
                result["committees"].append(committee_entry)

        joint_committees = [
            {"acronym": "BILI", "name": "Library of Parliament", "url": "https://www.parl.ca/Committees/en/BILI"},
            {"acronym": "REGS", "name": "Scrutiny of Regulations", "url": "https://www.parl.ca/Committees/en/REGS"}
        ]
        for jc in joint_committees:
            if not any(c["acronym"] == jc["acronym"] for c in result["joint_committees"]):
                jc["detailed_content"] = fetch_detail_page_content(jc["url"], headers)
                result["joint_committees"].append(jc)

        result["total_count"] = len(result["committees"]) + len(result["subcommittees"]) + len(result["joint_committees"])

        return result

    except requests.RequestException as e:
        return {"error": f"Failed to fetch committee data: {str(e)}"}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

def fetch_detail_page_content(detail_url, headers):
    """
    Fetches and extracts detailed content from a committee's detail page.
    Returns a dictionary with extracted content or an error message.
    """
    try:
        response = requests.get(detail_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        content_section = soup.find("div", class_="content") or soup.find("main") or soup.find("div", id="wb-main")
        if content_section:
            paragraphs = content_section.find_all(["p", "h1", "h2", "h3", "h4"])
            content_text = " ".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
            if content_text:
                return {"content": content_text}
            else:
                return {"content": "No detailed content found on the page"}
        else:
            return {"content": "No main content section found on the page"}

    except requests.RequestException as e:
        return {"error": f"Failed to fetch detail page {detail_url}: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing detail page {detail_url}: {str(e)}"}


def fetch_canada_gazette():
    """Return Canada Gazette items from the past year with full detail content for HTML links."""

    parts = {
        "Part I":  "https://www.gazette.gc.ca/rss/p1-eng.xml",
        "Part II": "https://www.gazette.gc.ca/rss/p2-eng.xml",
        "Part III": "https://www.gazette.gc.ca/rss/en-ls-eng.xml",
    }

    one_year_ago = datetime.now() - timedelta(days=365)
    publications = []

    for part_name, url in parts.items():
        feed = feedparser.parse(url)

        for entry in feed.entries:
            try:
                published_dt = datetime(*entry.published_parsed[:6])
            except Exception:
                continue  

            if published_dt < one_year_ago:
                continue 

            soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
            a_tag = soup.find("a")
            link = a_tag["href"] if a_tag and a_tag.has_attr("href") else entry.get("link", "")

            detail_content = ""
            if link.lower().endswith(".html"):
                try:
                    detail_res = requests.get(link, timeout=10)
                    if detail_res.status_code == 200:
                        page_soup = BeautifulSoup(detail_res.content, "html.parser")
                        content_blocks = page_soup.select("section, article, .cn-inset, .row, .col-md-12")
                        detail_content = "\n\n".join([
                            block.get_text(strip=True, separator="\n") for block in content_blocks
                        ])
                except Exception as e:
                    detail_content = f"Error loading detail: {e}"

            publications.append({
                "part": part_name,
                "title": entry.get("title", ""),
                "url": link,
                "published": published_dt.strftime("%Y-%m-%d"),
                "type": "PDF" if link.lower().endswith(".pdf") else "HTML",
                "detail": detail_content
            })

    return {
        "total_count": len(publications),
        "publications": publications
    }

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; DebateFetcher/1.0)',
    'Accept': 'application/json'
}
def fetch_debates(date=None):
    try:
        base_url = "https://api.openparliament.ca/debates/"
        params = {}
        if date:
            if not is_valid_date(date):
                return {'error': 'Invalid date format. Use YYYY-MM-DD.'}
            params['date'] = date

        response = requests.get(base_url, params=params, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return {'error': f"Failed to fetch debates — HTTP {response.status_code}"}
        data = response.json()
        debates = []

        for item in data.get("objects", []):
            debate_date = item.get("date")
            number = item.get("number")
            word = item.get("most_frequent_word", {}).get("en", "")
            url = f"https://openparliament.ca/debates/{debate_date.replace('-', '/')}/"
            detail = "[No speeches found]"

            if not item.get("speeches_count"):
                try:
                    html_resp = requests.get(url, headers=HEADERS, timeout=10)
                    if html_resp.status_code == 200:
                        soup = BeautifulSoup(html_resp.text, "html.parser")
                        topics_div = soup.find("div", {"id": "hansard-topics"})
                        if topics_div:
                            paragraphs = topics_div.find_all("p")
                            topic_texts = []
                            for p in paragraphs:
                                topic_texts.append(p.get_text(separator=" ", strip=True))
                            if topic_texts:
                                detail = "\n\n".join(topic_texts)
                except Exception as e:
                    detail = f"[Error scraping speeches: {str(e)}]"

            debates.append({
                "date": debate_date,
                "number": number,
                "most_frequent_word_en": word,
                "url": url,
                "detail": detail
            })

        return {
            "total_count": len(debates),
            "debates": debates
        }

    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}   
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
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
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
from fake_useragent import UserAgent
import random
def fetch_access_information():
    """Scrapes the latest Access to Information & Privacy page on Canada.ca."""
    url = (
        "https://www.canada.ca/en/treasury-board-secretariat/"
        "services/access-information-privacy.html"
    )
    
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        time.sleep(random.uniform(0.5, 2.0))  
        logger.debug(f"Fetching {url} with User-Agent: {headers['User-Agent']}")
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.title.get_text(strip=True) if soup.title else "Unknown"
        
        main = soup.find("main") or soup
        
        intro = main.select_one("div.well p")
        description = intro.get_text(strip=True) if intro else "Description not found"
        
        contact = "Contact information for coordinators by institution"  
        
        actions = []
        for a in soup.select("div.well a.btn-primary"):
            label = a.get_text(strip=True)
            href = a.get("href", "")
            if href:
                if not href.startswith("http"):
                    href = "https://www.canada.ca" + href
                actions.append({"label": label, "url": href})
        
        def parse_section_by_h2(text):
            section = soup.find("h2", string=lambda s: s and text.lower() in s.lower())
            cards = []
            if section:
                row = section.find_next_sibling("div", class_="row")
                if row:
                    for card in row.select("div.col-md-4"):
                        a = card.find("a")
                        p = card.find("p")
                        if a and p:
                            href = a.get("href", "")
                            if href and not href.startswith("http"):
                                href = "https://www.canada.ca" + href
                            cards.append({
                                "title": a.get_text(strip=True),
                                "url": href,
                                "description": p.get_text(strip=True)
                            })
            return cards
        
        services_and_info = parse_section_by_h2("Services and information")
        
        depts_and_agencies = parse_section_by_h2("For departments and agencies")
        
        features = []
        feat_sec = soup.find("section", class_="gc-features")
        if feat_sec:
            title_tag = feat_sec.find("h3")
            a = title_tag.find("a") if title_tag else None
            p = feat_sec.find("p")
            img = feat_sec.find("img")
            if a and p:
                href = a.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.canada.ca" + href
                features.append({
                    "title": a.get_text(strip=True),
                    "url": href,
                    "description": p.get_text(strip=True),
                    "image": img.get("src") if img else None
                })
        
        modified = ""
        meta_modified = soup.find("meta", {"name": "dcterms.modified"})
        if meta_modified:
            modified = meta_modified.get("content")
        elif tm := soup.find("time", property="dateModified"):
            modified = tm.get_text(strip=True)
        
        return {
            "message": title,
            "description": description,
            "url": url,
            "contact": contact,
            "actions": actions,
            "services_and_info": services_and_info,
            "departments_and_agencies": depts_and_agencies,
            "features": features,
            "modified": modified
        }
    
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {str(e)}")
        return {"error": f"Failed to fetch data: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error while scraping {url}: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}
    
from datetime import datetime
import json

def fetch_senate_calendar(limit=100):
    """Fetch Senate Meetings and Events from the website using Selenium."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        url = "https://sencanada.ca/en/calendar/"
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "tab-current"))
        ).click()

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "event-listing"))
        )

        events = []
        event_items = driver.find_elements(By.CLASS_NAME, "event-item")
        for item in event_items[:limit]:
            try:
                date_time_elem = item.find_element(By.CLASS_NAME, "event-date-time")
                date = date_time_elem.find_element(By.CLASS_NAME, "event-date").text
                time_elem = date_time_elem.find_elements(By.CLASS_NAME, "event-time")
                time = time_elem[0].text if time_elem else ""

                category = item.find_element(By.CLASS_NAME, "event-item-category-name").text

                title_elems = item.find_elements(By.CLASS_NAME, "event-item-title")
                title = title_elems[0].text if title_elems else ""

                link_elems = item.find_elements(By.CLASS_NAME, "event-detail")
                link = link_elems[0].get_attribute("href") if link_elems else ""

                savetocal_elems = item.find_elements(By.CLASS_NAME, "event-item-savetocalendar")
                savetocal = savetocal_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href") if savetocal_elems else ""

                twitter_elems = item.find_elements(By.CLASS_NAME, "event-item-social-twitter")
                twitter = twitter_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href") if twitter_elems else ""
                facebook_elems = item.find_elements(By.CLASS_NAME, "event-item-social-facebook")
                facebook = facebook_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href") if facebook_elems else ""

                if category.lower() in ["sitting day", "possible sitting day", "planned sitting day"]:
                    continue

                events.append({
                    "date": date,
                    "time": time,
                    "title": title,
                    "category": category,
                    "link": link,
                    "save_to_calendar": savetocal,
                    "twitter": twitter,
                    "facebook": facebook
                })
            except Exception as e:
                print(f"Error parsing event: {e}")
                continue

        driver.quit()

        return {
            "total": len(events),
            "events": events,
            "source": url,
            "fetched_at": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "error": f"Failed to fetch Senate calendar events: {str(e)}"
        }
        
def fetch_bills_legislation():
    """Alias of the /bills feed."""
    return fetch_bills()

def fetch_parliamentary_docs():
    """Scrape all committee records from the Committees Work page, de-duplicated."""
    base_url = "https://www.ourcommons.ca/Committees/en/Work"
    params = {
        "parl": 45,
        "ses": 1,
        "refineByCommittees": "",
        "refineByCategories": "",
        "refineByEvents": "",
        "sortBySelected": "",
        "show": "allwork",
        "pageNumber": 1,
        "pageSize": 0
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36"
    }

    committees = []
    seen = set()

    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
    except Exception as e:
        return {"error": f"Failed to load committee records: {e}"}

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table.committeestable tbody tr")

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        try:
            short_name = cols[0].find("strong").text.strip()
            full_name = cols[0].find("i")["title"].strip()
            study_cell = cols[1]
            study = study_cell.get_text(strip=True)
            link = study_cell.find("a")
            detail_url = f"https://www.ourcommons.ca{link['href']}" if link and link.get('href') else ""
            event = cols[2].get_text(strip=True)
            date = cols[3].get_text(strip=True)

            key = (short_name, study, event, date)
            if key in seen:
                continue
            seen.add(key)

            committees.append({
                "short_name": short_name,
                "full_name": full_name,
                "study": study,
                "url": detail_url,
                "event": event,
                "date": date
            })
        except Exception:
            continue

    return {
        "source": base_url,
        "count": len(committees),
        "committees": committees
    }
def fetch_senate_orders(limit: int = 30):
    """Scrape Senate order papers and extract detail content."""
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

    records = []
    seen = set()

    for rel in date_links:
        page_url = rel if rel.startswith("http") else base + rel
        if page_url in seen:
            continue
        seen.add(page_url)

        try:
            page_html = requests.get(page_url, headers=HEADERS, timeout=15).text
            page_soup = BeautifulSoup(page_html, "html.parser")
        except Exception:
            continue

        content = page_soup.select_one("main")
        detail = content.get_text(strip=True, separator="\n") if content else "No content available."

        records.append({
            "title": rel.split("/")[-1],
            "link": page_url,
            "detail": detail
        })

        if len(records) >= limit:
            break

    return {"count": len(records), "orders": records}

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

def fetch_federal_procurement(limit: int = 50):
    """Scrape federal procurement tender notices from CanadaBuys website."""
    url = "https://canadabuys.canada.ca/en/tender-opportunities"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com",
        "Connection": "keep-alive",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        return {"error": f"Failed to load tender opportunities page: {e}"}

    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.select("table tbody tr")[:limit]

    notices = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 4:
            title_cell = cols[0]
            title = title_cell.get_text(strip=True)
            link = title_cell.find("a")
            detail_url = f"https://canadabuys.canada.ca{link['href']}" if link and link.get('href') else ""
            notices.append({
                "title": title,
                "url": detail_url,
                "category": cols[1].get_text(strip=True),
                "open_or_amendment_date": cols[2].get_text(strip=True),
                "closing_date": cols[3].get_text(strip=True),
                "organization": cols[4].get_text(strip=True) if len(cols) > 4 else ""
            })

    return {
        "source": url,
        "count": len(notices),
        "notices": notices
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
                rid = r.get("id")
                if rid:
                    resp = safe_get_json(f"{base_api}/resource_show?id={rid}")
                    if "result" in resp:
                        url = resp["result"].get("url")
                        if not url and r.get("format", "").upper() == "PBIX":
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
            "publisher": pkg["result"].get("organization", {}).get("title", "Not available"),
            "keywords": pkg["result"].get("keywords", {}).get("en", []) or ["Not available"],
            "license": pkg["result"].get("license_title", "Not available"),
            "resources": resources
        }

    return {"error": "Failed to fetch dataset"}

def get_article_content(link):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    try:
        r = requests.get(link, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        for selector in ['div.article-body', 'div#details-body', 'article']:
            container = soup.select_one(selector)
            if container:
                text = "\n".join(p.get_text(" ", strip=True) for p in container.find_all("p"))
                if text.strip():
                    return text.strip()
        return "[No content found]"
    except Exception as e:
        return f"[Error fetching content: {e}]"

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
    
def fetch_canadian_news():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    feed_url = "https://www.villagereport.ca/feed"
    articles = []

    try:
        logger.debug(f"Fetching RSS feed from {feed_url}")
        feed = feedparser.parse(feed_url)
        if feed.bozo == 0 and feed.entries:
            logger.debug(f"Found {len(feed.entries)} entries in RSS feed")
            for entry in feed.entries:
                summary = BeautifulSoup(getattr(entry, "summary", ""), "html.parser").get_text(" ", strip=True)
                articles.append({
                    "title": entry.title,
                    "summary": summary,
                    "link": entry.link,
                    "content": ""
                })
            logger.info(f"Extracted {len(articles)} articles from RSS feed")
            return {"source": feed_url, "count": len(articles), "articles": articles}
        else:
            logger.warning("RSS feed is empty or invalid, falling back to HTML scraping")
    except Exception as e:
        logger.error(f"Failed to parse RSS feed: {str(e)}")

    url = "https://www.villagereport.ca"
    try:
        logger.debug(f"Fetching HTML from {url}")
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        articles = []

        village_picks = soup.select("div.widget-cards a.card")
        for card in village_picks:
            title_tag = card.find("div", class_="card-title")
            title = title_tag.get_text(" ", strip=True) if title_tag else ""
            link = card.get("href", "")
            if not link.startswith("http"):
                link = url.rstrip("/") + link
            if title and link:
                articles.append({
                    "title": title,
                    "summary": "",
                    "link": link,
                    "content": ""
                })

        for section in soup.select("div.widget-canfeature"):
            main_card = section.find("div", class_="card")
            if main_card:
                title_tag = main_card.find("a", class_="card-title")
                title = title_tag.get_text(" ", strip=True) if title_tag else ""
                link = title_tag.get("href", "") if title_tag else ""
                if not link.startswith("http"):
                    link = url.rstrip("/") + link
                if title and link:
                    articles.append({
                        "title": title,
                        "summary": "",
                        "link": link,
                        "content": ""
                    })

            for item in section.select("ul.card-list a.card-title"):
                title = item.get_text(" ", strip=True)
                link = item.get("href", "")
                if not link.startswith("http"):
                    link = url.rstrip("/") + link
                if title and link:
                    articles.append({
                        "title": title,
                        "summary": "",
                        "link": link,
                        "content": ""
                    })

        seen_links = set()
        unique_articles = []
        for article in articles:
            if article["link"] not in seen_links:
                unique_articles.append(article)
                seen_links.add(article["link"])
        articles = unique_articles

        for article in articles:
            try:
                logger.debug(f"Fetching detail page for: {article['link']}")
                r = requests.get(article["link"], headers=headers, timeout=10)
                r.raise_for_status()
                detail_soup = BeautifulSoup(r.text, "html.parser")

                summary_tag = detail_soup.find("meta", property="og:description")
                if summary_tag and summary_tag.get("content"):
                    article["summary"] = summary_tag["content"]
                else:
                    summary_paragraphs = detail_soup.select("#details-body p")[:3]
                    summary = " ".join(p.get_text(" ", strip=True) for p in summary_paragraphs)
                    article["summary"] = summary if summary else "No summary available"

                content_paragraphs = detail_soup.select("#details-body p")
                content = "\n\n".join(p.get_text(" ", strip=True) for p in content_paragraphs)
                article["content"] = content if content else "No content available"

                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Failed to fetch summary/content for {article['link']}: {str(e)}")
                article["summary"] = article.get("summary", "Failed to fetch summary")
                article["content"] = "Failed to fetch content"

        logger.info(f"Extracted {len(articles)} unique articles with summaries and content")

        return {
            "source": url,
            "count": len(articles),
            "articles": articles
        }

    except Exception as e:
        logger.error(f"Failed to scrape HTML: {str(e)}")
        return {"source": url, "count": 0, "articles": []}

def fetch_member_urls(province_url, province_id, base_url="https://portal.fcm.ca"):
    """Fetch member URLs for a given province URL and ID."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    member_urls = []
    page = 1
    max_pages = 50  

    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument(f"user-agent={headers['User-Agent']}")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        while page <= max_pages:
            member_list_url = f"{base_url}/member-listing/?name_en=0&name_fr=0&filtertype=0&page={page}&province={province_id}&alphabet_en=0&alphabet_fr=0"
            logger.debug(f"Fetching member data for page {page} from {member_list_url}")

            driver.get(member_list_url)
            
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "MemberListing"))
                )
            except Exception as e:
                if "SignIn" in driver.current_url:
                    logger.warning(f"Authentication required for province ID {province_id}. Please provide login credentials.")
                    break
                logger.debug(f"Member listing not found on page {page}: {str(e)}")
                break  

            soup = BeautifulSoup(driver.page_source, "html.parser")
            member_listing = soup.find("div", {"id": "MemberListing"}) or soup.find("table", {"class": "table-striped"})

            if not member_listing:
                logger.debug(f"No member listing found for province ID {province_id} on page {page}")
                break

            page_urls = []
            for link in member_listing.find_all("a", href=True):
                href = link["href"]
                if href.startswith("/"):  
                    full_url = f"{base_url}{href}"
                    page_urls.append(full_url)
                    logger.debug(f"Found member URL: {full_url}")
                elif href.startswith("http"): 
                    page_urls.append(href)
                    logger.debug(f"Found member URL: {href}")

            if not page_urls:
                logger.debug(f"No member URLs found on page {page} for province ID {province_id}")
                break  

            member_urls.extend(page_urls)
            page += 1
            time.sleep(1) 

        driver.quit()
        logger.info(f"Extracted {len(member_urls)} member URLs for province ID {province_id}")
        return list(set(member_urls))  

    except Exception as e:
        logger.error(f"Error fetching member URLs for province ID {province_id}: {str(e)}")
        if "driver" in locals():
            driver.quit()
        return []

def fetch_municipal_councillors():
    """Fetch full table of provinces from FCM’s site using Selenium, including member URLs."""
    url = "https://portal.fcm.ca/our-members/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  
        options.add_argument(f"user-agent={headers['User-Agent']}")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        logger.debug(f"Fetching data from {url} with Selenium")
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "table-striped"))
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        table = soup.find("table", {"class": "table-striped"})
        if not table:
            logger.error("Table with class 'table-striped' not found")
            return {"error": "FCM table not found"}

        data = []
        for row in table.tbody.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) != 3:
                logger.debug(f"Skipping row with {len(cols)} columns: {cols}")
                continue

            province_cell = cols[0]
            province = province_cell.get_text(strip=True)
            link = province_cell.find("a")
            province_url = link["href"] if link and link.has_attr("href") else None

            members = cols[1].get_text(strip=True)
            percent = cols[2].get_text(strip=True)

            if "do not use" in province.lower():
                continue

            if not province or not members or not percent or not province_url:
                logger.warning(f"Skipping row with empty values: province={province}, members={members}, percent={percent}, url={province_url}")
                continue

            percent_cleaned = percent.replace("%", "").strip()
            try:
                members_int = int(members)
                percent_float = float(percent_cleaned)
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping row due to invalid numeric values: province={province}, members={members}, percent={percent_cleaned}, error={str(e)}")
                continue

            parsed_url = urllib.parse.urlparse(province_url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            province_id = query_params.get("id", [None])[0]

            full_province_url = f"https://portal.fcm.ca{province_url}" if province_url else None
            member_urls = fetch_member_urls(full_province_url, province_id) if province_id else []

            data.append({
                "province": province,
                "members": members_int,
                "population_percentage": f"{percent_float}%",
                "url": full_province_url,
                "member_urls": member_urls
            })
            logger.debug(f"Added row: {province}, {members_int}, {percent_float}%, {full_province_url}, {len(member_urls)} member URLs")

        if not data:
            logger.error("No valid data found in table after processing all rows")
            return {"error": "No valid data found in table"}

        logger.info(f"Successfully extracted {len(data)} valid rows")
        return {"objects": data}

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        if "driver" in locals():
            driver.quit()
        return {"error": f"Unexpected error: {str(e)}"}
       
class DynamicCommonsScraper:
    def __init__(self):
        self.base_url = "https://www.ourcommons.ca"
        self.ua = UserAgent()
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-CA,en-US;q=0.7,en;q=0.3',
            'DNT': '1',
        })
        self.common_selectors = {
            'item': ['.report-item', '.document-item', '.list-item', '[role="article"]', '.card'],
            'title': ['.title', 'h3', 'h4', '.document-title'],
            'link': ['a[href]'],
            'date': ['.date', '.pub-date', 'time', '.document-date'],
            'description': ['.description', '.summary', 'p']
        }

    def _rotate_headers(self):
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Referer': random.choice([
                self.base_url,
                f"{self.base_url}/Committees",
                f"{self.base_url}/Publications"
            ])
        })

    def _smart_request(self, url, max_retries=3):
        for attempt in range(max_retries):
            try:
                self._rotate_headers()
                response = self.session.get(url, timeout=(10, 20))
                response.raise_for_status()
                
                if any(blocked in response.text.lower() 
                       for blocked in ['access denied', 'captcha', 'bot detected']):
                    time.sleep(random.uniform(5, 10))
                    continue
                    
                return response
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                time.sleep((attempt + 1) * random.uniform(2, 5))

    def _detect_structure(self, soup):
        """Dynamically identify the content structure"""
        structure = {}
        for element_type, selectors in self.common_selectors.items():
            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    structure[element_type] = {
                        'selector': selector,
                        'sample_size': len(elements),
                        'example': elements[0].get_text(strip=True)[:50] + '...' if elements else None
                    }
                    break
        return structure

    def _dynamic_parse(self, item, structure):
        """Parse items based on detected structure"""
        result = {}
        
        if 'title' in structure:
            title_elem = item.select_one(structure['title']['selector'])
            if title_elem:
                result['title'] = title_elem.get_text(strip=True)
                link_elem = title_elem if title_elem.name == 'a' else title_elem.find('a')
                if link_elem and 'href' in link_elem.attrs:
                    result['link'] = (
                        self.base_url + link_elem['href'] 
                        if link_elem['href'].startswith('/') 
                        else link_elem['href']
                    )

        if 'date' in structure:
            date_elem = item.select_one(structure['date']['selector'])
            if date_elem:
                result['published'] = date_elem.get_text(strip=True)
                if 'datetime' in date_elem.attrs:
                    result['published'] = date_elem['datetime']

        if 'description' in structure:
            desc_elem = item.select_one(structure['description']['selector'])
            if desc_elem:
                result['description'] = desc_elem.get_text(strip=True)

        return result

    def scrape_reports(self, limit=40):
        """Main scraping method with dynamic structure detection"""
        entry_points = [
            f"{self.base_url}/Committees/en/AllReports",
            f"{self.base_url}/Committees/en/Reports",
            f"{self.base_url}/Publications/en/Search?type=committee+report",
            f"{self.base_url}/DocumentSearch/en?type=report"
        ]

        for url in entry_points:
            try:
                response = self._smart_request(url)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                structure = self._detect_structure(soup)
                if not structure.get('item'):
                    continue
                    
                container = None
                for selector in ['.results-container', '.listing', '#content', 'main']:
                    container = soup.select_one(selector)
                    if container:
                        break
                
                items = container.select(structure['item']['selector']) if container else []
                if not items:
                    continue
                    
                reports = []
                for item in items[:limit]:
                    try:
                        report = self._dynamic_parse(item, structure)
                        if any(report.values()):  
                            reports.append(report)
                    except Exception:
                        continue
                
                if reports:
                    return {
                        'source': url,
                        'structure_detected': structure,
                        'count': len(reports),
                        'reports': reports,
                        'retrieved_at': datetime.now().isoformat(),
                        'method': 'dynamic_parsing'
                    }
                    
            except Exception as e:
                continue

        return {
            'error': "Could not find report data using dynamic detection",
            'tried_urls': entry_points,
            'retrieved_at': datetime.now().isoformat()
        }
def fetch_victoria_procurement():
    """Fetch Victoria procurement opportunities with close_date and status (no Selenium)."""
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

            link = e.link
            close_date = ""
            status = ""

            try:
                resp = requests.get(link, timeout=10)
                soup = BeautifulSoup(resp.text, "html.parser")

                def extract_details(soup):
                    result = {}

                    for row in soup.select("table tr"):
                        cols = row.find_all(["th", "td"])
                        if len(cols) >= 2:
                            label = cols[0].get_text(strip=True).rstrip(":").lower()
                            value = cols[1].get_text(strip=True)
                            result[label] = value

                    for dt in soup.find_all("dt"):
                        dd = dt.find_next_sibling("dd")
                        if dd:
                            label = dt.get_text(strip=True).rstrip(":").lower()
                            value = dd.get_text(strip=True)
                            result[label] = value

                    page_text = soup.get_text(separator="\n")
                    for label in ["Close Date", "Status"]:
                        key = label.lower()
                        if key not in result:
                            match = re.search(rf"{label}\s*[:\-]?\s*(.+)", page_text, re.IGNORECASE)
                            if match:
                                result[key] = match.group(1).strip()

                    return result

                details = extract_details(soup)
                close_date = details.get("close date", "")
                status = details.get("status", "")

            except Exception as err:
                print(f"Error parsing {link}: {err}")

            items.append({
                "ref_no": ref_no,
                "title": title,
                "link": link,
                "published": getattr(e, "published", ""),
                "status": status,
                "close_date": close_date,
                "view_opportunity": link
            })

        return {
            "source": feed,
            "total": len(items),
            "opportunities": items
        }

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
    try:
        result = fetch_canada_gazette()
        return jsonify(result), 200
    except Exception as e:
        import traceback
        print("Error occurred:", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
def fetch_committee_reports():
    """
    Fetches agenda and publication data from https://www.ourcommons.ca/en#pw-agenda-publications,
    including detailed content from each publication's detail page.
    Returns a dictionary containing agenda details and publication data with detailed content.
    """
    url = "https://www.ourcommons.ca/en"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        result = {
            "agenda": {},
            "publications": []
        }

        agenda_section = soup.find("div", id="agenda-list-item")
        if agenda_section:
            subtitle = agenda_section.find("div", class_="subtitle")
            agenda_content = agenda_section.find_all("div")[-1]

            result["agenda"] = {
                "date": subtitle.get_text(strip=True) if subtitle else "N/A",
                "details": agenda_content.get_text(strip=True) if agenda_content else "No agenda available"
            }

        publication_section = soup.find("div", id="publication-list-item")
        if publication_section:
            publication_links = publication_section.find_all("a", class_="latest-house-publication-widget-link")
            for link in publication_links:
                publication_button = link.find("div", class_="publication-button")
                if publication_button:
                    title = publication_button.find("strong").get_text(strip=True)
                    description = publication_button.find("p", class_="button-paragraph").get_text(strip=True)
                    href = link.get("href")
                    if href and not href.startswith("http"):
                        href = f"https://www.ourcommons.ca{href}"

                    detailed_content = fetch_detail_page_content(href, headers)

                    result["publications"].append({
                        "title": title,
                        "description": description,
                        "url": href,
                        "detailed_content": detailed_content
                    })

        return result

    except requests.RequestException as e:
        return {"error": f"Failed to fetch main page data: {str(e)}"}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

def fetch_detail_page_content(detail_url, headers):
    """
    Fetches and extracts detailed content from a publication's detail page.
    Returns a dictionary with extracted content or an error message.
    """
    try:
        response = requests.get(detail_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        content_section = soup.find("div", class_="content") or soup.find("div", id="content") or soup.find("main")
        if content_section:
            paragraphs = content_section.find_all(["p", "h1", "h2", "h3", "h4"])
            content_text = " ".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
            if content_text:
                return {"content": content_text}
            else:
                return {"content": "No detailed content found on the page"}
        else:
            return {"content": "No main content section found on the page"}

    except requests.RequestException as e:
        return {"error": f"Failed to fetch detail page {detail_url}: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing detail page {detail_url}: {str(e)}"}


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

@app.route('/senate_calendar', methods=['GET'])
def senate_calendar_route():
    limit = int(request.args.get('limit', 100))
    date_filter = request.args.get('date') 
    data = fetch_senate_calendar(limit=limit)
    if date_filter and "events" in data:
        data["events"] = [e for e in data["events"] if date_filter in e["date"]]
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
    return jsonify(fetch_municipal_councillors())


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
    serve(app, host='0.0.0.0', port=5000)


# Step 3: Global fallback for safety
@app.after_request
def apply_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "https://transparencyproject.ca"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response
    
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "Welcome to the Transparency Project API",
        "status": "running"
    }), 200
