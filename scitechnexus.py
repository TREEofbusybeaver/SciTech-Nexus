# app.py - Main Flask Application
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import json
from urllib.parse import urljoin
import time
import threading  # For potential background tasks later
from transformers import pipeline
from dateutil import parser as date_parser  # For robust date parsing
import warnings

warnings.filterwarnings("ignore")  # Consider being more specific with warnings if possible

app = Flask(__name__)

# --- Configuration ---
DATABASE_NAME = 'news_aggregator.db'

# Initialize AI summarizer
try:
    summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6", device=-1)  # device=-1 for CPU
    print("AI summarizer loaded successfully.")
except Exception as e:
    summarizer = None
    print(f"Warning: AI summarizer could not be loaded: {e}")

# News sources configuration with RSS/API focus
NEWS_SOURCES_CONFIG = {
    'ScienceDaily': {
        'url': 'https://www.sciencedaily.com/rss/top/science.xml',  # General Science RSS
        'type': 'rss',
        'base_url': 'https://www.sciencedaily.com/'
    },
    'Phys.org': {
        'url': 'https://phys.org/rss-feed/technology-news/',
        'type': 'rss',
        'base_url': 'https://phys.org/'
    },
    'New Atlas': {
        'url': 'https://newatlas.com/index.rss',
        'type': 'rss',
        'base_url': 'https://newatlas.com/'
    },
    'Nature': {
        'url': 'https://www.nature.com/nature/rss/news.xml',
        'type': 'rss',
        'base_url': 'https://www.nature.com/'
    },
    'Science Magazine': {
        'url': 'https://www.science.org/rss/news_current.xml',
        'type': 'rss',
        'base_url': 'https://www.science.org/'
    },
    'arXiv (AI)': {
        'url': 'http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10',
        'type': 'arxiv',  # Uses Atom feed, similar to RSS
        'base_url': 'https://arxiv.org/'
    },
    'arXiv (Quantum)': {
        'url': 'http://export.arxiv.org/api/query?search_query=cat:quant-ph&sortBy=submittedDate&sortOrder=descending&max_results=10',
        'type': 'arxiv',
        'base_url': 'https://arxiv.org/'
    }
}

CATEGORIES_KEYWORDS = {  # Renamed from CATEGORIES for clarity
    'AI': ['artificial intelligence', 'machine learning', 'deep learning', 'neural network',
           'computer vision', 'natural language processing', 'nlp', 'ai', 'gpt', 'llm'],
    'Quantum Computing': ['quantum computer', 'quantum mechanics', 'superposition',
                          'entanglement', 'quantum', 'qubit', 'quantum algorithm', 'quantum supremacy'],
    'Deep Tech': ['blockchain', 'cryptocurrency', 'robotics', 'automation', 'iot',
                  'internet of things', 'nanotechnology', 'fusion energy', 'advanced materials'],
    'Computer Science': ['programming', 'software', 'computing', 'database', 'cybersecurity',
                         'algorithm', 'data structure', 'computer architecture', 'operating system'],
    'Astrophysics': ['space', 'astronomy', 'cosmology', 'black hole', 'galaxy', 'universe',
                     'telescope', 'planet', 'star', 'exoplanet', 'dark matter', 'dark energy'],
    'Quantum Science': ['quantum physics', 'particle physics', 'quantum field theory',
                        'string theory', 'standard model', 'quantum optics'],
    'Neuroscience': ['brain', 'neuron', 'cognitive science', 'neurobiology', 'consciousness', 'memory', 'synapse'],
    'Biotechnology': ['biotech', 'genetics', 'dna', 'rna', 'protein engineering', 'gene therapy', 'crispr',
                      'synthetic biology', 'bioinformatics', 'pharmaceuticals'],
    'Materials Science': ['new materials', 'nanomaterials', 'graphene', 'polymer', 'ceramics',
                          'semiconductor', 'superconductor', 'biomaterials', 'metamaterials']
}


# --- Database Manager ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_summary TEXT,
            ai_summary TEXT,
            link TEXT UNIQUE NOT NULL,
            publication_date DATETIME NOT NULL,
            source TEXT NOT NULL,
            categories TEXT,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# --- News Aggregation Logic ---
