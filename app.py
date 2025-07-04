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

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


nest_asyncio.apply()
asyncio.set_event_loop(asyncio.new_event_loop())

app = Flask(__name__)

# ✅ CORS setup for your frontend domain
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:5173",          # for local React/Vite dev
            "https://transparencyproject.ca"  # your production frontend
        ],
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


@app.route('/senators', methods=['GET'])
def get_senators():
    senators = [{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ziad-aboultaif(89156)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AboultaifZiad_CPC.jpg","ce-mip-mp-name":"Ziad Aboultaif","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Manning","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sima-acan(123092)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AcanSima_Lib.jpg","ce-mip-mp-name":"Sima Acan","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Oakville West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/scott-aitchison(105340)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/AitchisonScott_CPC.jpg","ce-mip-mp-name":"Scott Aitchison","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Parry Sound—Muskoka","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/fares-al-soud(123033)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AlSoudFares_Lib.jpg","ce-mip-mp-name":"Fares Al Soud","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dan-albas(72029)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/AlbasDan_CPC.jpg","ce-mip-mp-name":"Dan Albas","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Okanagan Lake West—South Kelowna","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shafqat-ali(110339)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AliShafqat_Lib.jpg","ce-mip-mp-name":"Shafqat Ali","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brampton—Chinguacousy Park","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dean-allison(25446)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AllisonDean_CPC.jpg","ce-mip-mp-name":"Dean Allison","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Niagara West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rebecca-alty(123675)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AltyRebecca_Lib.jpg","ce-mip-mp-name":"Rebecca Alty","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Northwest Territories","ce-mip-mp-province":"Northwest Territories","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anita-anand(96081)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AnandAnita_Lib.jpg","ce-mip-mp-name":"Anita Anand","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Oakville East","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gary-anandasangaree(89449)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AnandasangareeGary_Lib.jpg","ce-mip-mp-name":"Gary Anandasangaree","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough—Guildwood—Rouge Park","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/scott-anderson(89259)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AndersonScott_CPC.jpg","ce-mip-mp-name":"Scott Anderson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Vernon—Lake Country—Monashee","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/carol-anstey(109872)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AnsteyCarol_CPC.jpg","ce-mip-mp-name":"Carol Anstey","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Long Range Mountains","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mel-arnold(89294)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ArnoldMel_CPC.jpg","ce-mip-mp-name":"Mel Arnold","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kamloops—Shuswap—Central Rockies","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chak-au(123608)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AuChak_CPC.jpg","ce-mip-mp-name":"Chak Au","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Richmond Centre—Marpole","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tatiana-auguste(122753)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/AugusteTatiana_Lib.jpg","ce-mip-mp-name":"Tatiana Auguste","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Terrebonne","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/roman-baber(123276)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BaberRoman_CPC.jpg","ce-mip-mp-name":"Roman Baber","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"York Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/burton-bailey(123500)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BaileyBurton_CPC.jpg","ce-mip-mp-name":"Burton Bailey","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Red Deer","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/parm-bains(111067)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BainsParm_Lib.jpg","ce-mip-mp-name":"Parm Bains","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Richmond East—Steveston","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/yvan-baker(105121)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BakerYvan_Lib.jpg","ce-mip-mp-name":"Yvan Baker","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Etobicoke Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tony-baldinelli(30330)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BaldinelliTony_CPC.jpg","ce-mip-mp-name":"Tony Baldinelli","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Niagara Falls—Niagara-on-the-Lake","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/karim-bardeesy(123214)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BardeesyKarim_Lib.jpg","ce-mip-mp-name":"Karim Bardeesy","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Taiaiako'n—Parkdale—High Park","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-barlow(86261)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BarlowJohn_CPC.jpg","ce-mip-mp-name":"John Barlow","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Foothills","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-barrett(102275)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BarrettMichael_CPC.jpg","ce-mip-mp-name":"Michael Barrett","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Leeds—Grenville—Thousand Islands—Rideau Lakes","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/xavier-barsalou-duval(88422)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Barsalou-DuvalXavier_BQ.jpg","ce-mip-mp-name":"Xavier Barsalou-Duval","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Pierre-Boucher—Les Patriotes—Verchères","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jaime-battiste(104571)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BattisteJaime_Lib.jpg","ce-mip-mp-name":"Jaime Battiste","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Cape Breton—Canso—Antigonish","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mario-beaulieu(376)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BeaulieuMario_BQ.jpg","ce-mip-mp-name":"Mario Beaulieu","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"La Pointe-de-l'Île","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/terry-beech(89236)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BeechTerry_Lib.jpg","ce-mip-mp-name":"Terry Beech","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Burnaby North—Seymour","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/buckley-belanger(110791)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BelangerBuckley_Lib.jpg","ce-mip-mp-name":"Buckley Belanger","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Desnethé—Missinippi—Churchill River","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jim-belanger(123208)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BelangerJim_CPC.jpg","ce-mip-mp-name":"Jim Bélanger","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Sudbury East—Manitoulin—Nickel Belt","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rachel-bendayan(88567)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BendayanRachel_Lib.jpg","ce-mip-mp-name":"Rachel Bendayan","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Outremont","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/luc-berthold(88541)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BertholdLuc_CPC.jpg","ce-mip-mp-name":"Luc Berthold","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Mégantic—L'Érable—Lotbinière","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/david-bexte(123372)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BexteDavid_CPC.jpg","ce-mip-mp-name":"David Bexte","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Bow River","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/james-bezan(25475)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BezanJames_CPC.jpg","ce-mip-mp-name":"James Bezan","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Selkirk—Interlake—Eastman","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chris-bittle(88934)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BittleChris_Lib.jpg","ce-mip-mp-name":"Chris Bittle","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"St. Catharines","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bill-blair(88961)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BlairBill_Lib.jpg","ce-mip-mp-name":"Bill Blair","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough Southwest","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/yves-francois-blanchet(104669)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/BlanchetYves-Fran%C3%A7ois_BQ.jpg","ce-mip-mp-name":"Yves-François Blanchet","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Beloeil—Chambly","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/maxime-blanchette-joncas(104705)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Blanchette-JoncasMaxime_BQ.jpg","ce-mip-mp-name":"Maxime Blanchette-Joncas","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Rimouski—La Matapédia","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kelly-block(59156)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BlockKelly_CPC.jpg","ce-mip-mp-name":"Kelly Block","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Carlton Trail—Eagle Creek","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kody-blois(104555)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BloisKody_Lib.jpg","ce-mip-mp-name":"Kody Blois","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Kings—Hants","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/patrick-bonin(122709)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BoninPatrick_BQ.jpg","ce-mip-mp-name":"Patrick Bonin","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Repentigny","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/steven-bonk(123361)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BonkSteven_CPC.jpg","ce-mip-mp-name":"Steven Bonk","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Souris—Moose Mountain","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kathy-borrelli(110706)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BorrelliKathy_CPC.jpg","ce-mip-mp-name":"Kathy Borrelli","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Windsor—Tecumseh—Lakeshore","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alexandre-boulerice(58775)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BoulericeAlexandre_NDP.jpg","ce-mip-mp-name":"Alexandre Boulerice","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Rosemont—La Petite-Patrie","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/richard-bragdon(88369)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BragdonRichard_CPC.jpg","ce-mip-mp-name":"Richard Bragdon","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Tobique—Mactaquac","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-brassard(88674)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BrassardJohn_CPC.jpg","ce-mip-mp-name":"John Brassard","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Barrie South—Innisfil","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/elisabeth-briere(104977)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Bri%C3%A8re%C3%89lisabeth_Lib.jpg","ce-mip-mp-name":"Élisabeth Brière","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Sherbrooke","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/larry-brock(110354)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/BrockLarry_CPC.jpg","ce-mip-mp-name":"Larry Brock","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Brantford—Brant South—Six Nations","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alexis-brunelle-duceppe(104786)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Brunelle-DuceppeAlexis_BQ.jpg","ce-mip-mp-name":"Alexis Brunelle-Duceppe","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Lac-Saint-Jean","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/blaine-calkins(35897)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/CalkinsBlaine_CPC.jpg","ce-mip-mp-name":"Blaine Calkins","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Ponoka—Didsbury","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/frank-caputo(111007)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CaputoFrank_CPC.jpg","ce-mip-mp-name":"Frank Caputo","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kamloops—Thompson—Nicola","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mark-carney(28286)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CarneyMark_Lib.jpg","ce-mip-mp-name":"Mark Carney","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Nepean","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Right Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ben-carr(115744)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CarrBen_lib.jpg","ce-mip-mp-name":"Ben Carr","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Winnipeg South Centre","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sean-casey(71270)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CaseySean_Lib.jpg","ce-mip-mp-name":"Sean Casey","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Charlottetown","ce-mip-mp-province":"Prince Edward Island","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bardish-chagger(89000)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChaggerBardish_Lib.jpg","ce-mip-mp-name":"Bardish Chagger","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Waterloo","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/adam-chambers(110649)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChambersAdam_CPC.jpg","ce-mip-mp-name":"Adam Chambers","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Simcoe North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/francois-philippe-champagne(88633)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChampagneFrancois-Philippe_Lib.jpg","ce-mip-mp-name":"François-Philippe Champagne","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Saint-Maurice—Champlain","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/martin-champoux(104741)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChampouxMartin_BQ.jpg","ce-mip-mp-name":"Martin Champoux","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Drummond","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/wade-chang(123520)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChangWade_Lib.jpg","ce-mip-mp-name":"Wade Chang","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Burnaby Central","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rebecca-chartrand(89464)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChartrandRebecca_Lib.jpg","ce-mip-mp-name":"Rebecca Chartrand","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Churchill—Keewatinook Aski","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sophie-chatel(110225)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChatelSophie_Lib.jpg","ce-mip-mp-name":"Sophie Chatel","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Pontiac—Kitigan Zibi","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shaun-chen(88953)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/ChenShaun_Lib.jpg","ce-mip-mp-name":"Shaun Chen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/madeleine-chenette(122756)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChenetteMadeleine_Lib.jpg","ce-mip-mp-name":"Madeleine Chenette","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Thérèse-De Blainville","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/maggie-chi(122899)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChiMaggie_Lib.jpg","ce-mip-mp-name":"Maggie Chi","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Don Valley North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-d-chong(25488)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChongMichaelD_CPC.jpg","ce-mip-mp-name":"Michael D. Chong","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Wellington—Halton Hills North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/leslie-church(119705)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ChurchLeslie_Lib.jpg","ce-mip-mp-name":"Leslie Church","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Toronto—St. Paul's","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/braedon-clark(122437)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ClarkBraedon_Lib.jpg","ce-mip-mp-name":"Braedon Clark","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Sackville—Bedford—Preston","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sandra-cobena(123060)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CobenaSandra_CPC.jpg","ce-mip-mp-name":"Sandra Cobena","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Newmarket—Aurora","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/connie-cody(110365)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CodyConnie_CPC.jpg","ce-mip-mp-name":"Connie Cody","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Cambridge","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/paul-connors(122369)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ConnorsPaul_Lib.jpg","ce-mip-mp-name":"Paul Connors","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Avalon","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-cooper(89219)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CooperMichael_CPC.jpg","ce-mip-mp-name":"Michael Cooper","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"St. Albert—Sturgeon River","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/serge-cormier(88350)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CormierSerge_Lib.jpg","ce-mip-mp-name":"Serge Cormier","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Acadie—Bathurst","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-coteau(110373)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/CoteauMichael_Lib.jpg","ce-mip-mp-name":"Michael Coteau","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough—Woburn","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chris-dentremont(49344)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DEntremontChris_CPC.jpg","ce-mip-mp-name":"Chris d'Entremont","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Acadie—Annapolis","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/julie-dabrusin(88994)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DabrusinJulie_Lib.jpg","ce-mip-mp-name":"Julie Dabrusin","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Toronto—Danforth","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marc-dalton(35909)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DaltonMarc_CPC.jpg","ce-mip-mp-name":"Marc Dalton","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Pitt Meadows—Maple Ridge","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/raquel-dancho(105521)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DanchoRaquel_CPC.jpg","ce-mip-mp-name":"Raquel Dancho","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kildonan—St. Paul","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marianne-dandurand(122559)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DandurandMarianne_Lib.jpg","ce-mip-mp-name":"Marianne Dandurand","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Compton—Stanstead","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-paul-danko(122959)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DankoJohn-Paul_Lib.jpg","ce-mip-mp-name":"John-Paul Danko","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Hamilton West—Ancaster—Dundas","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/scot-davidson(102653)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DavidsonScot_CPC.jpg","ce-mip-mp-name":"Scot Davidson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"New Tecumseth—Gwillimbury","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/don-davies(59325)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DaviesDon_NDP.jpg","ce-mip-mp-name":"Don Davies","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Vancouver Kingsway","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/fred-davies(123073)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DaviesFred_CPC.jpg","ce-mip-mp-name":"Fred Davies","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Niagara South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mike-dawson(122476)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DawsonMike_CPC.jpg","ce-mip-mp-name":"Mike Dawson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Miramichi—Grand Lake","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/claude-debellefeuille(35315)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/DeBellefeuilleClaude_BQ.jpg","ce-mip-mp-name":"Claude DeBellefeuille","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Beauharnois—Salaberry—Soulanges—Huntingdon","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gerard-deltell(88535)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DeltellGerard_CPC.jpg","ce-mip-mp-name":"Gérard Deltell","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Louis-Saint-Laurent—Akiawenhrahk","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kelly-deridder(122988)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DeRidderKelly_CPC.jpg","ce-mip-mp-name":"Kelly DeRidder","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kitchener Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/guillaume-deschenes-theriault(122473)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Deschenes-TheriaultGuillaume_Lib.jpg","ce-mip-mp-name":"Guillaume Deschênes-Thériault","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Madawaska—Restigouche","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alexis-deschenes(122579)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Desch%C3%AAnesAlexis_BQ.jpg","ce-mip-mp-name":"Alexis Deschênes","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Gaspésie—Les Îles-de-la-Madeleine—Listuguj","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/caroline-desrochers(110124)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DesrochersCaroline_Lib.jpg","ce-mip-mp-name":"Caroline Desrochers","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Trois-Rivières","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sukh-dhaliwal(31098)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DhaliwalSukh_Lib.jpg","ce-mip-mp-name":"Sukh Dhaliwal","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Surrey Newton","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anju-dhillon(88453)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/DhillonAnju_Lib.jpg","ce-mip-mp-name":"Anju Dhillon","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Dorval—Lachine—LaSalle","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/lena-metlege-diab(109915)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DiabLenaMetlege_Lib.jpg","ce-mip-mp-name":"Lena Metlege Diab","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Halifax West","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kerry-diotte(89150)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DiotteKerry_CPC.jpg","ce-mip-mp-name":"Kerry Diotte","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Griesbach","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/todd-doherty(89249)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DohertyTodd_CPC.jpg","ce-mip-mp-name":"Todd Doherty","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Cariboo—Prince George","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/terry-dowdall(105410)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DowdallTerry_CPC.jpg","ce-mip-mp-name":"Terry Dowdall","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Simcoe—Grey","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jean-yves-duclos(89408)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DuclosJean-Yves_Lib.jpg","ce-mip-mp-name":"Jean-Yves Duclos","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Québec Centre","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/terry-duguid(31119)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/DuguidTerry_Lib.jpg","ce-mip-mp-name":"Terry Duguid","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Winnipeg South","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/eric-duncan(105422)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DuncanEric_CPC.jpg","ce-mip-mp-name":"Eric Duncan","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Stormont—Dundas—Glengarry","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/julie-dzerowicz(88721)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/DzerowiczJulie_Lib.jpg","ce-mip-mp-name":"Julie Dzerowicz","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Davenport","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/philip-earle(122380)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/EarlePhilip_Lib.jpg","ce-mip-mp-name":"Philip Earle","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Labrador","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ali-ehsassi(89010)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/EhsassiAli_Lib.jpg","ce-mip-mp-name":"Ali Ehsassi","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Willowdale","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/faycal-el-khoury(88515)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ElKhouryFay%C3%A7al_Lib.jpg","ce-mip-mp-name":"Fayçal El-Khoury","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Laval—Les Îles","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dave-epp(105082)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/EppDave_CPC.jpg","ce-mip-mp-name":"Dave Epp","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Chatham-Kent—Leamington","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/nathaniel-erskine-smith(88687)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Erskine-SmithNathaniel_lib.jpg","ce-mip-mp-name":"Nathaniel Erskine-Smith","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Beaches—East York","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/doug-eyolfson(89027)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/EyolfsonDoug_Lib.jpg","ce-mip-mp-name":"Doug Eyolfson","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Winnipeg West","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rosemarie-falk(98749)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FalkRosemarie_CPC.jpg","ce-mip-mp-name":"Rosemarie Falk","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Battlefords—Lloydminster—Meadow Lake","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ted-falk(84672)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FalkTed_CPC.jpg","ce-mip-mp-name":"Ted Falk","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Provencher","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jessica-fancy(122443)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Fancy-LandryJessica_Lib.jpg","ce-mip-mp-name":"Jessica Fancy","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"South Shore—St. Margarets","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bruce-fanjoy(122850)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FanjoyBruce_Lib.jpg","ce-mip-mp-name":"Bruce Fanjoy","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Carleton","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/greg-fergus(88478)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FergusGreg_Lib.jpg","ce-mip-mp-name":"Greg Fergus","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Hull—Aylmer","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/darren-fisher(88323)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/FisherDarren_Lib.jpg","ce-mip-mp-name":"Darren Fisher","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Dartmouth—Cole Harbour","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/peter-fonseca(71692)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FonsecaPeter_Lib.jpg","ce-mip-mp-name":"Peter Fonseca","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga East—Cooksville","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mona-fortier(96356)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FortierMona_Lib.jpg","ce-mip-mp-name":"Mona Fortier","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ottawa—Vanier—Gloucester","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rheal-eloi-fortin(88605)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FortinRh%C3%A9al_BQ.jpg","ce-mip-mp-name":"Rhéal Éloi Fortin","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Rivière-du-Nord","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/peter-fragiskatos(88827)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FragiskatosPeter_Lib.jpg","ce-mip-mp-name":"Peter Fragiskatos","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"London Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sean-fraser(88316)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/FraserSean_Lib.jpg","ce-mip-mp-name":"Sean Fraser","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Central Nova","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chrystia-freeland(84665)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FreelandChrystia_Lib.jpg","ce-mip-mp-name":"Chrystia Freeland","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"University—Rosedale","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/hedy-fry(1589)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FryHedy_Lib.jpg","ce-mip-mp-name":"Hedy Fry","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vancouver Centre","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/stephen-fuhr(89279)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/FuhrStephen_Lib.jpg","ce-mip-mp-name":"Stephen Fuhr","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Kelowna","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/iqwinder-gaheer(110534)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GaheerIqwinder_Lib.jpg","ce-mip-mp-name":"Iqwinder Gaheer","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga—Malton","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anna-gainey(115736)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GaineyAnna_Lib.jpg","ce-mip-mp-name":"Anna Gainey","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Notre-Dame-de-Grâce—Westmount","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/cheryl-gallant(1809)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/GallantCheryl_CPC.jpg","ce-mip-mp-name":"Cheryl Gallant","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Algonquin—Renfrew—Pembroke","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jean-denis-garon(110189)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GaronJean-Denis_BQ.jpg","ce-mip-mp-name":"Jean-Denis Garon","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Mirabel","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/vince-gasparro(122911)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GasparroVince_Lib.jpg","ce-mip-mp-name":"Vince Gasparro","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Eglinton—Lawrence","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marie-helene-gaudreau(104806)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GaudreauMarie-H%C3%A9l%C3%A8ne_BQ.jpg","ce-mip-mp-name":"Marie-Hélène Gaudreau","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Laurentides—Labelle","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/leah-gazan(87121)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GazanLeah_NDP.jpg","ce-mip-mp-name":"Leah Gazan","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Winnipeg Centre","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bernard-genereux(63908)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GenereuxBernard_CPC.jpg","ce-mip-mp-name":"Bernard Généreux","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Côte-du-Sud-Rivière-du-Loup-Kataskomiq-Témiscouata","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/garnett-genuis(89226)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GenuisGarnett_CPC.jpg","ce-mip-mp-name":"Garnett Genuis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Sherwood Park—Fort Saskatchewan","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mark-gerretsen(88802)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GerretsenMark_Lib.jpg","ce-mip-mp-name":"Mark Gerretsen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Kingston and the Islands","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/amanpreet-s-gill(123418)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillAmanpreet_CPC.jpg","ce-mip-mp-name":"Amanpreet S. Gill","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Skyview","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/amarjeet-gill(122825)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillAmarjeet_CPC.jpg","ce-mip-mp-name":"Amarjeet Gill","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Brampton West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dalwinder-gill(123401)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillDalwinder_CPC.jpg","ce-mip-mp-name":"Dalwinder Gill","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary McKnight","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/harb-gill(123272)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillHarb_CPC.jpg","ce-mip-mp-name":"Harb Gill","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Windsor West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marilene-gill(88538)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillMaril%C3%A8ne_BQ.jpg","ce-mip-mp-name":"Marilène Gill","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Côte-Nord—Kawawachikamach—Nitassinan","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sukhman-gill(123517)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GillSukhman_CPC.jpg","ce-mip-mp-name":"Sukhman Gill","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Abbotsford—South Langley","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marilyn-gladu(88938)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GladuMarilyn_CPC.jpg","ce-mip-mp-name":"Marilyn Gladu","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Sarnia—Lambton—Bkejwanong","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/joel-godin(89407)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GodinJo%C3%ABl_CPC.jpg","ce-mip-mp-name":"Joël Godin","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Portneuf—Jacques-Cartier","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/laila-goodridge(110918)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GoodridgeLaila_CPC.jpg","ce-mip-mp-name":"Laila Goodridge","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Fort McMurray—Cold Lake","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/karina-gould(88715)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GouldKarina_Lib.jpg","ce-mip-mp-name":"Karina Gould","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Burlington","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jacques-gourde(35397)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GourdeJacques_CPC.jpg","ce-mip-mp-name":"Jacques Gourde","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Lévis—Lotbinière","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/wade-grant(123653)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GrantWade_Lib.jpg","ce-mip-mp-name":"Wade Grant","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vancouver Quadra","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/will-greaves(123665)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GreavesWilfrid_Lib.jpg","ce-mip-mp-name":"Will Greaves","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Victoria","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jason-groleau(122507)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GroleauJason_CPC.jpg","ce-mip-mp-name":"Jason Groleau","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Beauce","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/claude-guay(122615)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GuayClaude_Lib.jpg","ce-mip-mp-name":"Claude Guay","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"LaSalle—Émard—Verdun","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-guglielmin(123248)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GuglielminMichael_CPC.jpg","ce-mip-mp-name":"Michael Guglielmin","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Vaughan—Woodbridge","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/steven-guilbeault(14171)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GuilbeaultSteven_Lib.jpg","ce-mip-mp-name":"Steven Guilbeault","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Laurier—Sainte-Marie","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mandy-gull-masty(122492)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Gull-MastyMandy_Lib.jpg","ce-mip-mp-name":"Mandy Gull-Masty","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Abitibi—Baie-James—Nunavik—Eeyou","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/aaron-gunn(123586)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/GunnAaron_CPC.jpg","ce-mip-mp-name":"Aaron Gunn","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"North Island—Powell River","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/patty-hajdu(88984)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/HajduPatty_Lib.jpg","ce-mip-mp-name":"Patty Hajdu","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Thunder Bay—Superior North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jasraj-hallan(105630)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HallanJasrajSingh_CPC.jpg","ce-mip-mp-name":"Jasraj Hallan","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary East","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/brendan-hanley(111109)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HanleyBrendan_Lib.jpg","ce-mip-mp-name":"Brendan Hanley","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Yukon","ce-mip-mp-province":"Yukon","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gabriel-hardy(122678)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HardyGabriel_CPC.jpg","ce-mip-mp-name":"Gabriel Hardy","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Montmorency—Charlevoix","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/emma-harrison(123133)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HarrisonHillEmma_Lib.jpg","ce-mip-mp-name":"Emma Harrison","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Peterborough","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/lisa-hepfner(110446)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HepfnerLisa_lib.jpg","ce-mip-mp-name":"Lisa Hepfner","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Hamilton Mountain","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alana-hirtle(122419)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HirtleAlana_Lib.jpg","ce-mip-mp-name":"Alana Hirtle","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Cumberland—Colchester","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/vincent-neil-ho(123153)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HoVincent_CPC.jpg","ce-mip-mp-name":"Vincent Neil Ho","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Richmond Hill South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/randy-hoback(59148)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HobackRandy_CPC.jpg","ce-mip-mp-name":"Randy Hoback","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Prince Albert","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tim-hodgson(123019)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HodgsonTimothyEdward_Lib.jpg","ce-mip-mp-name":"Tim Hodgson","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Markham—Thornhill","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/corey-hogan(123382)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HoganCorey_Lib.jpg","ce-mip-mp-name":"Corey Hogan","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Calgary Confederation","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kurt-holman(123006)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HolmanKurt_CPC.jpg","ce-mip-mp-name":"Kurt Holman","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"London—Fanshawe","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anthony-housefather(88558)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HousefatherAnthony_Lib.jpg","ce-mip-mp-name":"Anthony Housefather","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mount Royal","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ahmed-hussen(89020)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/HussenAhmed_Lib.jpg","ce-mip-mp-name":"Ahmed Hussen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"York South—Weston—Etobicoke","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/angelo-iacono(71337)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/IaconoAngelo_Lib.jpg","ce-mip-mp-name":"Angelo Iacono","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Alfred-Pellan","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/lori-idlout(111116)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/IdloutLori_NDP.jpg","ce-mip-mp-name":"Lori Idlout","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Nunavut","ce-mip-mp-province":"Nunavut","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/grant-jackson(123287)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JacksonGrant_CPC.jpg","ce-mip-mp-name":"Grant Jackson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Brandon—Souris","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/helena-jaczek(105229)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JaczekHelena_Lib.jpg","ce-mip-mp-name":"Helena Jaczek","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Markham—Stouffville","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tamara-jansen(105774)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JansenTamara_CPC.jpg","ce-mip-mp-name":"Tamara Jansen","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Cloverdale—Langley City","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/matt-jeneroux(89167)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/JenerouxMatt_CPC.jpg","ce-mip-mp-name":"Matt Jeneroux","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Riverbend","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jamil-jivani(118689)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JivaniJamil_CPC.jpg","ce-mip-mp-name":"Jamil Jivani","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Bowmanville—Oshawa North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gord-johns(89263)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JohnsGord_NDP.jpg","ce-mip-mp-name":"Gord Johns","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Courtenay—Alberni","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/melanie-joly(88384)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/JolyM%C3%A9lanie_Lib.jpg","ce-mip-mp-name":"Mélanie Joly","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ahuntsic-Cartierville","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/natilien-joseph(122646)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/JosephNatilien_Lib.jpg","ce-mip-mp-name":"Natilien Joseph","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Longueuil—Saint-Hubert","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/arielle-kayabaga(110502)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KayabagaArielle_Lib.jpg","ce-mip-mp-name":"Arielle Kayabaga","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"London West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mike-kelloway(104531)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KellowayMike_Lib.jpg","ce-mip-mp-name":"Mike Kelloway","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Sydney—Glace Bay","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/pat-kelly(89130)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KellyPat_CPC.jpg","ce-mip-mp-name":"Pat Kelly","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Crowfoot","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/iqra-khalid(88849)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/KhalidIqra_Lib.jpg","ce-mip-mp-name":"Iqra Khalid","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga—Erin Mills","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/arpan-khanna(105052)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KhannaArpan_CPC.jpg","ce-mip-mp-name":"Arpan Khanna","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Oxford","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jeff-kibble(123552)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KibbleJeff_CPC.jpg","ce-mip-mp-name":"Jeff Kibble","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Cowichan—Malahat—Langford","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rhonda-kirkland(123104)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KirklandRhonda_CPC.jpg","ce-mip-mp-name":"Rhonda Kirkland","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Oshawa","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ernie-klassen(123625)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KlassenErnie_Lib.jpg","ce-mip-mp-name":"Ernie Klassen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"South Surrey—White Rock","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tom-kmiec(89136)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KmiecTom_CPC.jpg","ce-mip-mp-name":"Tom Kmiec","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Shepard","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/helena-konanz(105863)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KonanzHelena_CPC.jpg","ce-mip-mp-name":"Helena Konanz","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Similkameen—South Okanagan—West Kootenay","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/annie-koutrakis(105009)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KoutrakisAnnie_Lib.jpg","ce-mip-mp-name":"Annie Koutrakis","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vimy","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-kram(89080)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KramMichael_CPC.jpg","ce-mip-mp-name":"Michael Kram","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Regina—Wascana","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shelby-kramp-neuman(110454)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Kramp-NeumanShelby_CPC.jpg","ce-mip-mp-name":"Shelby Kramp-Neuman","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Hastings—Lennox and Addington—Tyendinaga","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tamara-kronis(111025)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KronisTamara_CPC.jpg","ce-mip-mp-name":"Tamara Kronis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Nanaimo—Ladysmith","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ned-kuruc(110441)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KurucNed_CPC.jpg","ce-mip-mp-name":"Ned Kuruc","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Hamilton East—Stoney Creek","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/stephanie-kusie(96367)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KusieStephanie_CPC.jpg","ce-mip-mp-name":"Stephanie Kusie","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Midnapore","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jenny-kwan(89346)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/KwanJenny_NDP.jpg","ce-mip-mp-name":"Jenny Kwan","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Vancouver East","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mike-lake(35857)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/LakeMike_CPC.jpg","ce-mip-mp-name":"Mike Lake","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Leduc—Wetaskiwin","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marie-france-lalonde(92209)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LalondeMarie-France_Lib.jpg","ce-mip-mp-name":"Marie-France Lalonde","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Orléans","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/emmanuella-lambropoulos(96350)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/LambropoulosEmmanuella_Lib.jpg","ce-mip-mp-name":"Emmanuella Lambropoulos","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Saint-Laurent","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kevin-lamoureux(30552)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LamoureuxKevin_Lib.jpg","ce-mip-mp-name":"Kevin Lamoureux","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Winnipeg North","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/melissa-lantsman(110665)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/LantsmanMelissa_CPC.jpg","ce-mip-mp-name":"Melissa Lantsman","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Thornhill","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/linda-lapointe(88601)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LapointeLinda_Lib.jpg","ce-mip-mp-name":"Linda Lapointe","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Rivière-des-Mille-Îles","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/viviane-lapointe(110663)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LapointeViviane_Lib.jpg","ce-mip-mp-name":"Viviane Lapointe","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Sudbury","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/andreanne-larouche(104973)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LaroucheAndreanne_BQ.jpg","ce-mip-mp-name":"Andréanne Larouche","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Shefford","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/patricia-lattanzio(104957)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LattanzioPatricia_Lib.jpg","ce-mip-mp-name":"Patricia Lattanzio","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Saint-Léonard—Saint-Michel","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/stephane-lauzon(88394)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LauzonSt%C3%A9phane_Lib.jpg","ce-mip-mp-name":"Stéphane Lauzon","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Argenteuil—La Petite-Nation","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ginette-lavack(123305)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LavackGinette_Lib.jpg","ce-mip-mp-name":"Ginette Lavack","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"St. Boniface—St. Vital","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/steeve-lavoie(122518)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LavoieSteeve_Lib.jpg","ce-mip-mp-name":"Steeve Lavoie","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Beauport—Limoilou","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/philip-lawrence(105291)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LawrencePhilip_CPC.jpg","ce-mip-mp-name":"Philip Lawrence","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Northumberland—Clarke","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/andrew-lawton(122913)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LawtonAndrew_CPC.jpg","ce-mip-mp-name":"Andrew Lawton","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Elgin—St. Thomas—London South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dominic-leblanc(1813)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LeBlancDominic_Lib.jpg","ce-mip-mp-name":"Dominic LeBlanc","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Beauséjour","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/eric-lefebvre(58757)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LefebvreEric_CPC.jpg","ce-mip-mp-name":"Eric Lefebvre","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Richmond—Arthabaska","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/carlos-leitao(122656)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LeitaoCarlos_Lib.jpg","ce-mip-mp-name":"Carlos Leitão","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Marc-Aurèle-Fortin","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sebastien-lemire(104630)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LemireSebastien_BQ.jpg","ce-mip-mp-name":"Sébastien Lemire","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Abitibi—Témiscamingue","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/branden-leslie(108395)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LeslieBranden_CPC.jpg","ce-mip-mp-name":"Branden Leslie","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Portage—Lisgar","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chris-lewis(105120)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LewisChris_CPC.jpg","ce-mip-mp-name":"Chris Lewis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Essex","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/leslyn-lewis(88958)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LewisLeslyn_CPC.jpg","ce-mip-mp-name":"Leslyn Lewis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Haldimand—Norfolk","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/joel-lightbound(88532)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LightboundJoel_Lib.jpg","ce-mip-mp-name":"Joël Lightbound","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Louis-Hébert","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dane-lloyd(98079)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LloydDane_CPC.jpg","ce-mip-mp-name":"Dane Lloyd","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Parkland","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ben-lobb(35600)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/LobbBen_CPC.jpg","ce-mip-mp-name":"Ben Lobb","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Huron—Bruce","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/wayne-long(88368)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LongWayne_Lib.jpg","ce-mip-mp-name":"Wayne Long","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Saint John—Kennebecasis","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tim-louis(88810)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/LouisTim_Lib.jpg","ce-mip-mp-name":"Tim Louis","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Kitchener—Conestoga","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michael-ma(105088)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MaMichael_CPC.jpg","ce-mip-mp-name":"Michael Ma","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Markham—Unionville","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/heath-macdonald(109891)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MacDonaldHeath_Lib.jpg","ce-mip-mp-name":"Heath MacDonald","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Malpeque","ce-mip-mp-province":"Prince Edward Island","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kent-macdonald(122394)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MacDonaldKent_Lib.jpg","ce-mip-mp-name":"Kent MacDonald","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Cardigan","ce-mip-mp-province":"Prince Edward Island","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/steven-mackinnon(88468)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MacKinnonSteven_Lib.jpg","ce-mip-mp-name":"Steven MacKinnon","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Gatineau","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jagsharan-singh-mahal(123455)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MahalJagsharanSingh_CPC.jpg","ce-mip-mp-name":"Jagsharan Singh Mahal","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Southeast","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shuvaloy-majumdar(116022)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/MajumdarShuvaloy_CPC.jpg","ce-mip-mp-name":"Shuvaloy Majumdar","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Heritage","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chris-malette(122788)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MaletteChristopherJohn_Lib.jpg","ce-mip-mp-name":"Chris Malette","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Bay of Quinte","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gaetan-malette(122975)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MaletteGaetan_CPC.jpg","ce-mip-mp-name":"Gaétan Malette","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kapuskasing—Timmins—Mushkegowuk","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/james-maloney(88748)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MaloneyJames_Lib.jpg","ce-mip-mp-name":"James Maloney","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Etobicoke—Lakeshore","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jacob-mantle(123282)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MantleJacob_CPC.jpg","ce-mip-mp-name":"Jacob Mantle","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"York—Durham","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/richard-martel(100521)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MartelRichard_CPC.jpg","ce-mip-mp-name":"Richard Martel","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Chicoutimi—Le Fjord","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/elizabeth-may(2897)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MayElizabeth_GP.jpg","ce-mip-mp-name":"Elizabeth May","ce-mip-mp-party":"Green Party","ce-mip-mp-constituency":"Saanich—Gulf Islands","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dan-mazier(3306)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MazierDan_CPC.jpg","ce-mip-mp-name":"Dan Mazier","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Riding Mountain","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kelly-mccauley(89179)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McCauleyKelly_CPC.jpg","ce-mip-mp-name":"Kelly McCauley","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton West","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/david-j-mcguinty(9486)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McGuintyDavidJ_Lib.jpg","ce-mip-mp-name":"David J. McGuinty","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ottawa South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jennifer-mckelvie(122773)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McKelvieJennifer_Lib.jpg","ce-mip-mp-name":"Jennifer McKelvie","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ajax","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/david-mckenzie(123415)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McKenzieDavid_CPC.jpg","ce-mip-mp-name":"David McKenzie","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Signal Hill","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ron-mckinnon(59293)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McKinnonRon_Lib.jpg","ce-mip-mp-name":"Ron McKinnon","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Coquitlam—Port Coquitlam","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jill-mcknight(123556)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McKnightJill_Lib.jpg","ce-mip-mp-name":"Jill McKnight","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Delta","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/greg-mclean(105623)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McLeanGreg_CPC.jpg","ce-mip-mp-name":"Greg McLean","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Centre","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/stephanie-mclean(123563)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McLeanStephanie_Lib.jpg","ce-mip-mp-name":"Stephanie McLean","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Esquimalt—Saanich—Sooke","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/heather-mcpherson(105689)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/McPhersonHeather_NDP.jpg","ce-mip-mp-name":"Heather McPherson","ce-mip-mp-party":"NDP","ce-mip-mp-constituency":"Edmonton Strathcona","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/eric-melillo(105186)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MelilloEric_CPC.jpg","ce-mip-mp-name":"Eric Melillo","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kenora—Kiiwetinoong","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marie-gabrielle-menard(122587)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/M%C3%A9nardMarie-Gabrielle_Lib.jpg","ce-mip-mp-name":"Marie-Gabrielle Ménard","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Hochelaga—Rosemont-Est","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alexandra-mendes(58621)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MendesAlexandra_Lib.jpg","ce-mip-mp-name":"Alexandra Mendès","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brossard—Saint-Lambert","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/costas-menegakis(71762)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MenegakisCostas_CPC.jpg","ce-mip-mp-name":"Costas Menegakis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Aurora—Oak Ridges—Richmond Hill","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marjorie-michel(122684)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MichelMarjorie_Lib.jpg","ce-mip-mp-name":"Marjorie Michel","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Papineau","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shannon-miedema(122428)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MiedemaShannon_Lib.jpg","ce-mip-mp-name":"Shannon Miedema","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Halifax","ce-mip-mp-province":"Nova Scotia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marc-miller(88660)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MillerMarc_Lib.jpg","ce-mip-mp-name":"Marc Miller","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ville-Marie—Le Sud-Ouest—Île-des-Soeurs","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/giovanna-mingarelli(123144)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MingarelliGiovanna_Lib.jpg","ce-mip-mp-name":"Giovanna Mingarelli","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Prescott—Russell—Cumberland","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rob-moore(17210)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/MooreRob_CPC.jpg","ce-mip-mp-name":"Rob Moore","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Fundy Royal","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/billy-morin(123447)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MorinWilliam_CPC.jpg","ce-mip-mp-name":"Billy Morin","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Northwest","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rob-morrison(105807)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MorrisonRob_CPC.jpg","ce-mip-mp-name":"Rob Morrison","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Columbia—Kootenay—Southern Rockies","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/robert-j-morrissey(88308)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MorrisseyRobertJ_Lib.jpg","ce-mip-mp-name":"Robert J. Morrissey","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Egmont","ce-mip-mp-province":"Prince Edward Island","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/glen-motz(94305)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MotzGlen_CPC.jpg","ce-mip-mp-name":"Glen Motz","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Medicine Hat—Cardston—Warner","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dan-muys(110415)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MuysDan_CPC.jpg","ce-mip-mp-name":"Dan Muys","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Flamborough—Glanbrook—Brant North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/david-myles(122462)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/MylesDavid_Lib.jpg","ce-mip-mp-name":"David Myles","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Fredericton—Oromocto","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/yasir-naqvi(110572)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NaqviYasir_Lib.jpg","ce-mip-mp-name":"Yasir Naqvi","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ottawa Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-nater(88917)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NaterJohn_CPC.jpg","ce-mip-mp-name":"John Nater","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Perth—Wellington","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/juanita-nathan(123141)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NathanJuanita_Lib.jpg","ce-mip-mp-name":"Juanita Nathan","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Pickering—Brooklin","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chi-nguyen(123192)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NguyenChi_Lib.jpg","ce-mip-mp-name":"Chi Nguyen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Spadina—Harbourfront","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/taleeb-noormohamed(72023)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/NoormohamedTaleeb_Lib.jpg","ce-mip-mp-name":"Taleeb Noormohamed","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vancouver Granville","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/christine-normandin(104947)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NormandinChristine_BQ.jpg","ce-mip-mp-name":"Christine Normandin","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Saint-Jean","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bienvenu-olivier-ntumba(122668)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/NtumbaBienvenu-Olivier_Lib.jpg","ce-mip-mp-name":"Bienvenu-Olivier Ntumba","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mont-Saint-Bruno—L'Acadie","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dominique-orourke(122933)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ORourkeDominique_Lib.jpg","ce-mip-mp-name":"Dominique O'Rourke","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Guelph","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/robert-oliphant(58858)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/OliphantRobert_Lib.jpg","ce-mip-mp-name":"Robert Oliphant","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Don Valley West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/eleanor-olszewski(89171)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/OlszewskiEleanor_Lib.jpg","ce-mip-mp-name":"Eleanor Olszewski","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Edmonton Centre","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tom-osborne(122375)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/OsborneTom_Lib.jpg","ce-mip-mp-name":"Tom Osborne","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Cape Spear","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jeremy-patzer(105559)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/PatzerJeremy_CPC.jpg","ce-mip-mp-name":"Jeremy Patzer","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Swift Current—Grasslands—Kindersley","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/pierre-paul-hus(71454)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Paul_HusPierre_CPC.jpg","ce-mip-mp-name":"Pierre Paul-Hus","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Charlesbourg—Haute-Saint-Charles","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/yves-perron(88418)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/PerronYves_BQ.jpg","ce-mip-mp-name":"Yves Perron","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Berthier—Maskinongé","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ginette-petitpas-taylor(88364)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/PetitpasTaylorGinette_Lib.jpg","ce-mip-mp-name":"Ginette Petitpas Taylor","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Moncton—Dieppe","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/louis-plamondon(413)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/PlamondonLouis_BQ.jpg","ce-mip-mp-name":"Louis Plamondon","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Bécancour—Nicolet—Saurel—Alnôbak","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/marcus-powlowski(105437)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/PowlowskiMarcus_Lib.jpg","ce-mip-mp-name":"Marcus Powlowski","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Thunder Bay—Rainy River","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/nathalie-provost(122552)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ProvostNathalie_Lib.jpg","ce-mip-mp-name":"Nathalie Provost","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Châteauguay—Les Jardins-de-Napierville","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jacques-ramsay(122606)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RamsayJacques_Lib.jpg","ce-mip-mp-name":"Jacques Ramsay","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"La Prairie—Atateken","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/aslam-rana(122946)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RanaAslam_Lib.jpg","ce-mip-mp-name":"Aslam Rana","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Hamilton Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/brad-redekopp(105598)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RedekoppBrad_CPC.jpg","ce-mip-mp-name":"Brad Redekopp","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Saskatoon West","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/scott-reid(1827)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/ReidScott_CPC.jpg","ce-mip-mp-name":"Scott Reid","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Lanark—Frontenac","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/michelle-rempel-garner(71902)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/RempelMichelle_CPC.jpg","ce-mip-mp-name":"Michelle Rempel Garner","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Calgary Nose Hill","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/colin-reynolds(119991)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ReynoldsColin_CPC.jpg","ce-mip-mp-name":"Colin Reynolds","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Elmwood—Transcona","ce-mip-mp-province":"Manitoba","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/blake-richards(59235)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RichardsBlake_CPC.jpg","ce-mip-mp-name":"Blake Richards","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Airdrie—Cochrane","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anna-roberts(105191)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RobertsAnna_CPC.jpg","ce-mip-mp-name":"Anna Roberts","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"King—Vaughan","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gregor-robertson(123644)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RobertsonGregor_Lib.jpg","ce-mip-mp-name":"Gregor Robertson","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vancouver Fraserview—South Burnaby","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/pauline-rochefort(123081)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RochefortPauline_Lib.jpg","ce-mip-mp-name":"Pauline Rochefort","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Nipissing—Timiskaming","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sherry-romanado(88521)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RomanadoSherry_Lib.jpg","ce-mip-mp-name":"Sherry Romanado","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Longueuil—Charles-LeMoyne","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/lianne-rood(105210)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RoodLianne_CPC.jpg","ce-mip-mp-name":"Lianne Rood","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Middlesex—London","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ellis-ross(123622)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RossEllis_CPC.jpg","ce-mip-mp-name":"Ellis Ross","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Skeena—Bulkley Valley","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jonathan-rowe(122389)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RoweJonathan_CPC.jpg","ce-mip-mp-name":"Jonathan Rowe","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Terra Nova—The Peninsulas","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/zoe-royer(59294)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/RoyerZoe_Lib.jpg","ce-mip-mp-name":"Zoe Royer","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Port Moody—Coquitlam","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/alex-ruff(105070)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/RuffAlex_CPC.jpg","ce-mip-mp-name":"Alex Ruff","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Bruce—Grey—Owen Sound","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ruby-sahota(88698)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SahotaRuby_Lib.jpg","ce-mip-mp-name":"Ruby Sahota","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brampton North—Caledon","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gurbux-saini(1422)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SainiGurbux_Lib.jpg","ce-mip-mp-name":"Gurbux Saini","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Fleetwood—Port Kells","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/randeep-sarai(89339)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/SaraiRandeep_Lib.jpg","ce-mip-mp-name":"Randeep Sarai","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Surrey Centre","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/abdelhaq-sari(122533)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SariAbdelhaq_Lib.jpg","ce-mip-mp-name":"Abdelhaq Sari","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Bourassa","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/simon-pierre-savard-tremblay(104944)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Savard-TremblaySimon-Pierre_BQ.jpg","ce-mip-mp-name":"Simon-Pierre Savard-Tremblay","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Saint-Hyacinthe—Bagot—Acton","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jake-sawatzky(123583)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SawatzkyJake_Lib.jpg","ce-mip-mp-name":"Jake Sawatzky","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"New Westminster—Burnaby—Maillardville","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/francis-scarpaleggia(25453)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ScarpaleggiaFrancis_Lib.jpg","ce-mip-mp-name":"Francis Scarpaleggia","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Lac-Saint-Louis","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/andrew-scheer(25454)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/ScheerAndrew_CPC.jpg","ce-mip-mp-name":"Andrew Scheer","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Regina—Qu'Appelle","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/peter-schiefke(88649)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SchiefkePeter_Lib.jpg","ce-mip-mp-name":"Peter Schiefke","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Vaudreuil","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jamie-schmale(88770)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SchmaleJamie_CPC.jpg","ce-mip-mp-name":"Jamie Schmale","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Haliburton—Kawartha Lakes","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kyle-seeback(58841)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SeebackKyle_CPC.jpg","ce-mip-mp-name":"Kyle Seeback","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Dufferin—Caledon","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/judy-a-sgro(1787)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SgroJudy_Lib.jpg","ce-mip-mp-name":"Judy A. Sgro","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Humber River—Black Creek","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/terry-sheehan(88944)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SheehanTerry_Lib.jpg","ce-mip-mp-name":"Terry Sheehan","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Sault Ste. Marie—Algoma","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/doug-shipley(105031)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ShipleyDoug_CPC.jpg","ce-mip-mp-name":"Doug Shipley","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Barrie—Springwater—Oro-Medonte","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/maninder-sidhu(105045)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SidhuManinder_Lib.jpg","ce-mip-mp-name":"Maninder Sidhu","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brampton East","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sonia-sidhu(88703)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SidhuSonia_Lib.jpg","ce-mip-mp-name":"Sonia Sidhu","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brampton South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mario-simard(104773)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SimardMario_BQ.jpg","ce-mip-mp-name":"Mario Simard","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Jonquière","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/clifford-small(109867)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SmallClifford_CPC.jpg","ce-mip-mp-name":"Clifford Small","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Central Newfoundland","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/amandeep-sodhi(122801)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SodhiAmandeep_Lib.jpg","ce-mip-mp-name":"Amandeep Sodhi","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brampton Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/evan-solomon(123229)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SolomonEvan_Lib.jpg","ce-mip-mp-name":"Evan Solomon","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Toronto Centre","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/charles-sousa(114349)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SousaCharles_Lib.jpg","ce-mip-mp-name":"Charles Sousa","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga—Lakeshore","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/eric-st-pierre(122589)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/St-PierreEric_Lib.jpg","ce-mip-mp-name":"Eric St-Pierre","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Honoré-Mercier","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/gabriel-ste-marie(88485)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/SteMarieGabriel_BQ.jpg","ce-mip-mp-name":"Gabriel Ste-Marie","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Joliette—Manawan","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/warren-steinley(105581)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SteinleyWarren_CPC.jpg","ce-mip-mp-name":"Warren Steinley","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Regina—Lewvan","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/william-stevenson(123513)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/StevensonWilliam_CPC.jpg","ce-mip-mp-name":"William Stevenson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Yellowhead","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/mark-strahl(71986)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/StrahlMark_CPC.jpg","ce-mip-mp-name":"Mark Strahl","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Chilliwack—Hope","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/matt-strauss(122994)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/StraussMatt_CPC.jpg","ce-mip-mp-name":"Matt Strauss","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Kitchener South—Hespeler","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/shannon-stubbs(89198)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/StubbsShannon_CPC.jpg","ce-mip-mp-name":"Shannon Stubbs","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Lakeland","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jenna-sudds(110459)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/SuddsJenna_Lib.jpg","ce-mip-mp-name":"Jenna Sudds","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Kanata","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kristina-tesser-derksen(123027)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/TesserDerksenKristina_Lib.jpg","ce-mip-mp-name":"Kristina Tesser Derksen","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Milton East—Halton Hills South","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/luc-theriault(88552)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/Th%C3%A9riaultLuc_BQ.jpg","ce-mip-mp-name":"Luc Thériault","ce-mip-mp-party":"Bloc Québécois","ce-mip-mp-constituency":"Montcalm","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rachael-thomas(89200)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ThomasRachael_CPC.jpg","ce-mip-mp-name":"Rachael Thomas","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Lethbridge","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/joanne-thompson(109877)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ThompsonJoanne_lib.jpg","ce-mip-mp-name":"Joanne Thompson","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"St. John's East","ce-mip-mp-province":"Newfoundland and Labrador","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/corey-tochor(84882)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/TochorCorey_CPC.jpg","ce-mip-mp-name":"Corey Tochor","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Saskatoon—University","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/fraser-tolmie(110800)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/TolmieFraser_CPC.jpg","ce-mip-mp-name":"Fraser Tolmie","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Moose Jaw—Lake Centre—Lanigan","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/ryan-turnbull(105480)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/TurnbullRyan_Lib.jpg","ce-mip-mp-name":"Ryan Turnbull","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Whitby","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tim-uppal(30645)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/UppalTim_CPC.jpg","ce-mip-mp-name":"Tim Uppal","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Edmonton Gateway","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/rechie-valdez(110538)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ValdezRechie_Lib.jpg","ce-mip-mp-name":"Rechie Valdez","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Mississauga—Streetsville","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/adam-van-koeverden(105242)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/vanKoeverdenAdam_Lib.jpg","ce-mip-mp-name":"Adam van Koeverden","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Burlington North—Milton West","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tako-van-popta(105811)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/VanPoptaTako_CPC.jpg","ce-mip-mp-name":"Tako Van Popta","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Langley Township—Fraser Heights","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/anita-vandenbeld(71738)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/VandenbeldAnita_Lib.jpg","ce-mip-mp-name":"Anita Vandenbeld","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Ottawa West—Nepean","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/dominique-vien(110009)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/VienDominique_CPC.jpg","ce-mip-mp-name":"Dominique Vien","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Bellechasse—Les Etchemins—Lévis","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/arnold-viersen(89211)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ViersenArnold_CPC.jpg","ce-mip-mp-name":"Arnold Viersen","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Peace River—Westlock","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/louis-villeneuve(122539)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/VilleneuveLouis_Lib.jpg","ce-mip-mp-name":"Louis Villeneuve","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Brome—Missisquoi","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/brad-vis(89289)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/VisBrad_CPC.jpg","ce-mip-mp-name":"Brad Vis","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Mission—Matsqui—Abbotsford","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/cathay-wagantall(89098)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WagantallCathay_CPC.jpg","ce-mip-mp-name":"Cathay Wagantall","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Yorkton—Melville","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/chris-warkentin(35886)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WarkentinChris_CPC.jpg","ce-mip-mp-name":"Chris Warkentin","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Grande Prairie","ce-mip-mp-province":"Alberta","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/tim-watchorn(122637)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WatchornTim_Lib.jpg","ce-mip-mp-name":"Tim Watchorn","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Les Pays-d'en-Haut","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/kevin-waugh(89084)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WaughKevin_CPC.jpg","ce-mip-mp-name":"Kevin Waugh","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Saskatoon South","ce-mip-mp-province":"Saskatchewan","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/patrick-weiler(105918)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WeilerPatrick_Lib.jpg","ce-mip-mp-name":"Patrick Weiler","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"West Vancouver—Sunshine Coast—Sea to Sky Country","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jonathan-wilkinson(89300)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/WilkinsonJonathan_Lib.jpg","ce-mip-mp-name":"Jonathan Wilkinson","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"North Vancouver—Capilano","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-williamson(71323)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/WilliamsonJohn_CPC.jpg","ce-mip-mp-name":"John Williamson","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Saint John—St. Croix","ce-mip-mp-province":"New Brunswick","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/jean-yip(98747)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/YipJean_Lib.jpg","ce-mip-mp-name":"Jean Yip","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough—Agincourt","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/salma-zahid(88950)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ZahidSalma_Lib.jpg","ce-mip-mp-name":"Salma Zahid","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Scarborough Centre—Don Valley East","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/john-zerucelli(122925)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/45/ZerucelliJohn_Lib.jpg","ce-mip-mp-name":"John Zerucelli","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Etobicoke North","ce-mip-mp-province":"Ontario","ce-mip-mp-honourable":"The Honourable"},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/bob-zimmer(72035)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/ZimmerBob_CPC.jpg","ce-mip-mp-name":"Bob Zimmer","ce-mip-mp-party":"Conservative","ce-mip-mp-constituency":"Prince George—Peace River—Northern Rockies","ce-mip-mp-province":"British Columbia","ce-mip-mp-honourable":""},{"ce-mip-mp-tile href":"https://www.ourcommons.ca/members/en/sameer-zuberi(54157)","ce-mip-mp-picture src":"https://www.ourcommons.ca/Content/Parliamentarians/Images/OfficialMPPhotos/44/ZuberiSameer_Lib.jpg","ce-mip-mp-name":"Sameer Zuberi","ce-mip-mp-party":"Liberal","ce-mip-mp-constituency":"Pierrefonds—Dollard","ce-mip-mp-province":"Quebec","ce-mip-mp-honourable":""}]

    return jsonify({
        "total_count": len(senators),
        "senators": senators
    }) 
    


# Hardcoded JSON data
committees_data = {
  "main_committees": [
  {
    "href": "/en/committees/agfo/45-1",
      "acronym": "AGFO",
      "name_full": "Agriculture and Forestry",
      "name_short": "Agriculture",
    "members": [
      {
        "name": "Robert Black",
        "href": "/en/senators/black-robert/",
        "image": "https://sencanada.ca/media/4xlb0fam/sen_pho_black_official_2024.jpg?center=0.38914995975052752,0.46871057422593848&mode=crop&width=95&height=100&rnd=133953399113030000&quality=90",
        "alt": "Black, Robert",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "John M. McNair",
        "href": "/en/senators/mcnair-john-m/",
        "image": "https://sencanada.ca/media/yr4kwcj1/sen_pho_mcnair_official_2024.jpg?center=0.37930393685352287,0.47083675544428272&mode=crop&width=95&height=100&rnd=133953399108970000&quality=90",
        "alt": "McNair, John M.",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Robert Black",
        "href": "/en/senators/black-robert/",
        "image": "https://sencanada.ca/media/4xlb0fam/sen_pho_black_official_2024.jpg?center=0.38914995975052752,0.46871057422593848&mode=crop&width=95&height=100&rnd=133953399113030000&quality=90",
        "alt": "Black, Robert",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "John M. McNair",
        "href": "/en/senators/mcnair-john-m/",
        "image": "https://sencanada.ca/media/yr4kwcj1/sen_pho_mcnair_official_2024.jpg?center=0.37930393685352287,0.47083675544428272&mode=crop&width=95&height=100&rnd=133953399108970000&quality=90",
        "alt": "McNair, John M.",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Margo  Greenwood",
        "href": "/en/senators/greenwood-margo/",
        "image": "https://sencanada.ca/media/fj2nn02k/sen_pho_greenwood_official_2024.jpg?center=0.38726637304449174,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399103800000&quality=95",
        "alt": "Greenwood, Margo",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Yonah Martin",
        "href": "/en/senators/martin-yonah/",
        "image": "https://sencanada.ca/media/tn2oodro/sen_pho_martin_official_2024.jpg?center=0.40516608862971354,0.53653188335415136&mode=crop&width=95&height=100&rnd=133953399108030000&quality=95",
        "alt": "Martin, Yonah",
        "affiliation": "C - (British Columbia)"
      },
      {
        "name": "Marnie McBean",
        "href": "/en/senators/mcbean-marnie/",
        "image": "https://sencanada.ca/media/rrkd133i/sen_pho_mcbean_official_2024.jpg?center=0.40384161235629751,0.49645859136157555&mode=crop&width=95&height=100&rnd=133953399108500000&quality=95",
        "alt": "McBean, Marnie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Julie Miville-Dech\u00eane",
        "href": "/en/senators/miville-dechene-julie/",
        "image": "https://sencanada.ca/media/wlhl22jx/sen_pho_miville-dechene_official_2024.jpg?center=0.36237063010296866,0.51225218914900916&mode=crop&width=95&height=100&rnd=133953399109430000&quality=95",
        "alt": "Miville-Dech\u00eane, Julie",
        "affiliation": "ISG - (Quebec - Inkerman)"
      },
      {
        "name": "Tracy Muggli",
        "href": "/en/senators/muggli-tracy/",
        "image": "https://sencanada.ca/media/eu0fd4uf/sen_pho_muggli_official_2024.jpg?center=0.40958608232385585,0.55773867716261583&mode=crop&width=95&height=100&rnd=133953399110700000&quality=95",
        "alt": "Muggli, Tracy",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "David Richards",
        "href": "/en/senators/richards-david/",
        "image": "https://sencanada.ca/media/dy4jis1j/sen_pho_richards_official_2024.jpg?center=0.33076430212690744,0.57160772958755057&mode=crop&width=95&height=100&rnd=133953399112730000&quality=95",
        "alt": "Richards, David",
        "affiliation": "C - (New Brunswick)"
      },
      {
        "name": "Mary Robinson",
        "href": "/en/senators/robinson-mary/",
        "image": "https://sencanada.ca/media/j5pl14zl/sen_pho_robinson_official.jpg?center=0.39190610754728655,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399113330000&quality=95",
        "alt": "Robinson, Mary",
        "affiliation": "CSG - (Prince Edward Island)"
      },
      {
        "name": "Karen Sorensen",
        "href": "/en/senators/sorensen-karen/",
        "image": "https://sencanada.ca/media/dfdob5tv/sen_pho_sorensen_official_2024.jpg?center=0.40369275739833277,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399114900000&quality=95",
        "alt": "Sorensen, Karen",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Margo  Greenwood",
        "href": "/en/senators/greenwood-margo/",
        "image": "https://sencanada.ca/media/fj2nn02k/sen_pho_greenwood_official_2024.jpg?center=0.38726637304449174,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399103800000&quality=95",
        "alt": "Greenwood, Margo",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Yonah Martin",
        "href": "/en/senators/martin-yonah/",
        "image": "https://sencanada.ca/media/tn2oodro/sen_pho_martin_official_2024.jpg?center=0.40516608862971354,0.53653188335415136&mode=crop&width=95&height=100&rnd=133953399108030000&quality=95",
        "alt": "Martin, Yonah",
        "affiliation": "C - (British Columbia)"
      },
      {
        "name": "Marnie McBean",
        "href": "/en/senators/mcbean-marnie/",
        "image": "https://sencanada.ca/media/rrkd133i/sen_pho_mcbean_official_2024.jpg?center=0.40384161235629751,0.49645859136157555&mode=crop&width=95&height=100&rnd=133953399108500000&quality=95",
        "alt": "McBean, Marnie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Julie Miville-Dech\u00eane",
        "href": "/en/senators/miville-dechene-julie/",
        "image": "https://sencanada.ca/media/wlhl22jx/sen_pho_miville-dechene_official_2024.jpg?center=0.36237063010296866,0.51225218914900916&mode=crop&width=95&height=100&rnd=133953399109430000&quality=95",
        "alt": "Miville-Dech\u00eane, Julie",
        "affiliation": "ISG - (Quebec - Inkerman)"
      },
      {
        "name": "Tracy Muggli",
        "href": "/en/senators/muggli-tracy/",
        "image": "https://sencanada.ca/media/eu0fd4uf/sen_pho_muggli_official_2024.jpg?center=0.40958608232385585,0.55773867716261583&mode=crop&width=95&height=100&rnd=133953399110700000&quality=95",
        "alt": "Muggli, Tracy",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "David Richards",
        "href": "/en/senators/richards-david/",
        "image": "https://sencanada.ca/media/dy4jis1j/sen_pho_richards_official_2024.jpg?center=0.33076430212690744,0.57160772958755057&mode=crop&width=95&height=100&rnd=133953399112730000&quality=95",
        "alt": "Richards, David",
        "affiliation": "C - (New Brunswick)"
      },
      {
        "name": "Mary Robinson",
        "href": "/en/senators/robinson-mary/",
        "image": "https://sencanada.ca/media/j5pl14zl/sen_pho_robinson_official.jpg?center=0.39190610754728655,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399113330000&quality=95",
        "alt": "Robinson, Mary",
        "affiliation": "CSG - (Prince Edward Island)"
      },
      {
        "name": "Karen Sorensen",
        "href": "/en/senators/sorensen-karen/",
        "image": "https://sencanada.ca/media/dfdob5tv/sen_pho_sorensen_official_2024.jpg?center=0.40369275739833277,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399114900000&quality=95",
        "alt": "Sorensen, Karen",
        "affiliation": "ISG - (Alberta)"
      }
    ]
  },
  {
    "href": "/en/committees/aovs/45-1",
      "acronym": "AOVS",
      "name_full": "Audit and Oversight",
      "name_short": "Audit and Oversight",
    "members": [
      {
        "name": "Marty Klyne",
        "href": "/en/senators/klyne-marty/",
        "image": "https://sencanada.ca/media/1nshiaty/sen_pho_klyne_official_2024.jpg?center=0.37740307830951847,0.4695629636123782&mode=crop&width=95&height=100&rnd=133953399106170000&quality=90",
        "alt": "Klyne, Marty",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Colin Deacon",
        "href": "/en/senators/deacon-colin/",
        "image": "https://sencanada.ca/media/xllg2j35/sen_pho_deacon-colin_official_2024.jpg?center=0.40979304311793552,0.48633155505483944&mode=crop&width=95&height=100&rnd=133953399100530000&quality=90",
        "alt": "Deacon, Colin",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Tony Loffreda",
        "href": "/en/senators/loffreda-tony/",
        "image": "https://sencanada.ca/media/pcqnmbxq/sen_pho_loffreda_official_2024.jpg?center=0.43315938202594828,0.46654946378621853&mode=crop&width=95&height=100&rnd=133953399106930000&quality=90",
        "alt": "Loffreda, Tony",
        "affiliation": "ISG - (Quebec - Shawinegan)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=90",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Marty Klyne",
        "href": "/en/senators/klyne-marty/",
        "image": "https://sencanada.ca/media/1nshiaty/sen_pho_klyne_official_2024.jpg?center=0.37740307830951847,0.4695629636123782&mode=crop&width=95&height=100&rnd=133953399106170000&quality=90",
        "alt": "Klyne, Marty",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Colin Deacon",
        "href": "/en/senators/deacon-colin/",
        "image": "https://sencanada.ca/media/xllg2j35/sen_pho_deacon-colin_official_2024.jpg?center=0.40979304311793552,0.48633155505483944&mode=crop&width=95&height=100&rnd=133953399100530000&quality=90",
        "alt": "Deacon, Colin",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Tony Loffreda",
        "href": "/en/senators/loffreda-tony/",
        "image": "https://sencanada.ca/media/pcqnmbxq/sen_pho_loffreda_official_2024.jpg?center=0.43315938202594828,0.46654946378621853&mode=crop&width=95&height=100&rnd=133953399106930000&quality=90",
        "alt": "Loffreda, Tony",
        "affiliation": "ISG - (Quebec - Shawinegan)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=90",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      }
    ]
  },
  {
    "href": "/en/committees/appa/45-1",
      "acronym": "APPA",
      "name_full": "Indigenous Peoples",
      "name_short": "Indigenous Peoples",
    "members": [
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=90",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Margo  Greenwood",
        "href": "/en/senators/greenwood-margo/",
        "image": "https://sencanada.ca/media/fj2nn02k/sen_pho_greenwood_official_2024.jpg?center=0.38726637304449174,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399103800000&quality=90",
        "alt": "Greenwood, Margo",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=90",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Margo  Greenwood",
        "href": "/en/senators/greenwood-margo/",
        "image": "https://sencanada.ca/media/fj2nn02k/sen_pho_greenwood_official_2024.jpg?center=0.38726637304449174,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399103800000&quality=90",
        "alt": "Greenwood, Margo",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Gwen Boniface",
        "href": "/en/senators/boniface-gwen/",
        "image": "https://sencanada.ca/media/z0rcvach/com_pho_boniface_official_2024.jpg?center=0.36591503578522,0.52424751380354229&mode=crop&width=95&height=100&rnd=133953399097100000&quality=95",
        "alt": "Boniface, Gwen",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Nancy Karetak-Lindell",
        "href": "/en/senators/karetak-lindell-nancy/",
        "image": "https://sencanada.ca/media/q0uj1sd0/sen_pho_karetak-lindell_official.jpg?center=0.31156351383605357,0.49693482303990905&mode=crop&width=95&height=100&rnd=133953399105700000&quality=95",
        "alt": "Karetak-Lindell, Nancy",
        "affiliation": "ISG - (Nunavut)"
      },
      {
        "name": "Patti LaBoucane-Benson",
        "href": "/en/senators/laboucane-benson-patti/",
        "image": "https://sencanada.ca/media/lrflewsq/sen_pho_laboucane-benson_official_2024.jpg?center=0.39724693326104188,0.46593645490269259&mode=crop&width=95&height=100&rnd=133953399106470000&quality=95",
        "alt": "LaBoucane-Benson, Patti",
        "affiliation": "Non-affiliated - (Alberta)"
      },
      {
        "name": "Mary Jane McCallum",
        "href": "/en/senators/mccallum-mary-jane/",
        "image": "https://sencanada.ca/media/jksppaqb/sen_pho_mccallum_official_2024.jpg?center=0.39780758971394831,0.54391393130228693&mode=crop&width=95&height=100&rnd=133953399108670000&quality=95",
        "alt": "McCallum, Mary Jane",
        "affiliation": "C - (Manitoba)"
      },
      {
        "name": "Marilou McPhedran",
        "href": "/en/senators/mcphedran-marilou/",
        "image": "https://sencanada.ca/media/xuqgx0ay/sen_pho_mcphedran_official_2024.jpg?center=0.36099698599314906,0.51481070170850862&mode=crop&width=95&height=100&rnd=133953399109130000&quality=95",
        "alt": "McPhedran, Marilou",
        "affiliation": "Non-affiliated - (Manitoba)"
      },
      {
        "name": "Kim Pate",
        "href": "/en/senators/pate-kim/",
        "image": "https://sencanada.ca/media/njtnhamx/sen_pho_pate_official_2024.jpg?center=0.41090368770412528,0.47629208737933193&mode=crop&width=95&height=100&rnd=133953399111000000&quality=95",
        "alt": "Pate, Kim",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Paul (PJ) Prosper",
        "href": "/en/senators/prosper-paul/",
        "image": "https://sencanada.ca/media/tkbo3y4t/sen_pho_prosper_official_2024.jpg?center=0.40074609493557123,0.48351489883299009&mode=crop&width=95&height=100&rnd=133953399111930000&quality=95",
        "alt": "Prosper, Paul (PJ)",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Karen Sorensen",
        "href": "/en/senators/sorensen-karen/",
        "image": "https://sencanada.ca/media/dfdob5tv/sen_pho_sorensen_official_2024.jpg?center=0.40369275739833277,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399114900000&quality=95",
        "alt": "Sorensen, Karen",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "Judy A. White",
        "href": "/en/senators/white-judy/",
        "image": "https://sencanada.ca/media/tqlbjf04/sen_pho_white_official_2024.jpg?center=0.38724453840732909,0.46955336482074367&mode=crop&width=95&height=100&rnd=133953399116300000&quality=95",
        "alt": "White, Judy A.",
        "affiliation": "PSG - (Newfoundland and Labrador)"
      },
      {
        "name": "Gwen Boniface",
        "href": "/en/senators/boniface-gwen/",
        "image": "https://sencanada.ca/media/z0rcvach/com_pho_boniface_official_2024.jpg?center=0.36591503578522,0.52424751380354229&mode=crop&width=95&height=100&rnd=133953399097100000&quality=95",
        "alt": "Boniface, Gwen",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Nancy Karetak-Lindell",
        "href": "/en/senators/karetak-lindell-nancy/",
        "image": "https://sencanada.ca/media/q0uj1sd0/sen_pho_karetak-lindell_official.jpg?center=0.31156351383605357,0.49693482303990905&mode=crop&width=95&height=100&rnd=133953399105700000&quality=95",
        "alt": "Karetak-Lindell, Nancy",
        "affiliation": "ISG - (Nunavut)"
      },
      {
        "name": "Patti LaBoucane-Benson",
        "href": "/en/senators/laboucane-benson-patti/",
        "image": "https://sencanada.ca/media/lrflewsq/sen_pho_laboucane-benson_official_2024.jpg?center=0.39724693326104188,0.46593645490269259&mode=crop&width=95&height=100&rnd=133953399106470000&quality=95",
        "alt": "LaBoucane-Benson, Patti",
        "affiliation": "Non-affiliated - (Alberta)"
      },
      {
        "name": "Mary Jane McCallum",
        "href": "/en/senators/mccallum-mary-jane/",
        "image": "https://sencanada.ca/media/jksppaqb/sen_pho_mccallum_official_2024.jpg?center=0.39780758971394831,0.54391393130228693&mode=crop&width=95&height=100&rnd=133953399108670000&quality=95",
        "alt": "McCallum, Mary Jane",
        "affiliation": "C - (Manitoba)"
      },
      {
        "name": "Marilou McPhedran",
        "href": "/en/senators/mcphedran-marilou/",
        "image": "https://sencanada.ca/media/xuqgx0ay/sen_pho_mcphedran_official_2024.jpg?center=0.36099698599314906,0.51481070170850862&mode=crop&width=95&height=100&rnd=133953399109130000&quality=95",
        "alt": "McPhedran, Marilou",
        "affiliation": "Non-affiliated - (Manitoba)"
      },
      {
        "name": "Kim Pate",
        "href": "/en/senators/pate-kim/",
        "image": "https://sencanada.ca/media/njtnhamx/sen_pho_pate_official_2024.jpg?center=0.41090368770412528,0.47629208737933193&mode=crop&width=95&height=100&rnd=133953399111000000&quality=95",
        "alt": "Pate, Kim",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Paul (PJ) Prosper",
        "href": "/en/senators/prosper-paul/",
        "image": "https://sencanada.ca/media/tkbo3y4t/sen_pho_prosper_official_2024.jpg?center=0.40074609493557123,0.48351489883299009&mode=crop&width=95&height=100&rnd=133953399111930000&quality=95",
        "alt": "Prosper, Paul (PJ)",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Karen Sorensen",
        "href": "/en/senators/sorensen-karen/",
        "image": "https://sencanada.ca/media/dfdob5tv/sen_pho_sorensen_official_2024.jpg?center=0.40369275739833277,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399114900000&quality=95",
        "alt": "Sorensen, Karen",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "Judy A. White",
        "href": "/en/senators/white-judy/",
        "image": "https://sencanada.ca/media/tqlbjf04/sen_pho_white_official_2024.jpg?center=0.38724453840732909,0.46955336482074367&mode=crop&width=95&height=100&rnd=133953399116300000&quality=95",
        "alt": "White, Judy A.",
        "affiliation": "PSG - (Newfoundland and Labrador)"
      }
    ]
  },
  {
    "href": "/en/committees/banc/45-1",
      "acronym": "BANC",
      "name_full": "Banking, Commerce and the Economy",
      "name_short": "Banking",
    "members": [
      {
        "name": "Cl\u00e9ment Gignac",
        "href": "/en/senators/gignac-clement/",
        "image": "https://sencanada.ca/media/z2ec4my2/sen_pho_gignac_official_2024.jpg?center=0.37034505076479468,0.46586777249836225&mode=crop&width=95&height=100&rnd=133953399103330000&quality=90",
        "alt": "Gignac, Cl\u00e9ment",
        "affiliation": "CSG - (Quebec - Kennebec)"
      },
      {
        "name": "Toni Varone",
        "href": "/en/senators/varone-toni/",
        "image": "https://sencanada.ca/media/cq2ggfgb/sen_pho_varone_official_2024.jpg?center=0.41105941355523662,0.572583432828541&mode=crop&width=95&height=100&rnd=133953399115530000&quality=90",
        "alt": "Varone, Toni",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Cl\u00e9ment Gignac",
        "href": "/en/senators/gignac-clement/",
        "image": "https://sencanada.ca/media/z2ec4my2/sen_pho_gignac_official_2024.jpg?center=0.37034505076479468,0.46586777249836225&mode=crop&width=95&height=100&rnd=133953399103330000&quality=90",
        "alt": "Gignac, Cl\u00e9ment",
        "affiliation": "CSG - (Quebec - Kennebec)"
      },
      {
        "name": "Toni Varone",
        "href": "/en/senators/varone-toni/",
        "image": "https://sencanada.ca/media/cq2ggfgb/sen_pho_varone_official_2024.jpg?center=0.41105941355523662,0.572583432828541&mode=crop&width=95&height=100&rnd=133953399115530000&quality=90",
        "alt": "Varone, Toni",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Daryl S. Fridhandler",
        "href": "/en/senators/fridhandler-daryl/",
        "image": "https://sencanada.ca/media/1dvpeivc/sen_pho_fridhandler_official_2024.jpg?center=0.3992727637041904,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399102230000&quality=95",
        "alt": "Fridhandler, Daryl S.",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=95",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Tony Loffreda",
        "href": "/en/senators/loffreda-tony/",
        "image": "https://sencanada.ca/media/pcqnmbxq/sen_pho_loffreda_official_2024.jpg?center=0.43315938202594828,0.46654946378621853&mode=crop&width=95&height=100&rnd=133953399106930000&quality=95",
        "alt": "Loffreda, Tony",
        "affiliation": "ISG - (Quebec - Shawinegan)"
      },
      {
        "name": "Elizabeth Marshall",
        "href": "/en/senators/marshall-elizabeth/",
        "image": "https://sencanada.ca/media/p2lbqiqx/sen_pho_marshall_official_2024.jpg?center=0.30801344134169434,0.47226417343585692&mode=crop&width=95&height=100&rnd=133953399107870000&quality=95",
        "alt": "Marshall, Elizabeth",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Yonah Martin",
        "href": "/en/senators/martin-yonah/",
        "image": "https://sencanada.ca/media/tn2oodro/sen_pho_martin_official_2024.jpg?center=0.40516608862971354,0.53653188335415136&mode=crop&width=95&height=100&rnd=133953399108030000&quality=95",
        "alt": "Martin, Yonah",
        "affiliation": "C - (British Columbia)"
      },
      {
        "name": "Paul J. Massicotte",
        "href": "/en/senators/massicotte-paul-j/",
        "image": "https://sencanada.ca/media/cvoldnej/sen_pho_massicotte_official_2024.jpg?center=0.38891563444744964,0.52710971090324721&mode=crop&width=95&height=100&rnd=133953399108200000&quality=95",
        "alt": "Massicotte, Paul J.",
        "affiliation": "ISG - (Quebec - De Lanaudi\u00e8re)"
      },
      {
        "name": "Marnie McBean",
        "href": "/en/senators/mcbean-marnie/",
        "image": "https://sencanada.ca/media/rrkd133i/sen_pho_mcbean_official_2024.jpg?center=0.40384161235629751,0.49645859136157555&mode=crop&width=95&height=100&rnd=133953399108500000&quality=95",
        "alt": "McBean, Marnie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Sandra Pupatello",
        "href": "/en/senators/pupatello-sandra/",
        "image": "https://sencanada.ca/media/233fr2g1/sen_pho_pupatello_official_2025.jpg?center=0.44347270064561373,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399112100000&quality=95",
        "alt": "Pupatello, Sandra",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Pierrette Ringuette",
        "href": "/en/senators/ringuette-pierrette/",
        "image": "https://sencanada.ca/media/ikultfz5/sen_pho_ringuette_official.jpg?center=0.43168605079456751,0.47927354007129719&mode=crop&width=95&height=100&rnd=133953399112870000&quality=95",
        "alt": "Ringuette, Pierrette",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Pamela Wallin",
        "href": "/en/senators/wallin-pamela/",
        "image": "https://sencanada.ca/media/h5ebetkz/sen_pho_wallin_official_2024.jpg?center=0.40958608232385585,0.52804916583076555&mode=crop&width=95&height=100&rnd=133953399115830000&quality=95",
        "alt": "Wallin, Pamela",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=95",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Daryl S. Fridhandler",
        "href": "/en/senators/fridhandler-daryl/",
        "image": "https://sencanada.ca/media/1dvpeivc/sen_pho_fridhandler_official_2024.jpg?center=0.3992727637041904,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399102230000&quality=95",
        "alt": "Fridhandler, Daryl S.",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=95",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Tony Loffreda",
        "href": "/en/senators/loffreda-tony/",
        "image": "https://sencanada.ca/media/pcqnmbxq/sen_pho_loffreda_official_2024.jpg?center=0.43315938202594828,0.46654946378621853&mode=crop&width=95&height=100&rnd=133953399106930000&quality=95",
        "alt": "Loffreda, Tony",
        "affiliation": "ISG - (Quebec - Shawinegan)"
      },
      {
        "name": "Elizabeth Marshall",
        "href": "/en/senators/marshall-elizabeth/",
        "image": "https://sencanada.ca/media/p2lbqiqx/sen_pho_marshall_official_2024.jpg?center=0.30801344134169434,0.47226417343585692&mode=crop&width=95&height=100&rnd=133953399107870000&quality=95",
        "alt": "Marshall, Elizabeth",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Yonah Martin",
        "href": "/en/senators/martin-yonah/",
        "image": "https://sencanada.ca/media/tn2oodro/sen_pho_martin_official_2024.jpg?center=0.40516608862971354,0.53653188335415136&mode=crop&width=95&height=100&rnd=133953399108030000&quality=95",
        "alt": "Martin, Yonah",
        "affiliation": "C - (British Columbia)"
      },
      {
        "name": "Paul J. Massicotte",
        "href": "/en/senators/massicotte-paul-j/",
        "image": "https://sencanada.ca/media/cvoldnej/sen_pho_massicotte_official_2024.jpg?center=0.38891563444744964,0.52710971090324721&mode=crop&width=95&height=100&rnd=133953399108200000&quality=95",
        "alt": "Massicotte, Paul J.",
        "affiliation": "ISG - (Quebec - De Lanaudi\u00e8re)"
      },
      {
        "name": "Marnie McBean",
        "href": "/en/senators/mcbean-marnie/",
        "image": "https://sencanada.ca/media/rrkd133i/sen_pho_mcbean_official_2024.jpg?center=0.40384161235629751,0.49645859136157555&mode=crop&width=95&height=100&rnd=133953399108500000&quality=95",
        "alt": "McBean, Marnie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Sandra Pupatello",
        "href": "/en/senators/pupatello-sandra/",
        "image": "https://sencanada.ca/media/233fr2g1/sen_pho_pupatello_official_2025.jpg?center=0.44347270064561373,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399112100000&quality=95",
        "alt": "Pupatello, Sandra",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Pierrette Ringuette",
        "href": "/en/senators/ringuette-pierrette/",
        "image": "https://sencanada.ca/media/ikultfz5/sen_pho_ringuette_official.jpg?center=0.43168605079456751,0.47927354007129719&mode=crop&width=95&height=100&rnd=133953399112870000&quality=95",
        "alt": "Ringuette, Pierrette",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Pamela Wallin",
        "href": "/en/senators/wallin-pamela/",
        "image": "https://sencanada.ca/media/h5ebetkz/sen_pho_wallin_official_2024.jpg?center=0.40958608232385585,0.52804916583076555&mode=crop&width=95&height=100&rnd=133953399115830000&quality=95",
        "alt": "Wallin, Pamela",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=95",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      }
    ]
  },
  {
    "href": "/en/committees/ciba/45-1",
      "acronym": "CIBA",
      "name_full": "Internal Economy, Budgets and Administration",
      "name_short": "Internal Economy",
    "members": [
      {
        "name": "Lucie Moncion",
        "href": "/en/senators/moncion-lucie/",
        "image": "https://sencanada.ca/media/m1hge4bp/sen_pho_mocion_official_2024.jpg?center=0.36662689106284063,0.41218847511068274&mode=crop&width=95&height=100&rnd=133953399109900000&quality=90",
        "alt": "Moncion, Lucie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=90",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=90",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Jim Quinn",
        "href": "/en/senators/quinn-jim/",
        "image": "https://sencanada.ca/media/2fck44iv/sen_pho_quinn_official_2024.jpg?center=0.3761829540974953,0.45737545742969926&mode=crop&width=95&height=100&rnd=133953399112270000&quality=90",
        "alt": "Quinn, Jim",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Lucie Moncion",
        "href": "/en/senators/moncion-lucie/",
        "image": "https://sencanada.ca/media/m1hge4bp/sen_pho_mocion_official_2024.jpg?center=0.36662689106284063,0.41218847511068274&mode=crop&width=95&height=100&rnd=133953399109900000&quality=90",
        "alt": "Moncion, Lucie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=90",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=90",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Jim Quinn",
        "href": "/en/senators/quinn-jim/",
        "image": "https://sencanada.ca/media/2fck44iv/sen_pho_quinn_official_2024.jpg?center=0.3761829540974953,0.45737545742969926&mode=crop&width=95&height=100&rnd=133953399112270000&quality=90",
        "alt": "Quinn, Jim",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=95",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Peter M. Boehm",
        "href": "/en/senators/boehm-peter/",
        "image": "https://sencanada.ca/media/ztdetwhw/sen_pho_boehm_official.jpg?center=0.41105941355523662,0.487756257594683&mode=crop&width=95&height=100&rnd=133953399096770000&quality=95",
        "alt": "Boehm, Peter M.",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Yvonne Boyer",
        "href": "/en/senators/boyer-yvonne/",
        "image": "https://sencanada.ca/media/eafhrjpy/com_pho_boyer_official_2024.jpg?center=0.39715459235398276,0.48499623197857689&mode=crop&width=95&height=100&rnd=133953399097570000&quality=95",
        "alt": "Boyer, Yvonne",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "\u00c9ric Forest",
        "href": "/en/senators/forest-eric/",
        "image": "https://sencanada.ca/media/v5gn1nkr/sen_pho_forest_official_2024.jpg?center=0.41122008882942684,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399101770000&quality=95",
        "alt": "Forest, \u00c9ric",
        "affiliation": "ISG - (Quebec - Gulf)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Jane MacAdam",
        "href": "/en/senators/macadam-beverly-jane/",
        "image": "https://sencanada.ca/media/35kiitf5/sen_pho_macadam_official_2024.jpg?center=0.402219426166952,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953402323930000&quality=95",
        "alt": "MacAdam, Jane",
        "affiliation": "ISG - (Prince Edward Island)"
      },
      {
        "name": "Rosemary Moodie",
        "href": "/en/senators/moodie-rosemary/",
        "image": "https://sencanada.ca/media/zjwmzdwg/sen_pho_moodie_official.jpg?center=0.38421052631578945,0.50378729518398735&mode=crop&width=95&height=100&rnd=133953399110070000&quality=95",
        "alt": "Moodie, Rosemary",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Manuelle Oudar",
        "href": "/en/senators/oudar-manuelle/",
        "image": "https://sencanada.ca/media/cdwddbnc/sen_pho_oudar_official_2024.jpg?center=0.40958608232385585,0.48987693697552948&mode=crop&width=95&height=100&rnd=133953401729870000&quality=95",
        "alt": "Oudar, Manuelle",
        "affiliation": "ISG - (Quebec - La Salle)"
      },
      {
        "name": "Larry W. Smith",
        "href": "/en/senators/smith-larry-w/",
        "image": "https://sencanada.ca/media/r03d0lss/sen_pho_smith_official_2024.jpg?center=0.39388567876792746,0.46187746446204314&mode=crop&width=95&height=100&rnd=133953399114770000&quality=95",
        "alt": "Smith, Larry W.",
        "affiliation": "C - (Quebec - Saurel)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=95",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Peter M. Boehm",
        "href": "/en/senators/boehm-peter/",
        "image": "https://sencanada.ca/media/ztdetwhw/sen_pho_boehm_official.jpg?center=0.41105941355523662,0.487756257594683&mode=crop&width=95&height=100&rnd=133953399096770000&quality=95",
        "alt": "Boehm, Peter M.",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Yvonne Boyer",
        "href": "/en/senators/boyer-yvonne/",
        "image": "https://sencanada.ca/media/eafhrjpy/com_pho_boyer_official_2024.jpg?center=0.39715459235398276,0.48499623197857689&mode=crop&width=95&height=100&rnd=133953399097570000&quality=95",
        "alt": "Boyer, Yvonne",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "\u00c9ric Forest",
        "href": "/en/senators/forest-eric/",
        "image": "https://sencanada.ca/media/v5gn1nkr/sen_pho_forest_official_2024.jpg?center=0.41122008882942684,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399101770000&quality=95",
        "alt": "Forest, \u00c9ric",
        "affiliation": "ISG - (Quebec - Gulf)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Jane MacAdam",
        "href": "/en/senators/macadam-beverly-jane/",
        "image": "https://sencanada.ca/media/35kiitf5/sen_pho_macadam_official_2024.jpg?center=0.402219426166952,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953402323930000&quality=95",
        "alt": "MacAdam, Jane",
        "affiliation": "ISG - (Prince Edward Island)"
      },
      {
        "name": "Rosemary Moodie",
        "href": "/en/senators/moodie-rosemary/",
        "image": "https://sencanada.ca/media/zjwmzdwg/sen_pho_moodie_official.jpg?center=0.38421052631578945,0.50378729518398735&mode=crop&width=95&height=100&rnd=133953399110070000&quality=95",
        "alt": "Moodie, Rosemary",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Manuelle Oudar",
        "href": "/en/senators/oudar-manuelle/",
        "image": "https://sencanada.ca/media/cdwddbnc/sen_pho_oudar_official_2024.jpg?center=0.40958608232385585,0.48987693697552948&mode=crop&width=95&height=100&rnd=133953401729870000&quality=95",
        "alt": "Oudar, Manuelle",
        "affiliation": "ISG - (Quebec - La Salle)"
      },
      {
        "name": "Larry W. Smith",
        "href": "/en/senators/smith-larry-w/",
        "image": "https://sencanada.ca/media/r03d0lss/sen_pho_smith_official_2024.jpg?center=0.39388567876792746,0.46187746446204314&mode=crop&width=95&height=100&rnd=133953399114770000&quality=95",
        "alt": "Smith, Larry W.",
        "affiliation": "C - (Quebec - Saurel)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      }
    ]
  },
  {
    "href": "/en/committees/conf/45-1",
      "acronym": "CONF",
      "name_full": "Ethics and Conflict of Interest for Senators",
      "name_short": "Conflict of Interest",
    "members": [
      {
        "name": "Judith G. Seidman",
        "href": "/en/senators/seidman-judith/",
        "image": "https://sencanada.ca/media/01ooqr2f/sen_pho_seidman_official_2024.jpg?center=0.36987499712240152,0.5906093641273733&mode=crop&width=95&height=100&rnd=133953399113800000&quality=90",
        "alt": "Seidman, Judith G.",
        "affiliation": "C - (Quebec - De la Durantaye)"
      },
      {
        "name": "Peter Harder",
        "href": "/en/senators/harder-peter-pc/",
        "image": "https://sencanada.ca/media/pm0pxoe5/sen_pho_harder_official_2024.jpg?center=0.37782682889564034,0.52098427481702214&mode=crop&width=95&height=100&rnd=133953399103970000&quality=90",
        "alt": "Harder, Peter, P.C.",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Judith G. Seidman",
        "href": "/en/senators/seidman-judith/",
        "image": "https://sencanada.ca/media/01ooqr2f/sen_pho_seidman_official_2024.jpg?center=0.36987499712240152,0.5906093641273733&mode=crop&width=95&height=100&rnd=133953399113800000&quality=90",
        "alt": "Seidman, Judith G.",
        "affiliation": "C - (Quebec - De la Durantaye)"
      },
      {
        "name": "Peter Harder",
        "href": "/en/senators/harder-peter-pc/",
        "image": "https://sencanada.ca/media/pm0pxoe5/sen_pho_harder_official_2024.jpg?center=0.37782682889564034,0.52098427481702214&mode=crop&width=95&height=100&rnd=133953399103970000&quality=90",
        "alt": "Harder, Peter, P.C.",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Gwen Boniface",
        "href": "/en/senators/boniface-gwen/",
        "image": "https://sencanada.ca/media/z0rcvach/com_pho_boniface_official_2024.jpg?center=0.36591503578522,0.52424751380354229&mode=crop&width=95&height=100&rnd=133953399097100000&quality=95",
        "alt": "Boniface, Gwen",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=95",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=95",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Gwen Boniface",
        "href": "/en/senators/boniface-gwen/",
        "image": "https://sencanada.ca/media/z0rcvach/com_pho_boniface_official_2024.jpg?center=0.36591503578522,0.52424751380354229&mode=crop&width=95&height=100&rnd=133953399097100000&quality=95",
        "alt": "Boniface, Gwen",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=95",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=95",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      }
    ]
  },
  {
    "href": "/en/committees/enev/45-1",
      "acronym": "ENEV",
      "name_full": "Energy, the Environment and Natural Resources",
      "name_short": "Energy",
    "members": [
      {
        "name": "Pat Duncan",
        "href": "/en/senators/duncan-pat/",
        "image": "https://sencanada.ca/media/tsjitw0d/sen_pho_duncan_official_2024.jpg?center=0.38530447160966591,0.53569246433694684&mode=crop&width=95&height=100&rnd=133953399101470000&quality=90",
        "alt": "Duncan, Pat",
        "affiliation": "ISG - (Yukon)"
      },
      {
        "name": "Jos\u00e9e Verner",
        "href": "/en/senators/verner-josee/",
        "image": "https://sencanada.ca/media/psahkdbx/sen_pho_verner_official_2024.jpg?center=0.36789520937406478,0.59335962092846017&mode=crop&width=95&height=100&rnd=133953399115700000&quality=90",
        "alt": "Verner, Jos\u00e9e, P.C.",
        "affiliation": "CSG - (Quebec - Montarville)"
      },
      {
        "name": "Pat Duncan",
        "href": "/en/senators/duncan-pat/",
        "image": "https://sencanada.ca/media/tsjitw0d/sen_pho_duncan_official_2024.jpg?center=0.38530447160966591,0.53569246433694684&mode=crop&width=95&height=100&rnd=133953399101470000&quality=90",
        "alt": "Duncan, Pat",
        "affiliation": "ISG - (Yukon)"
      },
      {
        "name": "Jos\u00e9e Verner",
        "href": "/en/senators/verner-josee/",
        "image": "https://sencanada.ca/media/psahkdbx/sen_pho_verner_official_2024.jpg?center=0.36789520937406478,0.59335962092846017&mode=crop&width=95&height=100&rnd=133953399115700000&quality=90",
        "alt": "Verner, Jos\u00e9e, P.C.",
        "affiliation": "CSG - (Quebec - Montarville)"
      },
      {
        "name": "Dawn Anderson",
        "href": "/en/senators/anderson-margaret/",
        "image": "https://sencanada.ca/media/nmemnah0/sen_pho_anderson_official_2024.jpg?center=0.404085788062057,0.46996252564457858&mode=crop&width=95&height=100&rnd=133953399095370000&quality=95",
        "alt": "Anderson, Dawn",
        "affiliation": "PSG - (Northwest Territories)"
      },
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=95",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "R\u00e9jean  Aucoin",
        "href": "/en/senators/aucoin-albert-rejean/",
        "image": "https://sencanada.ca/media/uu5fjgw0/sen_pho_aucoin_official.jpg?center=0.46557266911632539,0.50048033387976165&mode=crop&width=95&height=100&rnd=133953399096170000&quality=95",
        "alt": "Aucoin, R\u00e9jean",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Daryl S. Fridhandler",
        "href": "/en/senators/fridhandler-daryl/",
        "image": "https://sencanada.ca/media/1dvpeivc/sen_pho_fridhandler_official_2024.jpg?center=0.3992727637041904,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399102230000&quality=95",
        "alt": "Fridhandler, Daryl S.",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Rosa Galvez",
        "href": "/en/senators/galvez-rosa/",
        "image": "https://sencanada.ca/media/10kfuetn/sen_pho_galvez_official_2024.jpg?center=0.35840119583668006,0.49183309928481023&mode=crop&width=95&height=100&rnd=133953399103030000&quality=95",
        "alt": "Galvez, Rosa",
        "affiliation": "ISG - (Quebec - Bedford)"
      },
      {
        "name": "Joan Kingston",
        "href": "/en/senators/kingston-joan/",
        "image": "https://sencanada.ca/media/hefjkn1p/sen_pho_kingston_official_2024.jpg?center=0.3864635570240465,0.508763682384399&mode=crop&width=95&height=100&rnd=133953399106000000&quality=95",
        "alt": "Kingston, Joan",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Stan Kutcher",
        "href": "/en/senators/kutcher-stan/",
        "image": "https://sencanada.ca/media/r1vfsa0k/sen_pho_kutcher_official_2024.jpg?center=0.39133008856782647,0.54348626232738417&mode=crop&width=95&height=100&rnd=133953399106300000&quality=95",
        "alt": "Kutcher, Stan",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Todd Lewis",
        "href": "/en/senators/lewis-todd/",
        "image": "https://sencanada.ca/media/maonrkw1/sen_pho_lewis_official.jpg?center=0.40019123507802212,0.48178051078408923&mode=crop&width=95&height=100&rnd=133953399106800000&quality=95",
        "alt": "Lewis, Todd",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Mary Jane McCallum",
        "href": "/en/senators/mccallum-mary-jane/",
        "image": "https://sencanada.ca/media/jksppaqb/sen_pho_mccallum_official_2024.jpg?center=0.39780758971394831,0.54391393130228693&mode=crop&width=95&height=100&rnd=133953399108670000&quality=95",
        "alt": "McCallum, Mary Jane",
        "affiliation": "C - (Manitoba)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=95",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Suze Youance",
        "href": "/en/senators/youance-suze/",
        "image": "https://sencanada.ca/media/f2sf5v4b/sen_pho_youance_official_2024.jpg?center=0.40786198654862738,0.524802288565667&mode=crop&width=95&height=100&rnd=133953399116930000&quality=95",
        "alt": "Youance, Suze",
        "affiliation": "ISG - (Quebec - Lauzon)"
      },
      {
        "name": "Dawn Anderson",
        "href": "/en/senators/anderson-margaret/",
        "image": "https://sencanada.ca/media/nmemnah0/sen_pho_anderson_official_2024.jpg?center=0.404085788062057,0.46996252564457858&mode=crop&width=95&height=100&rnd=133953399095370000&quality=95",
        "alt": "Anderson, Dawn",
        "affiliation": "PSG - (Northwest Territories)"
      },
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=95",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "R\u00e9jean  Aucoin",
        "href": "/en/senators/aucoin-albert-rejean/",
        "image": "https://sencanada.ca/media/uu5fjgw0/sen_pho_aucoin_official.jpg?center=0.46557266911632539,0.50048033387976165&mode=crop&width=95&height=100&rnd=133953399096170000&quality=95",
        "alt": "Aucoin, R\u00e9jean",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Daryl S. Fridhandler",
        "href": "/en/senators/fridhandler-daryl/",
        "image": "https://sencanada.ca/media/1dvpeivc/sen_pho_fridhandler_official_2024.jpg?center=0.3992727637041904,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399102230000&quality=95",
        "alt": "Fridhandler, Daryl S.",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Rosa Galvez",
        "href": "/en/senators/galvez-rosa/",
        "image": "https://sencanada.ca/media/10kfuetn/sen_pho_galvez_official_2024.jpg?center=0.35840119583668006,0.49183309928481023&mode=crop&width=95&height=100&rnd=133953399103030000&quality=95",
        "alt": "Galvez, Rosa",
        "affiliation": "ISG - (Quebec - Bedford)"
      },
      {
        "name": "Joan Kingston",
        "href": "/en/senators/kingston-joan/",
        "image": "https://sencanada.ca/media/hefjkn1p/sen_pho_kingston_official_2024.jpg?center=0.3864635570240465,0.508763682384399&mode=crop&width=95&height=100&rnd=133953399106000000&quality=95",
        "alt": "Kingston, Joan",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Stan Kutcher",
        "href": "/en/senators/kutcher-stan/",
        "image": "https://sencanada.ca/media/r1vfsa0k/sen_pho_kutcher_official_2024.jpg?center=0.39133008856782647,0.54348626232738417&mode=crop&width=95&height=100&rnd=133953399106300000&quality=95",
        "alt": "Kutcher, Stan",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Todd Lewis",
        "href": "/en/senators/lewis-todd/",
        "image": "https://sencanada.ca/media/maonrkw1/sen_pho_lewis_official.jpg?center=0.40019123507802212,0.48178051078408923&mode=crop&width=95&height=100&rnd=133953399106800000&quality=95",
        "alt": "Lewis, Todd",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Mary Jane McCallum",
        "href": "/en/senators/mccallum-mary-jane/",
        "image": "https://sencanada.ca/media/jksppaqb/sen_pho_mccallum_official_2024.jpg?center=0.39780758971394831,0.54391393130228693&mode=crop&width=95&height=100&rnd=133953399108670000&quality=95",
        "alt": "McCallum, Mary Jane",
        "affiliation": "C - (Manitoba)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=95",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Suze Youance",
        "href": "/en/senators/youance-suze/",
        "image": "https://sencanada.ca/media/f2sf5v4b/sen_pho_youance_official_2024.jpg?center=0.40786198654862738,0.524802288565667&mode=crop&width=95&height=100&rnd=133953399116930000&quality=95",
        "alt": "Youance, Suze",
        "affiliation": "ISG - (Quebec - Lauzon)"
      }
    ]
  },
  {
    "href": "/en/committees/lcjc/45-1",
      "acronym": "LCJC",
      "name_full": "Legal and Constitutional Affairs",
      "name_short": "Legal",
    "members": [
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=90",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=90",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=90",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=90",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Baltej S. Dhillon",
        "href": "/en/senators/dhillon-baltej-s/",
        "image": "https://sencanada.ca/media/tbxdmqni/sen_pho_dhillon_official.jpg?center=0.38841822242592289,0.51988463292931186&mode=crop&width=95&height=100&rnd=133953399101170000&quality=95",
        "alt": "Dhillon, Baltej S.",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Leo Housakos",
        "href": "/en/senators/housakos-leo/",
        "image": "https://sencanada.ca/media/xbyp00a4/sen_pho_housakos_official_2024.jpg?center=0.402046481854913,0.56198899496986543&mode=crop&width=95&height=100&rnd=133953399105070000&quality=95",
        "alt": "Housakos, Leo",
        "affiliation": "C - (Quebec - Wellington)"
      },
      {
        "name": "Pierre Moreau",
        "href": "/en/senators/moreau-pierre/",
        "image": "https://sencanada.ca/media/2gzb1mkb/sen_pho_moreau_official.jpg?center=0.38228341294233087,0.51181271432115993&mode=crop&width=95&height=100&rnd=133953399110370000&quality=95",
        "alt": "Moreau, Pierre",
        "affiliation": "PSG - (Quebec - The Laurentides)"
      },
      {
        "name": "Manuelle Oudar",
        "href": "/en/senators/oudar-manuelle/",
        "image": "https://sencanada.ca/media/cdwddbnc/sen_pho_oudar_official_2024.jpg?center=0.40958608232385585,0.48987693697552948&mode=crop&width=95&height=100&rnd=133953401729870000&quality=95",
        "alt": "Oudar, Manuelle",
        "affiliation": "ISG - (Quebec - La Salle)"
      },
      {
        "name": "Kim Pate",
        "href": "/en/senators/pate-kim/",
        "image": "https://sencanada.ca/media/njtnhamx/sen_pho_pate_official_2024.jpg?center=0.41090368770412528,0.47629208737933193&mode=crop&width=95&height=100&rnd=133953399111000000&quality=95",
        "alt": "Pate, Kim",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Paul (PJ) Prosper",
        "href": "/en/senators/prosper-paul/",
        "image": "https://sencanada.ca/media/tkbo3y4t/sen_pho_prosper_official_2024.jpg?center=0.40074609493557123,0.48351489883299009&mode=crop&width=95&height=100&rnd=133953399111930000&quality=95",
        "alt": "Prosper, Paul (PJ)",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Paula Simons",
        "href": "/en/senators/simons-paula/",
        "image": "https://sencanada.ca/media/tffoquhj/sen_pho_simons_official_2024.jpg?center=0.41637698842054377,0.55565128069187186&mode=crop&width=95&height=100&rnd=133953399114600000&quality=95",
        "alt": "Simons, Paula",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Baltej S. Dhillon",
        "href": "/en/senators/dhillon-baltej-s/",
        "image": "https://sencanada.ca/media/tbxdmqni/sen_pho_dhillon_official.jpg?center=0.38841822242592289,0.51988463292931186&mode=crop&width=95&height=100&rnd=133953399101170000&quality=95",
        "alt": "Dhillon, Baltej S.",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Leo Housakos",
        "href": "/en/senators/housakos-leo/",
        "image": "https://sencanada.ca/media/xbyp00a4/sen_pho_housakos_official_2024.jpg?center=0.402046481854913,0.56198899496986543&mode=crop&width=95&height=100&rnd=133953399105070000&quality=95",
        "alt": "Housakos, Leo",
        "affiliation": "C - (Quebec - Wellington)"
      },
      {
        "name": "Pierre Moreau",
        "href": "/en/senators/moreau-pierre/",
        "image": "https://sencanada.ca/media/2gzb1mkb/sen_pho_moreau_official.jpg?center=0.38228341294233087,0.51181271432115993&mode=crop&width=95&height=100&rnd=133953399110370000&quality=95",
        "alt": "Moreau, Pierre",
        "affiliation": "PSG - (Quebec - The Laurentides)"
      },
      {
        "name": "Manuelle Oudar",
        "href": "/en/senators/oudar-manuelle/",
        "image": "https://sencanada.ca/media/cdwddbnc/sen_pho_oudar_official_2024.jpg?center=0.40958608232385585,0.48987693697552948&mode=crop&width=95&height=100&rnd=133953401729870000&quality=95",
        "alt": "Oudar, Manuelle",
        "affiliation": "ISG - (Quebec - La Salle)"
      },
      {
        "name": "Kim Pate",
        "href": "/en/senators/pate-kim/",
        "image": "https://sencanada.ca/media/njtnhamx/sen_pho_pate_official_2024.jpg?center=0.41090368770412528,0.47629208737933193&mode=crop&width=95&height=100&rnd=133953399111000000&quality=95",
        "alt": "Pate, Kim",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Paul (PJ) Prosper",
        "href": "/en/senators/prosper-paul/",
        "image": "https://sencanada.ca/media/tkbo3y4t/sen_pho_prosper_official_2024.jpg?center=0.40074609493557123,0.48351489883299009&mode=crop&width=95&height=100&rnd=133953399111930000&quality=95",
        "alt": "Prosper, Paul (PJ)",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Paula Simons",
        "href": "/en/senators/simons-paula/",
        "image": "https://sencanada.ca/media/tffoquhj/sen_pho_simons_official_2024.jpg?center=0.41637698842054377,0.55565128069187186&mode=crop&width=95&height=100&rnd=133953399114600000&quality=95",
        "alt": "Simons, Paula",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      }
    ]
  },
  {
    "href": "/en/committees/nffn/45-1",
      "acronym": "NFFN",
      "name_full": "National Finance",
      "name_short": "National Finance",
    "members": [
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=90",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "\u00c9ric Forest",
        "href": "/en/senators/forest-eric/",
        "image": "https://sencanada.ca/media/v5gn1nkr/sen_pho_forest_official_2024.jpg?center=0.41122008882942684,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399101770000&quality=90",
        "alt": "Forest, \u00c9ric",
        "affiliation": "ISG - (Quebec - Gulf)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=90",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "\u00c9ric Forest",
        "href": "/en/senators/forest-eric/",
        "image": "https://sencanada.ca/media/v5gn1nkr/sen_pho_forest_official_2024.jpg?center=0.41122008882942684,0.47767566526371863&mode=crop&width=95&height=100&rnd=133953399101770000&quality=90",
        "alt": "Forest, \u00c9ric",
        "affiliation": "ISG - (Quebec - Gulf)"
      },
      {
        "name": "Andrew Cardozo",
        "href": "/en/senators/cardozo-andrew/",
        "image": "https://sencanada.ca/media/fr4m4b54/sen_pho_cardozo_official_2024.jpg?center=0.41707283352201385,0.51905090048902747&mode=crop&width=95&height=100&rnd=133953399098330000&quality=95",
        "alt": "Cardozo, Andrew",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Rosa Galvez",
        "href": "/en/senators/galvez-rosa/",
        "image": "https://sencanada.ca/media/10kfuetn/sen_pho_galvez_official_2024.jpg?center=0.35840119583668006,0.49183309928481023&mode=crop&width=95&height=100&rnd=133953399103030000&quality=95",
        "alt": "Galvez, Rosa",
        "affiliation": "ISG - (Quebec - Bedford)"
      },
      {
        "name": "Cl\u00e9ment Gignac",
        "href": "/en/senators/gignac-clement/",
        "image": "https://sencanada.ca/media/z2ec4my2/sen_pho_gignac_official_2024.jpg?center=0.37034505076479468,0.46586777249836225&mode=crop&width=95&height=100&rnd=133953399103330000&quality=95",
        "alt": "Gignac, Cl\u00e9ment",
        "affiliation": "CSG - (Quebec - Kennebec)"
      },
      {
        "name": "Martine H\u00e9bert",
        "href": "/en/senators/hebert-martine/",
        "image": "https://sencanada.ca/media/l2jdnh33/sen_pho_hebert_official.png?center=0.44199936941423296,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953402111470000&quality=95",
        "alt": "H\u00e9bert, Martine",
        "affiliation": "ISG - (Quebec - Victoria)"
      },
      {
        "name": "Joan Kingston",
        "href": "/en/senators/kingston-joan/",
        "image": "https://sencanada.ca/media/hefjkn1p/sen_pho_kingston_official_2024.jpg?center=0.3864635570240465,0.508763682384399&mode=crop&width=95&height=100&rnd=133953399106000000&quality=95",
        "alt": "Kingston, Joan",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Jane MacAdam",
        "href": "/en/senators/macadam-beverly-jane/",
        "image": "https://sencanada.ca/media/35kiitf5/sen_pho_macadam_official_2024.jpg?center=0.402219426166952,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953402323930000&quality=95",
        "alt": "MacAdam, Jane",
        "affiliation": "ISG - (Prince Edward Island)"
      },
      {
        "name": "Elizabeth Marshall",
        "href": "/en/senators/marshall-elizabeth/",
        "image": "https://sencanada.ca/media/p2lbqiqx/sen_pho_marshall_official_2024.jpg?center=0.30801344134169434,0.47226417343585692&mode=crop&width=95&height=100&rnd=133953399107870000&quality=95",
        "alt": "Marshall, Elizabeth",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Pierre Moreau",
        "href": "/en/senators/moreau-pierre/",
        "image": "https://sencanada.ca/media/2gzb1mkb/sen_pho_moreau_official.jpg?center=0.38228341294233087,0.51181271432115993&mode=crop&width=95&height=100&rnd=133953399110370000&quality=95",
        "alt": "Moreau, Pierre",
        "affiliation": "PSG - (Quebec - The Laurentides)"
      },
      {
        "name": "Sandra Pupatello",
        "href": "/en/senators/pupatello-sandra/",
        "image": "https://sencanada.ca/media/233fr2g1/sen_pho_pupatello_official_2025.jpg?center=0.44347270064561373,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399112100000&quality=95",
        "alt": "Pupatello, Sandra",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Toni Varone",
        "href": "/en/senators/varone-toni/",
        "image": "https://sencanada.ca/media/cq2ggfgb/sen_pho_varone_official_2024.jpg?center=0.41105941355523662,0.572583432828541&mode=crop&width=95&height=100&rnd=133953399115530000&quality=95",
        "alt": "Varone, Toni",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Andrew Cardozo",
        "href": "/en/senators/cardozo-andrew/",
        "image": "https://sencanada.ca/media/fr4m4b54/sen_pho_cardozo_official_2024.jpg?center=0.41707283352201385,0.51905090048902747&mode=crop&width=95&height=100&rnd=133953399098330000&quality=95",
        "alt": "Cardozo, Andrew",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Rosa Galvez",
        "href": "/en/senators/galvez-rosa/",
        "image": "https://sencanada.ca/media/10kfuetn/sen_pho_galvez_official_2024.jpg?center=0.35840119583668006,0.49183309928481023&mode=crop&width=95&height=100&rnd=133953399103030000&quality=95",
        "alt": "Galvez, Rosa",
        "affiliation": "ISG - (Quebec - Bedford)"
      },
      {
        "name": "Cl\u00e9ment Gignac",
        "href": "/en/senators/gignac-clement/",
        "image": "https://sencanada.ca/media/z2ec4my2/sen_pho_gignac_official_2024.jpg?center=0.37034505076479468,0.46586777249836225&mode=crop&width=95&height=100&rnd=133953399103330000&quality=95",
        "alt": "Gignac, Cl\u00e9ment",
        "affiliation": "CSG - (Quebec - Kennebec)"
      },
      {
        "name": "Martine H\u00e9bert",
        "href": "/en/senators/hebert-martine/",
        "image": "https://sencanada.ca/media/l2jdnh33/sen_pho_hebert_official.png?center=0.44199936941423296,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953402111470000&quality=95",
        "alt": "H\u00e9bert, Martine",
        "affiliation": "ISG - (Quebec - Victoria)"
      },
      {
        "name": "Joan Kingston",
        "href": "/en/senators/kingston-joan/",
        "image": "https://sencanada.ca/media/hefjkn1p/sen_pho_kingston_official_2024.jpg?center=0.3864635570240465,0.508763682384399&mode=crop&width=95&height=100&rnd=133953399106000000&quality=95",
        "alt": "Kingston, Joan",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Jane MacAdam",
        "href": "/en/senators/macadam-beverly-jane/",
        "image": "https://sencanada.ca/media/35kiitf5/sen_pho_macadam_official_2024.jpg?center=0.402219426166952,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953402323930000&quality=95",
        "alt": "MacAdam, Jane",
        "affiliation": "ISG - (Prince Edward Island)"
      },
      {
        "name": "Elizabeth Marshall",
        "href": "/en/senators/marshall-elizabeth/",
        "image": "https://sencanada.ca/media/p2lbqiqx/sen_pho_marshall_official_2024.jpg?center=0.30801344134169434,0.47226417343585692&mode=crop&width=95&height=100&rnd=133953399107870000&quality=95",
        "alt": "Marshall, Elizabeth",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Pierre Moreau",
        "href": "/en/senators/moreau-pierre/",
        "image": "https://sencanada.ca/media/2gzb1mkb/sen_pho_moreau_official.jpg?center=0.38228341294233087,0.51181271432115993&mode=crop&width=95&height=100&rnd=133953399110370000&quality=95",
        "alt": "Moreau, Pierre",
        "affiliation": "PSG - (Quebec - The Laurentides)"
      },
      {
        "name": "Sandra Pupatello",
        "href": "/en/senators/pupatello-sandra/",
        "image": "https://sencanada.ca/media/233fr2g1/sen_pho_pupatello_official_2025.jpg?center=0.44347270064561373,0.50896305140314746&mode=crop&width=95&height=100&rnd=133953399112100000&quality=95",
        "alt": "Pupatello, Sandra",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Toni Varone",
        "href": "/en/senators/varone-toni/",
        "image": "https://sencanada.ca/media/cq2ggfgb/sen_pho_varone_official_2024.jpg?center=0.41105941355523662,0.572583432828541&mode=crop&width=95&height=100&rnd=133953399115530000&quality=95",
        "alt": "Varone, Toni",
        "affiliation": "ISG - (Ontario)"
      }
    ]
  },
  {
    "href": "/en/committees/ollo/45-1",
      "acronym": "OLLO",
      "name_full": "Official Languages",
      "name_short": "Official Languages",
    "members": [
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=90",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Rose-May Poirier",
        "href": "/en/senators/poirier-rose-may/",
        "image": "https://sencanada.ca/media/4uwlew2f/sen_pho_poirier_official_2024.jpg?center=0.39193901420517407,0.45739014647137149&mode=crop&width=95&height=100&rnd=133953399111800000&quality=90",
        "alt": "Poirier, Rose-May",
        "affiliation": "C - (New Brunswick - Saint-Louis-de-Kent)"
      },
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=90",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Rose-May Poirier",
        "href": "/en/senators/poirier-rose-may/",
        "image": "https://sencanada.ca/media/4uwlew2f/sen_pho_poirier_official_2024.jpg?center=0.39193901420517407,0.45739014647137149&mode=crop&width=95&height=100&rnd=133953399111800000&quality=90",
        "alt": "Poirier, Rose-May",
        "affiliation": "C - (New Brunswick - Saint-Louis-de-Kent)"
      },
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=95",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Ren\u00e9 Cormier",
        "href": "/en/senators/cormier-rene/",
        "image": "https://sencanada.ca/media/bsgbexch/sen_pho_cormier_official_2024.jpg?center=0.375393019937317,0.50202389129278346&mode=crop&width=95&height=100&rnd=133953399099130000&quality=95",
        "alt": "Cormier, Ren\u00e9",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Amina Gerba",
        "href": "/en/senators/gerba-amina/",
        "image": "https://sencanada.ca/media/utonnu0t/sen_pho_gerba_official_2024.jpg?center=0.40647362536155773,0.49673563804093013&mode=crop&width=95&height=100&rnd=133953399103200000&quality=95",
        "alt": "Gerba, Amina",
        "affiliation": "PSG - (Quebec - Rigaud)"
      },
      {
        "name": "Tony Ince",
        "href": "/en/senators/ince-tony/",
        "image": "https://sencanada.ca/media/4dghfsft/sen_pho_ince_official.jpg?center=0.384572304572723,0.50717761441942166&mode=crop&width=95&height=100&rnd=133953399105230000&quality=95",
        "alt": "Ince, Tony",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Lucie Moncion",
        "href": "/en/senators/moncion-lucie/",
        "image": "https://sencanada.ca/media/m1hge4bp/sen_pho_mocion_official_2024.jpg?center=0.36662689106284063,0.41218847511068274&mode=crop&width=95&height=100&rnd=133953399109900000&quality=95",
        "alt": "Moncion, Lucie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Rebecca Patterson",
        "href": "/en/senators/patterson-rebecca/",
        "image": "https://sencanada.ca/media/izdcqinz/sen_pho_patterson_official_2024.jpg?center=0.36391281415105181,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953399113970000&quality=95",
        "alt": "Patterson, Rebecca",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Mich\u00e8le Audette",
        "href": "/en/senators/audette-michele/",
        "image": "https://sencanada.ca/media/i0pdebyo/sen_pho_audette_official_2024.jpg?center=0.37717258684592186,0.48139434706252693&mode=crop&width=95&height=100&rnd=133953399096300000&quality=95",
        "alt": "Audette, Mich\u00e8le",
        "affiliation": "PSG - (Quebec - De Salaberry)"
      },
      {
        "name": "Ren\u00e9 Cormier",
        "href": "/en/senators/cormier-rene/",
        "image": "https://sencanada.ca/media/bsgbexch/sen_pho_cormier_official_2024.jpg?center=0.375393019937317,0.50202389129278346&mode=crop&width=95&height=100&rnd=133953399099130000&quality=95",
        "alt": "Cormier, Ren\u00e9",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Amina Gerba",
        "href": "/en/senators/gerba-amina/",
        "image": "https://sencanada.ca/media/utonnu0t/sen_pho_gerba_official_2024.jpg?center=0.40647362536155773,0.49673563804093013&mode=crop&width=95&height=100&rnd=133953399103200000&quality=95",
        "alt": "Gerba, Amina",
        "affiliation": "PSG - (Quebec - Rigaud)"
      },
      {
        "name": "Tony Ince",
        "href": "/en/senators/ince-tony/",
        "image": "https://sencanada.ca/media/4dghfsft/sen_pho_ince_official.jpg?center=0.384572304572723,0.50717761441942166&mode=crop&width=95&height=100&rnd=133953399105230000&quality=95",
        "alt": "Ince, Tony",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Lucie Moncion",
        "href": "/en/senators/moncion-lucie/",
        "image": "https://sencanada.ca/media/m1hge4bp/sen_pho_mocion_official_2024.jpg?center=0.36662689106284063,0.41218847511068274&mode=crop&width=95&height=100&rnd=133953399109900000&quality=95",
        "alt": "Moncion, Lucie",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Rebecca Patterson",
        "href": "/en/senators/patterson-rebecca/",
        "image": "https://sencanada.ca/media/izdcqinz/sen_pho_patterson_official_2024.jpg?center=0.36391281415105181,0.47503218130960434&mode=crop&width=95&height=100&rnd=133953399113970000&quality=95",
        "alt": "Patterson, Rebecca",
        "affiliation": "CSG - (Ontario)"
      }
    ]
  },
  {
    "href": "/en/committees/pofo/45-1",
      "acronym": "POFO",
      "name_full": "Fisheries and Oceans",
      "name_short": "Fisheries",
    "members": [
      {
        "name": "Fabian Manning",
        "href": "/en/senators/manning-fabian/",
        "image": "https://sencanada.ca/media/psrfhiws/sen_pho_manning_official_2024.jpg?center=0.38453945139038265,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953399107400000&quality=90",
        "alt": "Manning, Fabian",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=90",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Fabian Manning",
        "href": "/en/senators/manning-fabian/",
        "image": "https://sencanada.ca/media/psrfhiws/sen_pho_manning_official_2024.jpg?center=0.38453945139038265,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953399107400000&quality=90",
        "alt": "Manning, Fabian",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=90",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Victor Boudreau",
        "href": "/en/senators/boudreau-victor/",
        "image": "https://sencanada.ca/media/gvtoevkk/sen_pho_boudreau_official.jpg?center=0.3771727952334788,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399097230000&quality=95",
        "alt": "Boudreau, Victor",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Rodger Cuzner",
        "href": "/en/senators/cuzner-rodger/",
        "image": "https://sencanada.ca/media/byiflqn4/sen_pho_cuzner_official_2024.jpg?center=0.40029738034074341,0.47377000818954645&mode=crop&width=95&height=100&rnd=133953399099730000&quality=95",
        "alt": "Cuzner, Rodger",
        "affiliation": "PSG - (Nova Scotia)"
      },
      {
        "name": "Colin Deacon",
        "href": "/en/senators/deacon-colin/",
        "image": "https://sencanada.ca/media/xllg2j35/sen_pho_deacon-colin_official_2024.jpg?center=0.40979304311793552,0.48633155505483944&mode=crop&width=95&height=100&rnd=133953399100530000&quality=95",
        "alt": "Deacon, Colin",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Baltej S. Dhillon",
        "href": "/en/senators/dhillon-baltej-s/",
        "image": "https://sencanada.ca/media/tbxdmqni/sen_pho_dhillon_official.jpg?center=0.38841822242592289,0.51988463292931186&mode=crop&width=95&height=100&rnd=133953399101170000&quality=95",
        "alt": "Dhillon, Baltej S.",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Amina Gerba",
        "href": "/en/senators/gerba-amina/",
        "image": "https://sencanada.ca/media/utonnu0t/sen_pho_gerba_official_2024.jpg?center=0.40647362536155773,0.49673563804093013&mode=crop&width=95&height=100&rnd=133953399103200000&quality=95",
        "alt": "Gerba, Amina",
        "affiliation": "PSG - (Quebec - Rigaud)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Iris G. Petten",
        "href": "/en/senators/petten-iris/",
        "image": "https://sencanada.ca/media/flhokfcl/sen_pho_petten_official_2024.jpg?center=0.39732673485424785,0.50614186821947338&mode=crop&width=95&height=100&rnd=133953399111470000&quality=95",
        "alt": "Petten, Iris G.",
        "affiliation": "Non-affiliated - (Newfoundland and Labrador)"
      },
      {
        "name": "Rose-May Poirier",
        "href": "/en/senators/poirier-rose-may/",
        "image": "https://sencanada.ca/media/4uwlew2f/sen_pho_poirier_official_2024.jpg?center=0.39193901420517407,0.45739014647137149&mode=crop&width=95&height=100&rnd=133953399111800000&quality=95",
        "alt": "Poirier, Rose-May",
        "affiliation": "C - (New Brunswick - Saint-Louis-de-Kent)"
      },
      {
        "name": "Mohamed-Iqbal Ravalia",
        "href": "/en/senators/ravalia-mohamed-iqbal/",
        "image": "https://sencanada.ca/media/cwen5ay0/sen_pho_ravalia_official_2024.jpg?center=0.380479788686098,0.58082894556956211&mode=crop&width=95&height=100&rnd=133953399112400000&quality=95",
        "alt": "Ravalia, Mohamed-Iqbal",
        "affiliation": "ISG - (Newfoundland and Labrador)"
      },
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=95",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Victor Boudreau",
        "href": "/en/senators/boudreau-victor/",
        "image": "https://sencanada.ca/media/gvtoevkk/sen_pho_boudreau_official.jpg?center=0.3771727952334788,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399097230000&quality=95",
        "alt": "Boudreau, Victor",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Rodger Cuzner",
        "href": "/en/senators/cuzner-rodger/",
        "image": "https://sencanada.ca/media/byiflqn4/sen_pho_cuzner_official_2024.jpg?center=0.40029738034074341,0.47377000818954645&mode=crop&width=95&height=100&rnd=133953399099730000&quality=95",
        "alt": "Cuzner, Rodger",
        "affiliation": "PSG - (Nova Scotia)"
      },
      {
        "name": "Colin Deacon",
        "href": "/en/senators/deacon-colin/",
        "image": "https://sencanada.ca/media/xllg2j35/sen_pho_deacon-colin_official_2024.jpg?center=0.40979304311793552,0.48633155505483944&mode=crop&width=95&height=100&rnd=133953399100530000&quality=95",
        "alt": "Deacon, Colin",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Baltej S. Dhillon",
        "href": "/en/senators/dhillon-baltej-s/",
        "image": "https://sencanada.ca/media/tbxdmqni/sen_pho_dhillon_official.jpg?center=0.38841822242592289,0.51988463292931186&mode=crop&width=95&height=100&rnd=133953399101170000&quality=95",
        "alt": "Dhillon, Baltej S.",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Amina Gerba",
        "href": "/en/senators/gerba-amina/",
        "image": "https://sencanada.ca/media/utonnu0t/sen_pho_gerba_official_2024.jpg?center=0.40647362536155773,0.49673563804093013&mode=crop&width=95&height=100&rnd=133953399103200000&quality=95",
        "alt": "Gerba, Amina",
        "affiliation": "PSG - (Quebec - Rigaud)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Iris G. Petten",
        "href": "/en/senators/petten-iris/",
        "image": "https://sencanada.ca/media/flhokfcl/sen_pho_petten_official_2024.jpg?center=0.39732673485424785,0.50614186821947338&mode=crop&width=95&height=100&rnd=133953399111470000&quality=95",
        "alt": "Petten, Iris G.",
        "affiliation": "Non-affiliated - (Newfoundland and Labrador)"
      },
      {
        "name": "Rose-May Poirier",
        "href": "/en/senators/poirier-rose-may/",
        "image": "https://sencanada.ca/media/4uwlew2f/sen_pho_poirier_official_2024.jpg?center=0.39193901420517407,0.45739014647137149&mode=crop&width=95&height=100&rnd=133953399111800000&quality=95",
        "alt": "Poirier, Rose-May",
        "affiliation": "C - (New Brunswick - Saint-Louis-de-Kent)"
      },
      {
        "name": "Mohamed-Iqbal Ravalia",
        "href": "/en/senators/ravalia-mohamed-iqbal/",
        "image": "https://sencanada.ca/media/cwen5ay0/sen_pho_ravalia_official_2024.jpg?center=0.380479788686098,0.58082894556956211&mode=crop&width=95&height=100&rnd=133953399112400000&quality=95",
        "alt": "Ravalia, Mohamed-Iqbal",
        "affiliation": "ISG - (Newfoundland and Labrador)"
      },
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=95",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      }
    ]
  },
  {
    "href": "/en/committees/ridr/45-1",
      "acronym": "RIDR",
      "name_full": "Human Rights",
      "name_short": "Human Rights",
    "members": [
      {
        "name": "Paulette Senior",
        "href": "/en/senators/senior-paulette/",
        "image": "https://sencanada.ca/media/qhkhihsm/sen_pho_senior_official_2024.jpg?center=0.32804792107117686,0.48984055536184107&mode=crop&width=95&height=100&rnd=133953399114300000&quality=90",
        "alt": "Senior, Paulette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Wanda Thomas Bernard",
        "href": "/en/senators/bernard-wanda-thomas/",
        "image": "https://sencanada.ca/media/mejfthej/sen_pho_bernard_official_2024.jpg?center=0.41561730242408895,0.50697504887504552&mode=crop&width=95&height=100&rnd=133953399096630000&quality=90",
        "alt": "Bernard, Wanda Thomas",
        "affiliation": "PSG - (Nova Scotia - East Preston)"
      },
      {
        "name": "Paulette Senior",
        "href": "/en/senators/senior-paulette/",
        "image": "https://sencanada.ca/media/qhkhihsm/sen_pho_senior_official_2024.jpg?center=0.32804792107117686,0.48984055536184107&mode=crop&width=95&height=100&rnd=133953399114300000&quality=90",
        "alt": "Senior, Paulette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Wanda Thomas Bernard",
        "href": "/en/senators/bernard-wanda-thomas/",
        "image": "https://sencanada.ca/media/mejfthej/sen_pho_bernard_official_2024.jpg?center=0.41561730242408895,0.50697504887504552&mode=crop&width=95&height=100&rnd=133953399096630000&quality=90",
        "alt": "Bernard, Wanda Thomas",
        "affiliation": "PSG - (Nova Scotia - East Preston)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=95",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Mary Coyle",
        "href": "/en/senators/coyle-mary/",
        "image": "https://sencanada.ca/media/0wqdqvir/sen_pho_coyle_official_2024.jpg?center=0.40516608862971354,0.51956644830737975&mode=crop&width=95&height=100&rnd=133953403354530000&quality=95",
        "alt": "Coyle, Mary",
        "affiliation": "ISG - (Nova Scotia - Antigonish)"
      },
      {
        "name": "Nancy Karetak-Lindell",
        "href": "/en/senators/karetak-lindell-nancy/",
        "image": "https://sencanada.ca/media/q0uj1sd0/sen_pho_karetak-lindell_official.jpg?center=0.31156351383605357,0.49693482303990905&mode=crop&width=95&height=100&rnd=133953399105700000&quality=95",
        "alt": "Karetak-Lindell, Nancy",
        "affiliation": "ISG - (Nunavut)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=95",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Mary Coyle",
        "href": "/en/senators/coyle-mary/",
        "image": "https://sencanada.ca/media/0wqdqvir/sen_pho_coyle_official_2024.jpg?center=0.40516608862971354,0.51956644830737975&mode=crop&width=95&height=100&rnd=133953403354530000&quality=95",
        "alt": "Coyle, Mary",
        "affiliation": "ISG - (Nova Scotia - Antigonish)"
      },
      {
        "name": "Nancy Karetak-Lindell",
        "href": "/en/senators/karetak-lindell-nancy/",
        "image": "https://sencanada.ca/media/q0uj1sd0/sen_pho_karetak-lindell_official.jpg?center=0.31156351383605357,0.49693482303990905&mode=crop&width=95&height=100&rnd=133953399105700000&quality=95",
        "alt": "Karetak-Lindell, Nancy",
        "affiliation": "ISG - (Nunavut)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=95",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      }
    ]
  },
  {
    "href": "/en/committees/rprd/45-1",
      "acronym": "RPRD",
      "name_full": "Rules, Procedures and the Rights of Parliament",
      "name_short": "Rules, Procedures",
    "members": [
      {
        "name": "Pierre J. Dalphond",
        "href": "/en/senators/dalphond-pierre/",
        "image": "https://sencanada.ca/media/jzcgtom3/sen_pho_dalphond_official_2024.jpg?center=0.35728117912974378,0.45756206574401709&mode=crop&width=95&height=100&rnd=133953399100070000&quality=90",
        "alt": "Dalphond, Pierre J.",
        "affiliation": "PSG - (Quebec - De Lorimier)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=90",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "Percy E. Downe",
        "href": "/en/senators/downe-percy-e/",
        "image": "https://sencanada.ca/media/riuielkr/sen_pho_downe_official_2024.jpg?center=0.39799175061299108,0.53021765445520341&mode=crop&width=95&height=100&rnd=133953399101300000&quality=90",
        "alt": "Downe, Percy E.",
        "affiliation": "CSG - (Prince Edward Island - Charlottetown)"
      },
      {
        "name": "Pierrette Ringuette",
        "href": "/en/senators/ringuette-pierrette/",
        "image": "https://sencanada.ca/media/ikultfz5/sen_pho_ringuette_official.jpg?center=0.43168605079456751,0.47927354007129719&mode=crop&width=95&height=100&rnd=133953399112870000&quality=90",
        "alt": "Ringuette, Pierrette",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Pierre J. Dalphond",
        "href": "/en/senators/dalphond-pierre/",
        "image": "https://sencanada.ca/media/jzcgtom3/sen_pho_dalphond_official_2024.jpg?center=0.35728117912974378,0.45756206574401709&mode=crop&width=95&height=100&rnd=133953399100070000&quality=90",
        "alt": "Dalphond, Pierre J.",
        "affiliation": "PSG - (Quebec - De Lorimier)"
      },
      {
        "name": "Denise Batters",
        "href": "/en/senators/batters-denise/",
        "image": "https://sencanada.ca/media/jqzobltq/sen_pho_batters_official_2024.jpg?center=0.39172172471741984,0.50641174326518446&mode=crop&width=95&height=100&rnd=133953399096470000&quality=90",
        "alt": "Batters, Denise",
        "affiliation": "C - (Saskatchewan)"
      },
      {
        "name": "Percy E. Downe",
        "href": "/en/senators/downe-percy-e/",
        "image": "https://sencanada.ca/media/riuielkr/sen_pho_downe_official_2024.jpg?center=0.39799175061299108,0.53021765445520341&mode=crop&width=95&height=100&rnd=133953399101300000&quality=90",
        "alt": "Downe, Percy E.",
        "affiliation": "CSG - (Prince Edward Island - Charlottetown)"
      },
      {
        "name": "Pierrette Ringuette",
        "href": "/en/senators/ringuette-pierrette/",
        "image": "https://sencanada.ca/media/ikultfz5/sen_pho_ringuette_official.jpg?center=0.43168605079456751,0.47927354007129719&mode=crop&width=95&height=100&rnd=133953399112870000&quality=90",
        "alt": "Ringuette, Pierrette",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=95",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=95",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=95",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Judy A. White",
        "href": "/en/senators/white-judy/",
        "image": "https://sencanada.ca/media/tqlbjf04/sen_pho_white_official_2024.jpg?center=0.38724453840732909,0.46955336482074367&mode=crop&width=95&height=100&rnd=133953399116300000&quality=95",
        "alt": "White, Judy A.",
        "affiliation": "PSG - (Newfoundland and Labrador)"
      },
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=95",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Bev Busson",
        "href": "/en/senators/busson-bev/",
        "image": "https://sencanada.ca/media/u3yegw0q/sen_pho_busson_official_2024.jpg?center=0.45490039408430843,0.485788366915059&mode=crop&width=95&height=100&rnd=133953399098200000&quality=95",
        "alt": "Busson, Bev",
        "affiliation": "ISG - (British Columbia)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Allister W. Surette",
        "href": "/en/senators/surette-allister/",
        "image": "https://sencanada.ca/media/tqtknxzc/sen_pho_surette_official.jpg?center=0.44789269433975604,0.51108373078399394&mode=crop&width=95&height=100&rnd=133953399115230000&quality=95",
        "alt": "Surette, Allister W.",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "Scott Tannas",
        "href": "/en/senators/tannas-scott/",
        "image": "https://sencanada.ca/media/csjlraxb/sen_pho_tannas_official_2024.jpg?center=0.39114620502313591,0.55518738195433914&mode=crop&width=95&height=100&rnd=133953399115370000&quality=95",
        "alt": "Tannas, Scott",
        "affiliation": "CSG - (Alberta)"
      },
      {
        "name": "David M. Wells",
        "href": "/en/senators/wells-david-m/",
        "image": "https://sencanada.ca/media/s40fucit/sen_pho_david-wells_official_2024.jpg?center=0.39126152513355744,0.45523365115248321&mode=crop&width=95&height=100&rnd=133953399116170000&quality=95",
        "alt": "Wells, David M.",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Kristopher Wells",
        "href": "/en/senators/wells-kristopher/",
        "image": "https://sencanada.ca/media/saxnvpin/sen_pho_k-wells_official_2024.jpg?center=0.39485277001004809,0.51532508954568679&mode=crop&width=95&height=100&rnd=133953399105370000&quality=95",
        "alt": "Wells, Kristopher",
        "affiliation": "PSG - (Alberta)"
      },
      {
        "name": "Judy A. White",
        "href": "/en/senators/white-judy/",
        "image": "https://sencanada.ca/media/tqlbjf04/sen_pho_white_official_2024.jpg?center=0.38724453840732909,0.46955336482074367&mode=crop&width=95&height=100&rnd=133953399116300000&quality=95",
        "alt": "White, Judy A.",
        "affiliation": "PSG - (Newfoundland and Labrador)"
      },
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=95",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      }
    ]
  },
  {
    "href": "/en/committees/secd/45-1",
      "acronym": "SECD",
      "name_full": "National Security, Defence and Veterans Affairs",
      "name_short": "Defence",
    "members": [
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=90",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Mohammad Al Zaibak",
        "href": "/en/senators/al-zaibak-mohammad-khair/",
        "image": "https://sencanada.ca/media/nalbnwmb/sen_pho_al-zaibak_official_2024.jpg?center=0.40089431517076507,0.506629828852538&mode=crop&width=95&height=100&rnd=133953399095200000&quality=90",
        "alt": "Al Zaibak, Mohammad",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Hassan Yussuff",
        "href": "/en/senators/yussuff-hassan/",
        "image": "https://sencanada.ca/media/1p4gjprf/sen_pho_yussuff_official_2024.jpg?center=0.37717258684592186,0.46018754763245967&mode=crop&width=95&height=100&rnd=133953399117100000&quality=90",
        "alt": "Yussuff, Hassan",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Mohammad Al Zaibak",
        "href": "/en/senators/al-zaibak-mohammad-khair/",
        "image": "https://sencanada.ca/media/nalbnwmb/sen_pho_al-zaibak_official_2024.jpg?center=0.40089431517076507,0.506629828852538&mode=crop&width=95&height=100&rnd=133953399095200000&quality=90",
        "alt": "Al Zaibak, Mohammad",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Dawn Anderson",
        "href": "/en/senators/anderson-margaret/",
        "image": "https://sencanada.ca/media/nmemnah0/sen_pho_anderson_official_2024.jpg?center=0.404085788062057,0.46996252564457858&mode=crop&width=95&height=100&rnd=133953399095370000&quality=95",
        "alt": "Anderson, Dawn",
        "affiliation": "PSG - (Northwest Territories)"
      },
      {
        "name": "Andrew Cardozo",
        "href": "/en/senators/cardozo-andrew/",
        "image": "https://sencanada.ca/media/fr4m4b54/sen_pho_cardozo_official_2024.jpg?center=0.41707283352201385,0.51905090048902747&mode=crop&width=95&height=100&rnd=133953399098330000&quality=95",
        "alt": "Cardozo, Andrew",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=95",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Donna Dasko",
        "href": "/en/senators/dasko-donna/",
        "image": "https://sencanada.ca/media/wcrjo2ow/sen_pho_dasko_official_2024.jpg?center=0.36472169936455284,0.43914033241985162&mode=crop&width=95&height=100&rnd=133953399100200000&quality=95",
        "alt": "Dasko, Donna",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Marty Deacon",
        "href": "/en/senators/deacon-marty/",
        "image": "https://sencanada.ca/media/03tehv0q/sen_pho_deaconm_official_2024.jpg?center=0.39640163789548111,0.51473849617507572&mode=crop&width=95&height=100&rnd=133953399100700000&quality=95",
        "alt": "Deacon, Marty",
        "affiliation": "ISG - (Ontario - Waterloo Region)"
      },
      {
        "name": "Pat Duncan",
        "href": "/en/senators/duncan-pat/",
        "image": "https://sencanada.ca/media/tsjitw0d/sen_pho_duncan_official_2024.jpg?center=0.38530447160966591,0.53569246433694684&mode=crop&width=95&height=100&rnd=133953399101470000&quality=95",
        "alt": "Duncan, Pat",
        "affiliation": "ISG - (Yukon)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Tony Ince",
        "href": "/en/senators/ince-tony/",
        "image": "https://sencanada.ca/media/4dghfsft/sen_pho_ince_official.jpg?center=0.384572304572723,0.50717761441942166&mode=crop&width=95&height=100&rnd=133953399105230000&quality=95",
        "alt": "Ince, Tony",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Stan Kutcher",
        "href": "/en/senators/kutcher-stan/",
        "image": "https://sencanada.ca/media/r1vfsa0k/sen_pho_kutcher_official_2024.jpg?center=0.39133008856782647,0.54348626232738417&mode=crop&width=95&height=100&rnd=133953399106300000&quality=95",
        "alt": "Kutcher, Stan",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "John M. McNair",
        "href": "/en/senators/mcnair-john-m/",
        "image": "https://sencanada.ca/media/yr4kwcj1/sen_pho_mcnair_official_2024.jpg?center=0.37930393685352287,0.47083675544428272&mode=crop&width=95&height=100&rnd=133953399108970000&quality=95",
        "alt": "McNair, John M.",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "David Richards",
        "href": "/en/senators/richards-david/",
        "image": "https://sencanada.ca/media/dy4jis1j/sen_pho_richards_official_2024.jpg?center=0.33076430212690744,0.57160772958755057&mode=crop&width=95&height=100&rnd=133953399112730000&quality=95",
        "alt": "Richards, David",
        "affiliation": "C - (New Brunswick)"
      },
      {
        "name": "Dawn Anderson",
        "href": "/en/senators/anderson-margaret/",
        "image": "https://sencanada.ca/media/nmemnah0/sen_pho_anderson_official_2024.jpg?center=0.404085788062057,0.46996252564457858&mode=crop&width=95&height=100&rnd=133953399095370000&quality=95",
        "alt": "Anderson, Dawn",
        "affiliation": "PSG - (Northwest Territories)"
      },
      {
        "name": "Andrew Cardozo",
        "href": "/en/senators/cardozo-andrew/",
        "image": "https://sencanada.ca/media/fr4m4b54/sen_pho_cardozo_official_2024.jpg?center=0.41707283352201385,0.51905090048902747&mode=crop&width=95&height=100&rnd=133953399098330000&quality=95",
        "alt": "Cardozo, Andrew",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Claude Carignan",
        "href": "/en/senators/carignan-claude/",
        "image": "https://sencanada.ca/media/phznjx2v/com_sen_carignan_official_2024.jpg?center=0.40460315835375488,0.46311529238787591&mode=crop&width=95&height=100&rnd=133953399098500000&quality=95",
        "alt": "Carignan, Claude, P.C.",
        "affiliation": "C - (Quebec - Mille Isles)"
      },
      {
        "name": "Donna Dasko",
        "href": "/en/senators/dasko-donna/",
        "image": "https://sencanada.ca/media/wcrjo2ow/sen_pho_dasko_official_2024.jpg?center=0.36472169936455284,0.43914033241985162&mode=crop&width=95&height=100&rnd=133953399100200000&quality=95",
        "alt": "Dasko, Donna",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Marty Deacon",
        "href": "/en/senators/deacon-marty/",
        "image": "https://sencanada.ca/media/03tehv0q/sen_pho_deaconm_official_2024.jpg?center=0.39640163789548111,0.51473849617507572&mode=crop&width=95&height=100&rnd=133953399100700000&quality=95",
        "alt": "Deacon, Marty",
        "affiliation": "ISG - (Ontario - Waterloo Region)"
      },
      {
        "name": "Pat Duncan",
        "href": "/en/senators/duncan-pat/",
        "image": "https://sencanada.ca/media/tsjitw0d/sen_pho_duncan_official_2024.jpg?center=0.38530447160966591,0.53569246433694684&mode=crop&width=95&height=100&rnd=133953399101470000&quality=95",
        "alt": "Duncan, Pat",
        "affiliation": "ISG - (Yukon)"
      },
      {
        "name": "Brian Francis",
        "href": "/en/senators/francis-brian/",
        "image": "https://sencanada.ca/media/mc3n2kqs/sen_pho_francis_official_2024.jpg?center=0.27208988452880589,0.55986889557960606&mode=crop&width=95&height=100&rnd=133953399102100000&quality=95",
        "alt": "Francis, Brian",
        "affiliation": "PSG - (Prince Edward Island)"
      },
      {
        "name": "Tony Ince",
        "href": "/en/senators/ince-tony/",
        "image": "https://sencanada.ca/media/4dghfsft/sen_pho_ince_official.jpg?center=0.384572304572723,0.50717761441942166&mode=crop&width=95&height=100&rnd=133953399105230000&quality=95",
        "alt": "Ince, Tony",
        "affiliation": "CSG - (Nova Scotia)"
      },
      {
        "name": "Stan Kutcher",
        "href": "/en/senators/kutcher-stan/",
        "image": "https://sencanada.ca/media/r1vfsa0k/sen_pho_kutcher_official_2024.jpg?center=0.39133008856782647,0.54348626232738417&mode=crop&width=95&height=100&rnd=133953399106300000&quality=95",
        "alt": "Kutcher, Stan",
        "affiliation": "ISG - (Nova Scotia)"
      },
      {
        "name": "John M. McNair",
        "href": "/en/senators/mcnair-john-m/",
        "image": "https://sencanada.ca/media/yr4kwcj1/sen_pho_mcnair_official_2024.jpg?center=0.37930393685352287,0.47083675544428272&mode=crop&width=95&height=100&rnd=133953399108970000&quality=95",
        "alt": "McNair, John M.",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "David Richards",
        "href": "/en/senators/richards-david/",
        "image": "https://sencanada.ca/media/dy4jis1j/sen_pho_richards_official_2024.jpg?center=0.33076430212690744,0.57160772958755057&mode=crop&width=95&height=100&rnd=133953399112730000&quality=95",
        "alt": "Richards, David",
        "affiliation": "C - (New Brunswick)"
      }
    ]
  },
  {
    "href": "/en/committees/sele/45-1",
      "acronym": "SELE",
      "name_full": "Selection Committee",
      "name_short": "Selection",
    "members": [
      {
        "name": "Michael L. MacDonald",
        "href": "/en/senators/macdonald-michael-l/",
        "image": "https://sencanada.ca/media/gocpeh02/sen_pho_macdonald_official_2024.jpg?center=0.38132921229098238,0.56382001342519816&mode=crop&width=95&height=100&rnd=133953399107270000&quality=90",
        "alt": "MacDonald, Michael L.",
        "affiliation": "C - (Nova Scotia - Cape Breton)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=90",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "Michael L. MacDonald",
        "href": "/en/senators/macdonald-michael-l/",
        "image": "https://sencanada.ca/media/gocpeh02/sen_pho_macdonald_official_2024.jpg?center=0.38132921229098238,0.56382001342519816&mode=crop&width=95&height=100&rnd=133953399107270000&quality=90",
        "alt": "MacDonald, Michael L.",
        "affiliation": "C - (Nova Scotia - Cape Breton)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=90",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=95",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Percy E. Downe",
        "href": "/en/senators/downe-percy-e/",
        "image": "https://sencanada.ca/media/riuielkr/sen_pho_downe_official_2024.jpg?center=0.39799175061299108,0.53021765445520341&mode=crop&width=95&height=100&rnd=133953399101300000&quality=95",
        "alt": "Downe, Percy E.",
        "affiliation": "CSG - (Prince Edward Island - Charlottetown)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=95",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Duncan Wilson",
        "href": "/en/senators/wilson-duncan/",
        "image": "https://sencanada.ca/media/4eminkuz/sen_pho_wilson_official.jpg?center=0.38114382711465239,0.51143022064049992&mode=crop&width=95&height=100&rnd=133953399116470000&quality=95",
        "alt": "Wilson, Duncan",
        "affiliation": "PSG - (British Columbia)"
      },
      {
        "name": "David M. Arnot",
        "href": "/en/senators/arnot-david/",
        "image": "https://sencanada.ca/media/gpnlejy1/sen_pho_arnot_official_2024.jpg?center=0.390486311403914,0.48195226955766712&mode=crop&width=95&height=100&rnd=133953399095830000&quality=95",
        "alt": "Arnot, David M.",
        "affiliation": "ISG - (Saskatchewan)"
      },
      {
        "name": "Bernadette Clement",
        "href": "/en/senators/clement-bernadette/",
        "image": "https://sencanada.ca/media/ipcdgb5s/sen_pho_clement_official_2024.jpg?center=0.3900844572544841,0.46550661278670796&mode=crop&width=95&height=100&rnd=133953399098800000&quality=95",
        "alt": "Clement, Bernadette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Percy E. Downe",
        "href": "/en/senators/downe-percy-e/",
        "image": "https://sencanada.ca/media/riuielkr/sen_pho_downe_official_2024.jpg?center=0.39799175061299108,0.53021765445520341&mode=crop&width=95&height=100&rnd=133953399101300000&quality=95",
        "alt": "Downe, Percy E.",
        "affiliation": "CSG - (Prince Edward Island - Charlottetown)"
      },
      {
        "name": "Dani\u00e8le Henkel",
        "href": "/en/senators/henkel-daniele/",
        "image": "https://sencanada.ca/media/zo2a0vea/sen_pho_henkel_official.png?center=0.3742261327707172,0.48139421945214367&mode=crop&width=95&height=100&rnd=133953399104900000&quality=95",
        "alt": "Henkel, Dani\u00e8le",
        "affiliation": "PSG - (Quebec - Alma)"
      },
      {
        "name": "Krista Ross",
        "href": "/en/senators/ross-krista-ann/",
        "image": "https://sencanada.ca/media/4rfmp5t2/sen_pho_ross_official_2024.jpg?center=0.39410459399411257,0.4564431011118722&mode=crop&width=95&height=100&rnd=133953399113500000&quality=95",
        "alt": "Ross, Krista",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Raymonde Saint-Germain",
        "href": "/en/senators/saint-germain-raymonde/",
        "image": "https://sencanada.ca/media/01nnhkfd/sen_pho_saint-germain_official_2024.jpg?center=0.36328400281888656,0.54867340793102359&mode=crop&width=95&height=100&rnd=133953399113670000&quality=95",
        "alt": "Saint-Germain, Raymonde",
        "affiliation": "ISG - (Quebec - De la Valli\u00e8re)"
      },
      {
        "name": "Duncan Wilson",
        "href": "/en/senators/wilson-duncan/",
        "image": "https://sencanada.ca/media/4eminkuz/sen_pho_wilson_official.jpg?center=0.38114382711465239,0.51143022064049992&mode=crop&width=95&height=100&rnd=133953399116470000&quality=95",
        "alt": "Wilson, Duncan",
        "affiliation": "PSG - (British Columbia)"
      }
    ]
  },
  {
    "href": "/en/committees/soci/45-1",
      "acronym": "SOCI",
      "name_full": "Social Affairs, Science and Technology",
      "name_short": "Social Affairs",
    "members": [
      {
        "name": "Rosemary Moodie",
        "href": "/en/senators/moodie-rosemary/",
        "image": "https://sencanada.ca/media/zjwmzdwg/sen_pho_moodie_official.jpg?center=0.38421052631578945,0.50378729518398735&mode=crop&width=95&height=100&rnd=133953399110070000&quality=90",
        "alt": "Moodie, Rosemary",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=90",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Rosemary Moodie",
        "href": "/en/senators/moodie-rosemary/",
        "image": "https://sencanada.ca/media/zjwmzdwg/sen_pho_moodie_official.jpg?center=0.38421052631578945,0.50378729518398735&mode=crop&width=95&height=100&rnd=133953399110070000&quality=90",
        "alt": "Moodie, Rosemary",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Flordeliz (Gigi) Osler",
        "href": "/en/senators/osler-flordeliz/",
        "image": "https://sencanada.ca/media/jhyfi0mi/sen_pho_osler_official_2024.jpg?center=0.375699464002098,0.45806674626283272&mode=crop&width=95&height=100&rnd=133953399110830000&quality=90",
        "alt": "Osler, Flordeliz (Gigi)",
        "affiliation": "CSG - (Manitoba)"
      },
      {
        "name": "Dawn Arnold",
        "href": "/en/senators/arnold-dawn/",
        "image": "https://sencanada.ca/media/4n5pq0zd/sen_pho_arnold_official.jpg?center=0.41105941355523662,0.52168712768822623&mode=crop&width=95&height=100&rnd=133953399095530000&quality=95",
        "alt": "Arnold, Dawn",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Wanda Thomas Bernard",
        "href": "/en/senators/bernard-wanda-thomas/",
        "image": "https://sencanada.ca/media/mejfthej/sen_pho_bernard_official_2024.jpg?center=0.41561730242408895,0.50697504887504552&mode=crop&width=95&height=100&rnd=133953399096630000&quality=95",
        "alt": "Bernard, Wanda Thomas",
        "affiliation": "PSG - (Nova Scotia - East Preston)"
      },
      {
        "name": "Victor Boudreau",
        "href": "/en/senators/boudreau-victor/",
        "image": "https://sencanada.ca/media/gvtoevkk/sen_pho_boudreau_official.jpg?center=0.3771727952334788,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399097230000&quality=95",
        "alt": "Boudreau, Victor",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Patrick Brazeau",
        "href": "/en/senators/brazeau-patrick/",
        "image": "https://sencanada.ca/media/cpgo0kxe/sen_pho_brazeau_official_2024.jpg?center=0.43479399359978443,0.51109457534806735&mode=crop&width=95&height=100&rnd=133953399097700000&quality=95",
        "alt": "Brazeau, Patrick",
        "affiliation": "Non-affiliated - (Quebec - Repentigny)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Katherine Hay",
        "href": "/en/senators/hay-katherine/",
        "image": "https://sencanada.ca/media/e3epefrj/sen_pho_hay_official.jpg?center=0.39190610754728655,0.4517047081202934&mode=crop&width=95&height=100&rnd=133953399104430000&quality=95",
        "alt": "Hay, Katherine",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Marilou McPhedran",
        "href": "/en/senators/mcphedran-marilou/",
        "image": "https://sencanada.ca/media/xuqgx0ay/sen_pho_mcphedran_official_2024.jpg?center=0.36099698599314906,0.51481070170850862&mode=crop&width=95&height=100&rnd=133953399109130000&quality=95",
        "alt": "McPhedran, Marilou",
        "affiliation": "Non-affiliated - (Manitoba)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Tracy Muggli",
        "href": "/en/senators/muggli-tracy/",
        "image": "https://sencanada.ca/media/eu0fd4uf/sen_pho_muggli_official_2024.jpg?center=0.40958608232385585,0.55773867716261583&mode=crop&width=95&height=100&rnd=133953399110700000&quality=95",
        "alt": "Muggli, Tracy",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "Paulette Senior",
        "href": "/en/senators/senior-paulette/",
        "image": "https://sencanada.ca/media/qhkhihsm/sen_pho_senior_official_2024.jpg?center=0.32804792107117686,0.48984055536184107&mode=crop&width=95&height=100&rnd=133953399114300000&quality=95",
        "alt": "Senior, Paulette",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Dawn Arnold",
        "href": "/en/senators/arnold-dawn/",
        "image": "https://sencanada.ca/media/4n5pq0zd/sen_pho_arnold_official.jpg?center=0.41105941355523662,0.52168712768822623&mode=crop&width=95&height=100&rnd=133953399095530000&quality=95",
        "alt": "Arnold, Dawn",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Wanda Thomas Bernard",
        "href": "/en/senators/bernard-wanda-thomas/",
        "image": "https://sencanada.ca/media/mejfthej/sen_pho_bernard_official_2024.jpg?center=0.41561730242408895,0.50697504887504552&mode=crop&width=95&height=100&rnd=133953399096630000&quality=95",
        "alt": "Bernard, Wanda Thomas",
        "affiliation": "PSG - (Nova Scotia - East Preston)"
      },
      {
        "name": "Victor Boudreau",
        "href": "/en/senators/boudreau-victor/",
        "image": "https://sencanada.ca/media/gvtoevkk/sen_pho_boudreau_official.jpg?center=0.3771727952334788,0.51744576892653327&mode=crop&width=95&height=100&rnd=133953399097230000&quality=95",
        "alt": "Boudreau, Victor",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Patrick Brazeau",
        "href": "/en/senators/brazeau-patrick/",
        "image": "https://sencanada.ca/media/cpgo0kxe/sen_pho_brazeau_official_2024.jpg?center=0.43479399359978443,0.51109457534806735&mode=crop&width=95&height=100&rnd=133953399097700000&quality=95",
        "alt": "Brazeau, Patrick",
        "affiliation": "Non-affiliated - (Quebec - Repentigny)"
      },
      {
        "name": "Sharon Burey",
        "href": "/en/senators/burey-sharon/",
        "image": "https://sencanada.ca/media/kkmciyn2/sen_pho_burey_official_2024.jpg?center=0.39492871030460147,0.47993154704248786&mode=crop&width=95&height=100&rnd=133953399098070000&quality=95",
        "alt": "Burey, Sharon",
        "affiliation": "CSG - (Ontario)"
      },
      {
        "name": "Katherine Hay",
        "href": "/en/senators/hay-katherine/",
        "image": "https://sencanada.ca/media/e3epefrj/sen_pho_hay_official.jpg?center=0.39190610754728655,0.4517047081202934&mode=crop&width=95&height=100&rnd=133953399104430000&quality=95",
        "alt": "Hay, Katherine",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Marilou McPhedran",
        "href": "/en/senators/mcphedran-marilou/",
        "image": "https://sencanada.ca/media/xuqgx0ay/sen_pho_mcphedran_official_2024.jpg?center=0.36099698599314906,0.51481070170850862&mode=crop&width=95&height=100&rnd=133953399109130000&quality=95",
        "alt": "McPhedran, Marilou",
        "affiliation": "Non-affiliated - (Manitoba)"
      },
      {
        "name": "Marie-Fran\u00e7oise M\u00e9gie",
        "href": "/en/senators/megie-marie-francoise/",
        "image": "https://sencanada.ca/media/unjhgh4v/sen_pho_megie_official_2024.jpg?center=0.35170317484786057,0.51845494039254592&mode=crop&width=95&height=100&rnd=133953399109300000&quality=95",
        "alt": "M\u00e9gie, Marie-Fran\u00e7oise",
        "affiliation": "ISG - (Quebec - Rougemont)"
      },
      {
        "name": "Tracy Muggli",
        "href": "/en/senators/muggli-tracy/",
        "image": "https://sencanada.ca/media/eu0fd4uf/sen_pho_muggli_official_2024.jpg?center=0.40958608232385585,0.55773867716261583&mode=crop&width=95&height=100&rnd=133953399110700000&quality=95",
        "alt": "Muggli, Tracy",
        "affiliation": "PSG - (Saskatchewan)"
      },
      {
        "name": "Chantal Petitclerc",
        "href": "/en/senators/petitclerc-chantal/",
        "image": "https://sencanada.ca/media/g34f1f54/sen_pho_petitclerc_official_2024.jpg?center=0.40388346097650957,0.51961715750390625&mode=crop&width=95&height=100&rnd=133953399111300000&quality=95",
        "alt": "Petitclerc, Chantal",
        "affiliation": "ISG - (Quebec - Grandville)"
      },
      {
        "name": "Paulette Senior",
        "href": "/en/senators/senior-paulette/",
        "image": "https://sencanada.ca/media/qhkhihsm/sen_pho_senior_official_2024.jpg?center=0.32804792107117686,0.48984055536184107&mode=crop&width=95&height=100&rnd=133953399114300000&quality=95",
        "alt": "Senior, Paulette",
        "affiliation": "ISG - (Ontario)"
      }
    ]
  },
  {
    "href": "/en/committees/trcm/45-1",
      "acronym": "TRCM",
      "name_full": "Transport and Communications",
      "name_short": "Transport",
    "members": [
      {
        "name": "Larry W. Smith",
        "href": "/en/senators/smith-larry-w/",
        "image": "https://sencanada.ca/media/r03d0lss/sen_pho_smith_official_2024.jpg?center=0.39388567876792746,0.46187746446204314&mode=crop&width=95&height=100&rnd=133953399114770000&quality=90",
        "alt": "Smith, Larry W.",
        "affiliation": "C - (Quebec - Saurel)"
      },
      {
        "name": "Donna Dasko",
        "href": "/en/senators/dasko-donna/",
        "image": "https://sencanada.ca/media/wcrjo2ow/sen_pho_dasko_official_2024.jpg?center=0.36472169936455284,0.43914033241985162&mode=crop&width=95&height=100&rnd=133953399100200000&quality=90",
        "alt": "Dasko, Donna",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Larry W. Smith",
        "href": "/en/senators/smith-larry-w/",
        "image": "https://sencanada.ca/media/r03d0lss/sen_pho_smith_official_2024.jpg?center=0.39388567876792746,0.46187746446204314&mode=crop&width=95&height=100&rnd=133953399114770000&quality=90",
        "alt": "Smith, Larry W.",
        "affiliation": "C - (Quebec - Saurel)"
      },
      {
        "name": "Donna Dasko",
        "href": "/en/senators/dasko-donna/",
        "image": "https://sencanada.ca/media/wcrjo2ow/sen_pho_dasko_official_2024.jpg?center=0.36472169936455284,0.43914033241985162&mode=crop&width=95&height=100&rnd=133953399100200000&quality=90",
        "alt": "Dasko, Donna",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Dawn Arnold",
        "href": "/en/senators/arnold-dawn/",
        "image": "https://sencanada.ca/media/4n5pq0zd/sen_pho_arnold_official.jpg?center=0.41105941355523662,0.52168712768822623&mode=crop&width=95&height=100&rnd=133953399095530000&quality=95",
        "alt": "Arnold, Dawn",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Ren\u00e9 Cormier",
        "href": "/en/senators/cormier-rene/",
        "image": "https://sencanada.ca/media/bsgbexch/sen_pho_cormier_official_2024.jpg?center=0.375393019937317,0.50202389129278346&mode=crop&width=95&height=100&rnd=133953399099130000&quality=95",
        "alt": "Cormier, Ren\u00e9",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Tony Dean",
        "href": "/en/senators/dean-tony/",
        "image": "https://sencanada.ca/media/udqfumdz/sen_pho_dean_official_2024.jpg?center=0.33999338639432342,0.47960414887524228&mode=crop&width=95&height=100&rnd=133953399100830000&quality=95",
        "alt": "Dean, Tony",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Katherine Hay",
        "href": "/en/senators/hay-katherine/",
        "image": "https://sencanada.ca/media/e3epefrj/sen_pho_hay_official.jpg?center=0.39190610754728655,0.4517047081202934&mode=crop&width=95&height=100&rnd=133953399104430000&quality=95",
        "alt": "Hay, Katherine",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Todd Lewis",
        "href": "/en/senators/lewis-todd/",
        "image": "https://sencanada.ca/media/maonrkw1/sen_pho_lewis_official.jpg?center=0.40019123507802212,0.48178051078408923&mode=crop&width=95&height=100&rnd=133953399106800000&quality=95",
        "alt": "Lewis, Todd",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Fabian Manning",
        "href": "/en/senators/manning-fabian/",
        "image": "https://sencanada.ca/media/psrfhiws/sen_pho_manning_official_2024.jpg?center=0.38453945139038265,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953399107400000&quality=95",
        "alt": "Manning, Fabian",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Julie Miville-Dech\u00eane",
        "href": "/en/senators/miville-dechene-julie/",
        "image": "https://sencanada.ca/media/wlhl22jx/sen_pho_miville-dechene_official_2024.jpg?center=0.36237063010296866,0.51225218914900916&mode=crop&width=95&height=100&rnd=133953399109430000&quality=95",
        "alt": "Miville-Dech\u00eane, Julie",
        "affiliation": "ISG - (Quebec - Inkerman)"
      },
      {
        "name": "Jim Quinn",
        "href": "/en/senators/quinn-jim/",
        "image": "https://sencanada.ca/media/2fck44iv/sen_pho_quinn_official_2024.jpg?center=0.3761829540974953,0.45737545742969926&mode=crop&width=95&height=100&rnd=133953399112270000&quality=95",
        "alt": "Quinn, Jim",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Paula Simons",
        "href": "/en/senators/simons-paula/",
        "image": "https://sencanada.ca/media/tffoquhj/sen_pho_simons_official_2024.jpg?center=0.41637698842054377,0.55565128069187186&mode=crop&width=95&height=100&rnd=133953399114600000&quality=95",
        "alt": "Simons, Paula",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Pamela Wallin",
        "href": "/en/senators/wallin-pamela/",
        "image": "https://sencanada.ca/media/h5ebetkz/sen_pho_wallin_official_2024.jpg?center=0.40958608232385585,0.52804916583076555&mode=crop&width=95&height=100&rnd=133953399115830000&quality=95",
        "alt": "Wallin, Pamela",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Duncan Wilson",
        "href": "/en/senators/wilson-duncan/",
        "image": "https://sencanada.ca/media/4eminkuz/sen_pho_wilson_official.jpg?center=0.38114382711465239,0.51143022064049992&mode=crop&width=95&height=100&rnd=133953399116470000&quality=95",
        "alt": "Wilson, Duncan",
        "affiliation": "PSG - (British Columbia)"
      },
      {
        "name": "Dawn Arnold",
        "href": "/en/senators/arnold-dawn/",
        "image": "https://sencanada.ca/media/4n5pq0zd/sen_pho_arnold_official.jpg?center=0.41105941355523662,0.52168712768822623&mode=crop&width=95&height=100&rnd=133953399095530000&quality=95",
        "alt": "Arnold, Dawn",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Ren\u00e9 Cormier",
        "href": "/en/senators/cormier-rene/",
        "image": "https://sencanada.ca/media/bsgbexch/sen_pho_cormier_official_2024.jpg?center=0.375393019937317,0.50202389129278346&mode=crop&width=95&height=100&rnd=133953399099130000&quality=95",
        "alt": "Cormier, Ren\u00e9",
        "affiliation": "ISG - (New Brunswick)"
      },
      {
        "name": "Tony Dean",
        "href": "/en/senators/dean-tony/",
        "image": "https://sencanada.ca/media/udqfumdz/sen_pho_dean_official_2024.jpg?center=0.33999338639432342,0.47960414887524228&mode=crop&width=95&height=100&rnd=133953399100830000&quality=95",
        "alt": "Dean, Tony",
        "affiliation": "ISG - (Ontario)"
      },
      {
        "name": "Katherine Hay",
        "href": "/en/senators/hay-katherine/",
        "image": "https://sencanada.ca/media/e3epefrj/sen_pho_hay_official.jpg?center=0.39190610754728655,0.4517047081202934&mode=crop&width=95&height=100&rnd=133953399104430000&quality=95",
        "alt": "Hay, Katherine",
        "affiliation": "PSG - (Ontario)"
      },
      {
        "name": "Todd Lewis",
        "href": "/en/senators/lewis-todd/",
        "image": "https://sencanada.ca/media/maonrkw1/sen_pho_lewis_official.jpg?center=0.40019123507802212,0.48178051078408923&mode=crop&width=95&height=100&rnd=133953399106800000&quality=95",
        "alt": "Lewis, Todd",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Fabian Manning",
        "href": "/en/senators/manning-fabian/",
        "image": "https://sencanada.ca/media/psrfhiws/sen_pho_manning_official_2024.jpg?center=0.38453945139038265,0.4601874256436792&mode=crop&width=95&height=100&rnd=133953399107400000&quality=95",
        "alt": "Manning, Fabian",
        "affiliation": "C - (Newfoundland and Labrador)"
      },
      {
        "name": "Julie Miville-Dech\u00eane",
        "href": "/en/senators/miville-dechene-julie/",
        "image": "https://sencanada.ca/media/wlhl22jx/sen_pho_miville-dechene_official_2024.jpg?center=0.36237063010296866,0.51225218914900916&mode=crop&width=95&height=100&rnd=133953399109430000&quality=95",
        "alt": "Miville-Dech\u00eane, Julie",
        "affiliation": "ISG - (Quebec - Inkerman)"
      },
      {
        "name": "Jim Quinn",
        "href": "/en/senators/quinn-jim/",
        "image": "https://sencanada.ca/media/2fck44iv/sen_pho_quinn_official_2024.jpg?center=0.3761829540974953,0.45737545742969926&mode=crop&width=95&height=100&rnd=133953399112270000&quality=95",
        "alt": "Quinn, Jim",
        "affiliation": "CSG - (New Brunswick)"
      },
      {
        "name": "Paula Simons",
        "href": "/en/senators/simons-paula/",
        "image": "https://sencanada.ca/media/tffoquhj/sen_pho_simons_official_2024.jpg?center=0.41637698842054377,0.55565128069187186&mode=crop&width=95&height=100&rnd=133953399114600000&quality=95",
        "alt": "Simons, Paula",
        "affiliation": "ISG - (Alberta)"
      },
      {
        "name": "Pamela Wallin",
        "href": "/en/senators/wallin-pamela/",
        "image": "https://sencanada.ca/media/h5ebetkz/sen_pho_wallin_official_2024.jpg?center=0.40958608232385585,0.52804916583076555&mode=crop&width=95&height=100&rnd=133953399115830000&quality=95",
        "alt": "Wallin, Pamela",
        "affiliation": "CSG - (Saskatchewan)"
      },
      {
        "name": "Duncan Wilson",
        "href": "/en/senators/wilson-duncan/",
        "image": "https://sencanada.ca/media/4eminkuz/sen_pho_wilson_official.jpg?center=0.38114382711465239,0.51143022064049992&mode=crop&width=95&height=100&rnd=133953399116470000&quality=95",
        "alt": "Wilson, Duncan",
        "affiliation": "PSG - (British Columbia)"
      }
    ]
  }
],
  "sub_committees": [
    {
      "href": "/en/committees/hrrh/45-1",
      "acronym": "HRRH",
      "name_full": "Subcommittee on Human Resources (CIBA)",
      "name_short": "Human Resources"
    },
    {
      "href": "/en/committees/ltvp/45-1",
      "acronym": "LTVP",
      "name_full": "Subcommittee on Long Term Vision and Plan (CIBA)",
      "name_short": "Long Term Vision and Plan"
    },
    {
      "href": "/en/committees/sebs/45-1",
      "acronym": "SEBS",
      "name_full": "Subcommittee on Senate Estimates and Committee Budgets (CIBA)",
      "name_short": "Estimates and Budgets"
    },
    {
      "href": "/en/committees/veac/45-1",
      "acronym": "VEAC",
      "name_full": "Subcommittee on Veterans Affairs (SECD)",
      "name_short": "Veterans Affairs"
    }
  ],
  "joint_committees": [
    {
      "href": "/en/committees/bili/45-1",
      "acronym": "BILI",
      "name_full": "Library of Parliament (Joint)",
      "name_short": "Library"
    },
    {
      "href": "/en/committees/regs/45-1",
      "acronym": "REGS",
      "name_full": "Scrutiny of Regulations (Joint)",
      "name_short": "Regulations"
    }
  ]
}
# Route to serve the hardcoded JSON
@app.route("/committees", methods=["GET"])
def get_committees():
    return jsonify(committees_data)
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
        # ✅ Explicitly set binary location (for Render/Headless Chromium)
        chrome_options.binary_location = "/usr/bin/chromium-browser"
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # ✅ Use ChromeDriverManager to auto-install compatible driver
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
                savetocal = (
                    savetocal_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href")
                    if savetocal_elems else ""
                )

                twitter_elems = item.find_elements(By.CLASS_NAME, "event-item-social-twitter")
                twitter = (
                    twitter_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href")
                    if twitter_elems else ""
                )
                facebook_elems = item.find_elements(By.CLASS_NAME, "event-item-social-facebook")
                facebook = (
                    facebook_elems[0].find_element(By.TAG_NAME, "a").get_attribute("href")
                    if facebook_elems else ""
                )

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
from concurrent.futures import ThreadPoolExecutor, as_completed
def fetch_senate_orders(limit: int = 30):
    """Fast scrape of Senate order papers with structured content extraction."""
    base = "https://sencanada.ca"
    cal_url = f"{base}/en/in-the-chamber/order-papers-notice-papers/"

    try:
        cal_html = requests.get(cal_url, headers=HEADERS, timeout=10).text
    except Exception as e:
        return {"error": f"Failed to load calendar page: {e}"}

    soup = BeautifulSoup(cal_html, "html.parser")
    links = [
        a["href"].replace("\\", "/")
        for a in soup.select("table.sc-in-the-chamber-calendar-table a[href]")
    ][:limit]

    urls = [link if link.startswith("http") else base + link for link in links]
    seen = set()
    unique_urls = [url for url in urls if url not in seen and not seen.add(url)]

    def fetch_page(url):
        try:
            html = requests.get(url, headers=HEADERS, timeout=10).text
            page_soup = BeautifulSoup(html, "html.parser")
            main = page_soup.select_one("main")
            detail = main.get_text(strip=True, separator="\n") if main else "No content available."
            return {
                "title": url.split("/")[-1],
                "link": url,
                "detail": detail[:10000] 
            }
        except Exception:
            return None

    records = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_page, url): url for url in unique_urls}
        for future in as_completed(futures):
            result = future.result()
            if result:
                records.append(result)
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

import requests
from bs4 import BeautifulSoup

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
