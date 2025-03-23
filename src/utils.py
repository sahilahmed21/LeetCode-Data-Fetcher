import requests
import time
import re
from bs4 import BeautifulSoup

def make_request(url, payload, cookies, headers, max_retries=3):
    """Make HTTP request with retry logic."""
    retries = 0
    while retries < max_retries:
        try:
            response = requests.post(url, json=payload, cookies=cookies, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 403:
                raise Exception("Authentication failed: Invalid or expired cookies")
            elif response.status_code == 429:
                raise Exception("Rate limited")
            else:
                print(f"Error response: {response.text[:200]}...")
                raise Exception(f"Request failed with status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            retries += 1
            if retries >= max_retries:
                raise Exception(f"Request failed after {max_retries} retries: {str(e)}")
            sleep_time = 2 ** retries
            print(f"Request failed, retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)

def handle_rate_limit(request_func, max_retries=5):
    """Handle rate limiting with exponential backoff."""
    retries = 0
    while retries < max_retries:
        try:
            return request_func()
        except Exception as e:
            if "Rate limited" in str(e) and retries < max_retries:
                retries += 1
                sleep_time = 2 ** retries
                print(f"Rate limited, retrying in {sleep_time} seconds... (Attempt {retries}/{max_retries})")
                time.sleep(sleep_time)
            else:
                raise e

def parse_html_content(html_content):
    """Parse HTML content to extract plain text."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    for code in soup.find_all('pre'):
        code.extract()
    text = soup.get_text()
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

def log_error(message, error=None):
    """Log error messages."""
    if error:
        print(f"ERROR: {message} - {str(error)}")
    else:
        print(f"ERROR: {message}")