class NewsAggregator:
    def __init__(self):
        pass

    def _parse_datetime(self, date_string):
        if not date_string:
            return datetime.now()
        try:
            return date_parser.parse(date_string)
        except Exception as e:
            print(f"Could not parse date: {date_string} - Error: {e}")
            return datetime.now()

    def categorize_article(self, title, summary):
        text_to_search = (title + " " + (summary or "")).lower()
        found_categories = []
        for category, keywords in CATEGORIES_KEYWORDS.items():
            if any(keyword.lower() in text_to_search for keyword in keywords):
                found_categories.append(category)
        return found_categories if found_categories else ['General Tech']

    def summarize_text_ai(self, text_to_summarize):
        if not summarizer or not text_to_summarize or len(text_to_summarize.split()) < 50:
            return text_to_summarize
        try:
            max_chars = 4000
            summary_output = summarizer(text_to_summarize[:max_chars], max_length=150, min_length=40, do_sample=False)
            return summary_output[0]['summary_text']
        except Exception as e:
            print(f"AI Summarization error: {e}")
            return text_to_summarize

    def _fetch_and_parse_feed(self, source_name, config):
        articles = []
        print(f"Fetching {source_name} from {config['url']}...")
        try:
            headers = {'User-Agent': 'SciTechNewsAggregator/1.0'}
            response = requests.get(config['url'], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            items = soup.find_all('item') if config['type'] == 'rss' else soup.find_all('entry')

            for item in items[:15]:
                try:
                    title = item.find('title').get_text(strip=True) if item.find('title') else 'No Title'
                    link_tag = item.find('link')
                    link = link_tag['href'] if link_tag and link_tag.has_attr('href') else (
                        link_tag.get_text(strip=True) if link_tag else '')
                    if not link.startswith('http'):
                        link = urljoin(config['base_url'], link)
                    summary_tag = item.find('description') or item.find('summary')
                    original_summary = BeautifulSoup(summary_tag.get_text(strip=True),
                                                     "html.parser").get_text() if summary_tag else title
                    pub_date_str = (item.find('pubDate') or item.find('published') or item.find('updated')).get_text(
                        strip=True)
                    publication_date = self._parse_datetime(pub_date_str)
                    articles.append({'title': title, 'original_summary': original_summary, 'link': link,
                                     'publication_date': publication_date, 'source': source_name})
                except Exception as e:
                    print(
                        f"Error parsing item from {source_name}: {e}. Item: {item.title.get_text(strip=True) if item.title else 'Unknown'}")
                    continue
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {source_name}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred with {source_name}: {e}")
        return articles

    def scrape_all_sources(self):
        print("Starting scrape_all_sources...")
        processed_articles_count = 0
        conn = get_db_connection()
        cursor = conn.cursor()
        for source_name, config in NEWS_SOURCES_CONFIG.items():
            scraped_articles = self._fetch_and_parse_feed(source_name, config)
            for article_data in scraped_articles:
                try:
                    cursor.execute("SELECT id FROM articles WHERE link = ?", (article_data['link'],))
                    if cursor.fetchone():
                        continue
                    categories = self.categorize_article(article_data['title'], article_data['original_summary'])
                    ai_summary = self.summarize_text_ai(article_data['original_summary'])
                    cursor.execute('''
                        INSERT INTO articles (title, original_summary, ai_summary, link, publication_date, source, categories)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (article_data['title'], article_data['original_summary'], ai_summary, article_data['link'],
                          article_data['publication_date'].isoformat(), article_data['source'], json.dumps(categories)))
                    processed_articles_count += 1
                except Exception as e:
                    print(f"Error storing article '{article_data.get('title', 'Unknown')}': {e}")
            conn.commit()
            time.sleep(1)
        conn.close()
        print(f"Scraping finished. Processed {processed_articles_count} new articles.")
        return processed_articles_count

    # --- THIS IS WHERE THE INDENTATION WAS FIXED ---
    def get_articles_by_filter(self, date_str=None, category=None, year=None, limit=None):
        conn = get_db_connection()
        cursor = conn.cursor()
        base_query = "FROM articles"
        conditions, params = [], []
        if date_str:
            conditions.append("DATE(publication_date) = ?")
            params.append(date_str)
        if category:
            conditions.append("categories LIKE ?")
            params.append(f'%"{category}"%')
        if year:
            conditions.append("STRFTIME('%Y', publication_date) = ?")
            params.append(str(year))

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        count_query = "SELECT COUNT(*) as total_count " + base_query + where_clause
        cursor.execute(count_query, tuple(params))
        total_count = cursor.fetchone()['total_count']

        articles_query = "SELECT title, original_summary, ai_summary, link, publication_date, source, categories, scraped_at " + base_query + where_clause
        articles_query += " ORDER BY publication_date DESC, scraped_at DESC"

        if limit is not None:
            articles_query += " LIMIT ?"
            params.append(limit)

        cursor.execute(articles_query, tuple(params))
        articles_result = [{'title': row['title'],
                            'summary': row['ai_summary'] if row['ai_summary'] and len(row['ai_summary']) > 20 else row[
                                'original_summary'], 'link': row['link'],
                            'publication_date': date_parser.parse(row['publication_date']).strftime('%Y-%m-%d %H:%M'),
                            'source': row['source'],
                            'categories': json.loads(row['categories']) if row['categories'] else [],
                            'scraped_at': row['scraped_at']} for row in cursor.fetchall()]
        conn.close()
        return articles_result, total_count

    def get_available_dates(self, limit=15):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT DATE(publication_date) as article_date, COUNT(*) as count
            FROM articles
            GROUP BY article_date
            ORDER BY article_date DESC
            LIMIT ?
        ''', (limit,))
        dates_result = [{'date': row['article_date'], 'count': row['count']} for row in cursor.fetchall()]
        conn.close()
        return dates_result


# --- Global Initialization ---
init_database()
news_aggregator = NewsAggregator()


@app.context_processor
def inject_global_vars():
    return {'all_categories_list': list(CATEGORIES_KEYWORDS.keys()), 'current_year_for_link': datetime.now().year}


# --- Flask Routes ---
@app.route('/')
def index():
    today_str = datetime.now().strftime('%Y-%m-%d')
    articles, total_count = news_aggregator.get_articles_by_filter(date_str=today_str, limit=20)
    available_dates = news_aggregator.get_available_dates()
    return render_template('index.html', articles=articles, total_articles_count=total_count,
                           current_display_date=today_str, available_dates=available_dates)


@app.route('/date/<date_str>')
def articles_by_date_route(date_str):
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return "Invalid date format. Please use YYYY-MM-DD.", 400
    articles, total_count = news_aggregator.get_articles_by_filter(date_str=date_str)
    available_dates = news_aggregator.get_available_dates()
    return render_template('index.html', articles=articles, total_articles_count=total_count,
                           current_display_date=date_str, available_dates=available_dates)


@app.route('/category/<category_name>')
def articles_by_category_route(category_name):
    if category_name not in CATEGORIES_KEYWORDS:
        return "Invalid category.", 404
    articles, total_count = news_aggregator.get_articles_by_filter(category=category_name)
    available_dates = news_aggregator.get_available_dates()
    return render_template('category.html', articles=articles, total_articles_count=total_count,
                           category_title=category_name, available_dates=available_dates)


@app.route('/yearly/<int:year_num>')
def yearly_breakthroughs_route(year_num):
    articles, total_count = news_aggregator.get_articles_by_filter(year=year_num)
    available_dates = news_aggregator.get_available_dates()
    return render_template('yearly.html', articles=articles, total_articles_count=total_count, year_title=year_num,
                           available_dates=available_dates)


# --- Update Mechanism ---
scraping_lock = threading.Lock()


def background_scraper_task():
    if scraping_lock.acquire(blocking=False):
        try:
            print("Background scraping task started.")
            news_aggregator.scrape_all_sources()
            print("Background scraping task finished.")
        except Exception as e:
            print(f"Error in background_scraper_task: {e}")
        finally:
            scraping_lock.release()
    else:
        print("Scraping task already in progress. Skipping new request.")


@app.route('/update-news-json')
def update_news_json_route():
    if not scraping_lock.locked():
        thread = threading.Thread(target=background_scraper_task)
        thread.start()
        return jsonify({'status': 'success', 'message': 'News update process started in background.'})
    else:
        return jsonify({'status': 'busy', 'message': 'News update process is already running.'}), 429


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)