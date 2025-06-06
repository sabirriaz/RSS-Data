
Conversation opened. 1 unread message.

Skip to content
Using Gmail with screen readers

1 of 907
(no subject)
Inbox

Ghulam Jillani <ghulamjillani216@gmail.com>
Attachments
11:48 PM (2 minutes ago)
to me


 One attachment
  •  Scanned by Gmail
from flask import Flask, jsonify, request
from flask_cors import CORS
import feedparser
import requests
from bs4 import BeautifulSoup
import os
import xml.etree.ElementTree as ET
import re
import json
from datetime import datetime

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

def fetch_senators():
    """Fetch senators information - ENHANCED with better scraping"""
    try:
        url = 'https://sencanada.ca/en/senators/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            senators = []
            
            senator_links = soup.find_all('a', href=True)
            for link in senator_links:
                href = link.get('href', '')
                if '/senators/' in href and href.count('/') >= 4:
                    name = link.get_text(strip=True)
                    if name and len(name) > 2:  # Basic validation
                        senators.append({
                            'name': name,
                            'profile_url': f"https://sencanada.ca{href}" if href.startswith('/') else href,
                            'party': 'Unknown', 
                            'division': 'Unknown'
                        })
            
            # Remove duplicates based on name
            seen_names = set()
            unique_senators = []
            for senator in senators:
                if senator['name'] not in seen_names:
                    seen_names.add(senator['name'])
                    unique_senators.append(senator)
            
            return {
                'total_count': len(unique_senators),
                'senators': unique_senators[:50] 
            }
        
        return {'error': f'Failed to fetch senators - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch senators: {str(e)}'}

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
            
            # Look for committee links
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
    """Fetch judicial appointments from Justice Canada RSS - ENHANCED"""
    try:
        feed = feedparser.parse('https://www.justice.gc.ca/eng/news-nouv/rss.html')
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
    """Fetch House of Commons committees from OpenParliament API - CORRECTED"""
    try:
        url = 'https://api.openparliament.ca/committees/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            committees = []
            
            for committee in data.get('objects', []):
                committees.append({
                    'name': committee.get('name', {}),
                    'short_name': committee.get('short_name', {}),
                    'slug': committee.get('slug', ''),
                    'url': f"https://openparliament.ca{committee.get('url', '')}" if committee.get('url') else '',
                    'parent_url': committee.get('parent_url')
                })
            
            return {
                'total_count': len(committees),
                'committees': committees,
                'pagination': data.get('pagination', {})
            }
        
        return {'error': f'Failed to fetch committees - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch committees: {str(e)}'}

def fetch_canada_gazette():
    """Fetch Canada Gazette publications - ENHANCED"""
    try:
        url = 'https://canadagazette.gc.ca/partI/latest/latest-eng.html'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            publications = []
            
            links = soup.find_all('a', href=True)
            for link in links:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                if 'pdf' in href.lower() and text:
                    publications.append({
                        'title': text,
                        'url': href if href.startswith('http') else f"https://canadagazette.gc.ca{href}",
                        'type': 'PDF',
                        'publication': 'Canada Gazette Part I'
                    })
            
            return {
                'total_count': len(publications),
                'publications': publications[:20] 
            }
            
        return {'error': f'Failed to fetch Canada Gazette - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch Canada Gazette: {str(e)}'}

def fetch_debates(date=None):
    """
    Fetches parliamentary debates from the OpenParliament API.
    This function has been corrected to use the date filter query parameter.
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
            return {'error': f'No debates found for the specified date or general endpoint not found.'}
        else:
            return {'error': f'Failed to fetch debates - Status: {response.status_code}'}
    except requests.exceptions.Timeout:
        return {'error': 'Failed to fetch debates: Request timed out.'}
    except requests.exceptions.RequestException as e:
        return {'error': f'Failed to fetch debates: {str(e)}'}
    except Exception as e:
        return {'error': f'An unexpected error occurred while fetching debates: {str(e)}'}

def fetch_legal_info(query=""):
    """Fetch legal information from CanLII API"""
    try:
        api_key = os.environ.get('CANLII_API_KEY')
        if not api_key:
            return {'error': 'CANLII_API_KEY environment variable not set'}
        
        if not query:
            query = "federal"  # Default query
            
        url = f'https://api.canlii.org/v1/search/?q={query}&api_key={api_key}'
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        return {'error': f'Failed to fetch legal info - Status: {response.status_code}'}
    except Exception as e:
        return {'error': f'Failed to fetch legal info: {str(e)}'}

def fetch_access_information():
    """Static information about Access to Information"""
    return {
        'message': 'Access to Information and Privacy',
        'description': 'Information about how to access government information and protect privacy',
        'url': 'https://www.canada.ca/en/treasury-board-secretariat/services/access-information-privacy.html',
        'contact': 'Contact the relevant department directly for specific requests'
    }

@app.route('/pm_updates', methods=['GET'])
def pm_updates_route():
    return jsonify(fetch_pm_updates())

@app.route('/bills', methods=['GET'])
def bills_route():
    return jsonify(fetch_bills())

@app.route('/mps', methods=['GET'])
def mps_route():
    return jsonify(fetch_mps())

@app.route('/senators', methods=['GET'])
def senators_route():
    return jsonify(fetch_senators())

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

@app.route('/committees', methods=['GET'])
def committees_route():
    return jsonify(fetch_committees())

@app.route('/canada_gazette', methods=['GET'])
def canada_gazette_route():
    return jsonify(fetch_canada_gazette())

@app.route('/debates', methods=['GET'])
def debates_route():
    """
    Endpoint for parliamentary debates.
    Accepts an optional 'date' query parameter (YYYY-MM-DD).
    """
    date = request.args.get('date')
    return jsonify(fetch_debates(date))

@app.route('/legal_info', methods=['GET'])
def legal_info_route():
    query = request.args.get('query', '')
    return jsonify(fetch_legal_info(query))

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
            '/access_information'
        ]
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
app.py
Displaying app.py.
