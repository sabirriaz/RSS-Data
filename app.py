from flask import Flask, jsonify, request
from flask_cors import CORS
import feedparser
import requests
from bs4 import BeautifulSoup
import os
import xml.etree.ElementTree as ET
import re

app = Flask(__name__)
CORS(app, origins=['https://ifj.academiapro.uk'])

def is_valid_date(date_str):
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    return bool(re.match(pattern, date_str))

def fetch_pm_updates():
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

def fetch_judicial_appointments():
    try:
        feed = feedparser.parse('https://www.justice.gc.ca/eng/news-nouv/rss.html')
        appointments = []
        for entry in feed.entries:
            appointments.append({
                'title': entry.title,
                'summary': entry.summary,
                'link': entry.link
            })
        return appointments
    except Exception as e:
        return {'error': f'Failed to fetch judicial appointments: {str(e)}'}

def fetch_global_affairs():
    try:
        feed = feedparser.parse('https://www.international.gc.ca/global-affairs-affaires-mondiales/news-nouvelles/rss.aspx?lang=eng')
        news = []
        for entry in feed.entries:
            news.append({
                'title': entry.title,
                'summary': entry.summary,
                'link': entry.link
            })
        return news
    except Exception as e:
        return {'error': f'Failed to fetch global affairs: {str(e)}'}

def fetch_news_aggregator():
    try:
        url = 'https://www.villagereport.ca/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            articles = []
            for item in soup.find_all('div', class_='article'):
                title = item.find('h2').text.strip() if item.find('h2') else ''
                link = item.find('a')['href'] if item.find('a') else ''
                articles.append({
                    'title': title,
                    'link': link
                })
            return articles
        return {'error': 'Failed to fetch news aggregator'}
    except Exception as e:
        return {'error': f'Failed to fetch news aggregator: {str(e)}'}

def fetch_senators():
    try:
        url = 'https://sencanada.ca/en/senators/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            senators = []
            for item in soup.find_all('div', class_='senator-item'):
                name = item.find('h3').text.strip() if item.find('h3') else ''
                party = item.find('span', class_='party').text.strip() if item.find('span', class_='party') else ''
                division = item.find('span', class_='division').text.strip() if item.find('span', class_='division') else ''
                senators.append({
                    'name': name,
                    'party': party,
                    'division': division
                })
            return senators
        return {'error': 'Failed to fetch senators'}
    except Exception as e:
        return {'error': f'Failed to fetch senators: {str(e)}'}

def fetch_legal_info(query=""):
    try:
        api_key = os.environ.get('CANLII_API_KEY')
        if not api_key:
            return {'error': 'CANLII_API_KEY not set'}
        url = f'https://api.canlii.org/v1/search/?q={query}&api_key={api_key}'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return {'error': 'Failed to fetch legal info'}
    except Exception as e:
        return {'error': f'Failed to fetch legal info: {str(e)}'}

def fetch_bills():
    try:
        url = 'https://www.parl.ca/legisinfo/en/bills/json'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return {'error': 'Failed to fetch bills'}
    except Exception as e:
        return {'error': f'Failed to fetch bills: {str(e)}'}

def fetch_debates(date):
    try:
        if not is_valid_date(date):
            return {'error': 'Invalid date format. Use YYYY-MM-DD'}
        url = f'https://api.openparliament.ca/debates/{date}/'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return {'error': f'Failed to fetch debates for {date}'}
    except Exception as e:
        return {'error': f'Failed to fetch debates: {str(e)}'}

def fetch_mps():
    try:
        url = 'https://represent.opennorth.ca/api/representatives/?elected_office=MP'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return {'error': 'Failed to fetch MPs'}
    except Exception as e:
        return {'error': f'Failed to fetch MPs: {str(e)}'}

def fetch_federal_contracts():
    try:
        dataset_id = 'dbf85d91-7dec-4fd1-8055-83b77225db'
        url = f'https://open.canada.ca/api/3/action/package_show?id={dataset_id}'
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        return {'error': 'Failed to fetch federal contracts'}
    except Exception as e:
        return {'error': f'Failed to fetch federal contracts: {str(e)}'}

