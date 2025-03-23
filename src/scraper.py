import requests
from bs4 import BeautifulSoup
import re

def scrape_problem_description(slug, cookies=None):
    """Scrape problem description from LeetCode problem page when GraphQL fails."""
    url = f"https://leetcode.com/problems/{slug}/"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml"
    }
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
        if response.status_code != 200:
            return {
                "title": slug,
                "description": "",
                "difficulty": "Unknown",
                "tags": []
            }
        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.find('title')
        title = title_elem.text.replace(' - LeetCode', '') if title_elem else slug
        problem_container = soup.select_one('div[data-cy="question-title"]')
        if problem_container:
            parent = problem_container.parent
            description_container = parent.find_next('div', {'class': 'content__u3I1'})
            description = description_container.get_text() if description_container else ""
            description = re.sub(r'\n\s*\n', '\n\n', description)
            description = re.sub(r' +', ' ', description)
        else:
            description_elem = soup.select_one('div.question-content')
            description = description_elem.get_text() if description_elem else ""
        difficulty_elem = soup.select_one('div[diff]')
        difficulty = difficulty_elem.get('diff') if difficulty_elem else "Unknown"
        tags_container = soup.select('div.tag-v2')
        tags = [tag.text.strip() for tag in tags_container] if tags_container else []
        return {
            "title": title,
            "description": description.strip(),
            "difficulty": difficulty,
            "tags": tags
        }
    except Exception as e:
        print(f"Error scraping problem {slug}: {str(e)}")
        return {
            "title": slug,
            "description": "",
            "difficulty": "Unknown",
            "tags": []
        }

def scrape_submission_code(submission_id, cookies=None):
    """Scrape submission code from LeetCode submission detail page."""
    url = f"https://leetcode.com/submissions/detail/{submission_id}/"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml",
        "Referer": "https://leetcode.com/submissions/",
        "X-CSRFToken": cookies.get("csrftoken") if cookies else None
    }
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch submission {submission_id}: Status {response.status_code}")
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        code_elem = soup.select_one('div.CodeMirror-code')  # Adjust if needed
        if code_elem:
            code_lines = [line.get_text() for line in code_elem.find_all('div')]
            return '\n'.join(code_lines).strip()
        print(f"No code found for submission {submission_id}")
        return None
    except Exception as e:
        print(f"Error scraping submission {submission_id}: {str(e)}")
        return None

def scrape_all_submissions(username, cookies=None):
    """Scrape all submission IDs from the user's submissions page."""
    url = f"https://leetcode.com/{username}/submissions/"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml",
        "Referer": "https://leetcode.com/"
    }
    submissions = []
    page = 1
    while True:
        page_url = f"{url}?page={page}"
        try:
            response = requests.get(page_url, headers=headers, cookies=cookies, timeout=30)
            if response.status_code != 200:
                print(f"Failed to fetch submissions page {page}: Status {response.status_code}")
                break
            soup = BeautifulSoup(response.text, 'html.parser')
            submission_rows = soup.select('tr[data-submission-id]')
            if not submission_rows:
                print(f"No more submissions found on page {page}")
                break
            for row in submission_rows:
                sub_id = row.get('data-submission-id')
                title_elem = row.select_one('a[href*="/problems/"]')
                title = title_elem.text.strip() if title_elem else "Unknown"
                slug = title_elem['href'].split('/')[2] if title_elem else "unknown"
                status_elem = row.select_one('td:nth-child(3)')
                status = status_elem.text.strip() if status_elem else "Unknown"
                runtime_elem = row.select_one('td:nth-child(4)')
                runtime = runtime_elem.text.strip() if runtime_elem else "N/A"
                memory_elem = row.select_one('td:nth-child(5)')
                memory = memory_elem.text.strip() if memory_elem else "N/A"
                lang_elem = row.select_one('td:nth-child(6)')
                lang = lang_elem.text.strip() if lang_elem else "Unknown"
                timestamp_elem = row.select_one('td:nth-child(2) span')
                timestamp = timestamp_elem.get('data-timestamp') if timestamp_elem else "0"
                submissions.append({
                    "id": sub_id,
                    "title": title,
                    "titleSlug": slug,
                    "statusDisplay": status,
                    "runtime": runtime,
                    "memory": memory,
                    "lang": lang,
                    "timestamp": timestamp
                })
            print(f"Fetched {len(submission_rows)} submissions from page {page}")
            page += 1
            time.sleep(1)  # Avoid rate limiting
        except Exception as e:
            print(f"Error scraping submissions page {page}: {str(e)}")
            break
    return submissions