def fetch_senate_calendar():
    try:
        url = 'https://sencanada.ca/en/calendar/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            calendar_events = []
            for event in soup.find_all('div', class_='event'):
                calendar_events.append({
                    'date': event.find('span', class_='date').text.strip() if event.find('span', class_='date') else '',
                    'title': event.find('span', class_='title').text.strip() if event.find('span', class_='title') else ''
                })
            return calendar_events
        return {'error': 'Failed to fetch senate calendar'}
    except Exception as e:
        return {'error': f'Failed to fetch senate calendar: {str(e)}'}

def fetch_canada_gazette():
    try:
        url = 'https://canadagazette.gc.ca/partI/latest/latest-eng.html'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            publications = []
            for item in soup.find_all('a', href=True):
                if 'pdf' in item['href']:
                    publications.append({'url': item['href'], 'title': item.text.strip()})
            return publications
        return {'error': 'Failed to fetch Canada Gazette'}
    except Exception as e:
        return {'error': f'Failed to fetch Canada Gazette: {str(e)}'}

def fetch_order_papers():
    try:
        url = 'https://sencanada.ca/en/in-the-chamber/order-papers-notice-papers/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            papers = []
            for link in soup.find_all('a', href=True):
                if 'pdf' in link['href']:
                    papers.append({'url': link['href'], 'title': link.text.strip()})
            return papers
        return {'error': 'Failed to fetch order papers'}
    except Exception as e:
        return {'error': f'Failed to fetch order papers: {str(e)}'}

def fetch_federal_procurement():
    try:
        url = 'https://canadabuys.canada.ca/en/tender-opportunities'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            tenders = []
            for item in soup.find_all('div', class_='tender'):
                tenders.append({
                    'title': item.find('h3').text.strip() if item.find('h3') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return tenders
        return {'error': 'Failed to fetch federal procurement'}
    except Exception as e:
        return {'error': f'Failed to fetch federal procurement: {str(e)}'}

def fetch_bc_procurement():
    try:
        url = 'https://bcbid.gov.bc.ca/page.aspx?fr=request_browse_public'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            tenders = []
            for item in soup.find_all('div', class_='tender'):
                tenders.append({
                    'title': item.find('a').text.strip() if item.find('a') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return tenders
        return {'error': 'Failed to fetch BC procurement'}
    except Exception as e:
        return {'error': f'Failed to fetch BC procurement: {str(e)}'}

def fetch_municipal_councillors():
    try:
        url = 'https://portal.fcm.ca/our-members/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            councillors = []
            for item in soup.find_all('div', class_='councillor'):
                councillors.append({
                    'name': item.find('span', class_='name').text.strip() if item.find('span', class_='name') else '',
                    'municipality': item.find('span', class_='municipality').text.strip() if item.find('span', class_='municipality') else ''
                })
            return councillors
        return {'error': 'Failed to fetch municipal councillors'}
    except Exception as e:
        return {'error': f'Failed to fetch municipal councillors: {str(e)}'}

def fetch_senate_committees():
    try:
        url = 'https://sencanada.ca/en/committees/'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            committees = []
            for item in soup.find_all('div', class_='committee'):
                committees.append({
                    'name': item.find('a').text.strip() if item.find('a') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return committees
        return {'error': 'Failed to fetch senate committees'}
    except Exception as e:
        return {'error': f'Failed to fetch senate committees: {str(e)}'}

def fetch_victoria_procurement():
    try:
        url = 'https://victoria.bonfirehub.ca/portal/?tab=openOpportunities'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            opportunities = []
            for item in soup.find_all('div', class_='opportunity'):
                opportunities.append({
                    'title': item.find('a').text.strip() if item.find('a') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return opportunities
        return {'error': 'Failed to fetch Victoria procurement'}
    except Exception as e:
        return {'error': f'Failed to fetch Victoria procurement: {str(e)}'}

def fetch_access_information():
    return {'message': 'This is a static page: https://www.canada.ca/en/treasury-board-secretariat/services/access-information-privacy.html'}

def fetch_publications():
    try:
        url = 'https://www.ourcommons.ca/publicationsearch/en/?PubType=37'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            publications = []
            for item in soup.find_all('div', class_='publication'):
                publications.append({
                    'title': item.find('h3').text.strip() if item.find('h3') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return publications
        return {'error': 'Failed to fetch publications'}
    except Exception as e:
        return {'error': f'Failed to fetch publications: {str(e)}'}

def fetch_committees():
    try:
        url = 'https://www.ourcommons.ca/Committees/en/Home'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            committees = []
            for item in soup.find_all('div', class_='committee'):
                committees.append({
                    'name': item.find('a').text.strip() if item.find('a') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return committees
        return {'error': 'Failed to fetch committees'}
    except Exception as e:
        return {'error': f'Failed to fetch committees: {str(e)}'}

def fetch_work_reports():
    try:
        url = 'https://www.ourcommons.ca/Committees/en/Work'
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            reports = []
            for item in soup.find_all('div', class_='report'):
                reports.append({
                    'title': item.find('h3').text.strip() if item.find('h3') else '',
                    'link': item.find('a')['href'] if item.find('a') else ''
                })
            return reports
        return {'error': 'Failed to fetch work reports'}
    except Exception as e:
        return {'error': f'Failed to fetch work reports: {str(e)}'}

@app.route('/pm_updates', methods=['GET'])
def pm_updates_route():
    return jsonify(fetch_pm_updates())

@app.route('/judicial_appointments', methods=['GET'])
def judicial_appointments_route():
    return jsonify(fetch_judicial_appointments())

@app.route('/global_affairs', methods=['GET'])
def global_affairs_route():
    return jsonify(fetch_global_affairs())

@app.route('/news_aggregator', methods=['GET'])
def news_aggregator_route():
    return jsonify(fetch_news_aggregator())

@app.route('/senators', methods=['GET'])
def senators_route():
    return jsonify(fetch_senators())

@app.route('/legal_info', methods=['GET'])
def legal_info_route():
    query = request.args.get('query', '')
    return jsonify(fetch_legal_info(query))

@app.route('/bills', methods=['GET'])
def bills_route():
    return jsonify(fetch_bills())

@app.route('/debates/<date>', methods=['GET'])
def debates_route(date):
    return jsonify(fetch_debates(date))

@app.route('/mps', methods=['GET'])
def mps_route():
    return jsonify(fetch_mps())

@app.route('/federal_procurement', methods=['GET'])
def federal_procurement_route():
    return jsonify(fetch_federal_procurement())

@app.route('/federal_contracts', methods=['GET'])
def federal_contracts_route():
    return jsonify(fetch_federal_contracts())

@app.route('/publications', methods=['GET'])
def publications_route():
    return jsonify(fetch_publications())

@app.route('/committees', methods=['GET'])
def committees_route():
    return jsonify(fetch_committees())

@app.route('/work_reports', methods=['GET'])
def work_reports_route():
    return jsonify(fetch_work_reports())

@app.route('/access_information', methods=['GET'])
def access_information_route():
    return jsonify(fetch_access_information())

@app.route('/senate_calendar', methods=['GET'])
def senate_calendar_route():
    return jsonify(fetch_senate_calendar())

@app.route('/canada_gazette', methods=['GET'])
def canada_gazette_route():
    return jsonify(fetch_canada_gazette())

@app.route('/order_papers', methods=['GET'])
def order_papers_route():
    return jsonify(fetch_order_papers())

@app.route('/bc_procurement', methods=['GET'])
def bc_procurement_route():
    return jsonify(fetch_bc_procurement())

@app.route('/municipal_councillors', methods=['GET'])
def municipal_councillors_route():
    return jsonify(fetch_municipal_councillors())

@app.route('/senate_committees', methods=['GET'])
def senate_committees_route():
    return jsonify(fetch_senate_committees())

@app.route('/victoria_procurement', methods=['GET'])
def victoria_procurement_route():
    return jsonify(fetch_victoria_procurement())

application = app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
