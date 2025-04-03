import json
import os
import time
import sys
from collections import defaultdict
import requests
from bs4 import BeautifulSoup
import re

# Utility Functions
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
                print(f"Error response: {response.text[:200]}...", file=sys.stderr)
                raise Exception(f"Request failed with status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            retries += 1
            if retries >= max_retries:
                raise Exception(f"Request failed after {max_retries} retries: {str(e)}")
            sleep_time = 2 ** retries
            print(f"Request failed, retrying in {sleep_time} seconds...", file=sys.stderr)
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
                print(f"Rate limited, retrying in {sleep_time} seconds... (Attempt {retries}/{max_retries})", file=sys.stderr)
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

# Scraper Functions
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
        print(f"Error scraping problem {slug}: {str(e)}", file=sys.stderr)
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
            print(f"Failed to fetch submission {submission_id}: Status {response.status_code}", file=sys.stderr)
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        code_elem = soup.select_one('div.CodeMirror-code')
        if code_elem:
            code_lines = [line.get_text() for line in code_elem.find_all('div')]
            return '\n'.join(code_lines).strip()
        print(f"No code found for submission {submission_id}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error scraping submission {submission_id}: {str(e)}", file=sys.stderr)
        return None

# Fetcher Class
class LeetCodeFetcher:
    def __init__(self, username, session_cookie, csrf_token):
        """Initialize LeetCode fetcher with user credentials."""
        self.username = username
        self.url = "https://leetcode.com/graphql"
        self.api_base = "https://leetcode.com/api"
        self.cookies = {"LEETCODE_SESSION": session_cookie, "csrftoken": csrf_token}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://leetcode.com/",
            "X-CSRFToken": csrf_token,
            "Cookie": f"LEETCODE_SESSION={session_cookie}; csrftoken={csrf_token}"
        }

    def test_connection(self):
        """Test API connectivity and authentication."""
        query = """
        {
            userStatus {
                userId
                isSignedIn
            }
        }
        """
        payload = {"query": query}
        response = handle_rate_limit(
            lambda: make_request(self.url, payload, self.cookies, self.headers)
        )
        if not response.get("data") or not response["data"]["userStatus"]["isSignedIn"]:
            raise Exception("Authentication failed or user not signed in.")

    def fetch_profile_stats(self):
        """Fetch user profile statistics using GraphQL."""
        query = """
        query userPublicProfile($username: String!) {
            matchedUser(username: $username) {
                username
                submitStats: submitStatsGlobal {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }
            }
        }
        """
        payload = {"query": query, "variables": {"username": self.username}}
        response = handle_rate_limit(
            lambda: make_request(self.url, payload, self.cookies, self.headers)
        )
        if not response.get("data") or not response["data"].get("matchedUser"):
            raise Exception("Failed to fetch profile stats. Check if credentials are valid.")
        return response["data"]["matchedUser"]

    def fetch_solved_questions(self):
        """Fetch all solved questions using the algorithms API endpoint."""
        url = f"{self.api_base}/problems/algorithms/"
        try:
            response = requests.get(url, headers=self.headers, cookies=self.cookies, timeout=30)
            if response.status_code != 200:
                print(f"Failed to fetch solved questions: Status {response.status_code}", file=sys.stderr)
                return []
            data = response.json()
            questions = []
            difficulties = {1: "Easy", 2: "Medium", 3: "Hard"}
            for pair in data.get("stat_status_pairs", []):
                if pair.get("status") != "ac":
                    continue
                stat = pair["stat"]
                difficulty = difficulties.get(pair["difficulty"]["level"], "Unknown")
                questions.append({
                    "title": stat["question__title"],
                    "slug": stat["question__title_slug"],
                    "difficulty": difficulty
                })
            print(f"Fetched {len(questions)} solved questions.", file=sys.stderr)
            return questions
        except Exception as e:
            print(f"Error fetching solved questions: {str(e)}", file=sys.stderr)
            return []

    def fetch_submissions_for_question(self, title_slug):
        """Fetch submissions for a specific question."""
        url = f"{self.api_base}/submissions/{title_slug}/"
        try:
            response = requests.get(url, headers=self.headers, cookies=self.cookies, timeout=30)
            if response.status_code != 200:
                print(f"Failed to fetch submissions for {title_slug}: Status {response.status_code}", file=sys.stderr)
                return []
            data = response.json()
            submissions = data.get("submissions_dump", [])
            accepted_subs = {}
            for sub in submissions:
                if sub.get("status_display") != "Accepted":
                    continue
                lang = sub["lang"]
                if lang not in accepted_subs or int(sub["timestamp"]) > int(accepted_subs[lang]["timestamp"]):
                    code = scrape_submission_code(sub["id"], self.cookies) if not sub.get("code") else sub["code"]
                    accepted_subs[lang] = {
                        "status": sub["status_display"],
                        "timestamp": str(sub["timestamp"]),
                        "runtime": sub.get("runtime", "N/A"),
                        "memory": sub.get("memory", "N/A"),
                        "language": sub["lang"],
                        "submission_id": str(sub["id"]),
                        "code": code or ""
                    }
            return list(accepted_subs.values())
        except Exception as e:
            print(f"Error fetching submissions for {title_slug}: {str(e)}", file=sys.stderr)
            return []

    def fetch_submissions(self, limit=500):
        """Fetch all submissions by first getting solved questions, then submissions per question."""
        questions = self.fetch_solved_questions()
        if not questions:
            return []
        
        submissions = []
        total_questions = len(questions)
        for i, q in enumerate(questions):
            title_slug = q["slug"]
            print(f"Fetching submissions for question {i+1}/{total_questions}: {title_slug}", file=sys.stderr)
            subs = self.fetch_submissions_for_question(title_slug)
            submissions.extend(subs)
            time.sleep(1)  # Avoid rate limiting
        print(f"Fetched {len(submissions)} total submissions.", file=sys.stderr)
        return submissions

    def fetch_problem_details(self, slug):
        """Fetch problem details by slug using GraphQL."""
        query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                title
                content
                difficulty
                topicTags {
                    name
                }
            }
        }
        """
        payload = {"query": query, "variables": {"titleSlug": slug}}
        response = handle_rate_limit(
            lambda: make_request(self.url, payload, self.cookies, self.headers)
        )
        if not response.get("data") or not response["data"].get("question"):
            print(f"Couldn't fetch problem details for {slug} via GraphQL, trying scraper...", file=sys.stderr)
            return scrape_problem_description(slug, self.cookies)
        question = response["data"]["question"]
        question["description"] = parse_html_content(question.get("content", ""))
        del question["content"]
        question["tags"] = [tag["name"] for tag in question.get("topicTags", [])]
        del question["topicTags"]
        return question

    def process_data(self, profile_stats, submissions):
        """Process and structure fetched data into the required format."""
        difficulty_stats = {
            item["difficulty"].lower(): item["count"]
            for item in profile_stats["submitStats"]["acSubmissionNum"]
            if item["difficulty"] in ["Easy", "Medium", "Hard"]
        }
        problem_submissions = defaultdict(list)
        for sub in submissions:
            slug = sub.get("titleSlug", "")
            if not slug:
                continue
            problem_submissions[slug].append({
                "status": sub["status"],
                "timestamp": sub["timestamp"],
                "runtime": sub["runtime"],
                "memory": sub["memory"],
                "language": sub["language"],
                "submission_id": sub["submission_id"],
                "code": sub["code"]
            })
        
        problems = []
        for i, slug in enumerate(problem_submissions.keys()):
            print(f"Fetching details for problem {i+1}/{len(problem_submissions)}: {slug}", file=sys.stderr)
            problem_info = self.fetch_problem_details(slug)
            problem_info["slug"] = slug
            problem_info["submissions"] = problem_submissions[slug]
            problems.append(problem_info)
            if i % 5 == 0 and i > 0:
                time.sleep(1)  # Avoid rate limiting
        
        return {
            "profile_stats": {
                "total_solved": sum(difficulty_stats.values()),
                "easy": difficulty_stats.get("easy", 0),
                "medium": difficulty_stats.get("medium", 0),
                "hard": difficulty_stats.get("hard", 0)
            },
            "problems": problems
        }

# Main Execution
def main(username, session_cookie, csrf_token):
    print(f"Fetching data for user: {username}", file=sys.stderr)
    fetcher = LeetCodeFetcher(username, session_cookie, csrf_token)

    print("Testing API connection...", file=sys.stderr)
    fetcher.test_connection()
    print("API connection successful.", file=sys.stderr)

    print("Fetching profile stats...", file=sys.stderr)
    profile_stats = fetcher.fetch_profile_stats()

    print("Fetching submission history...", file=sys.stderr)
    submissions = fetcher.fetch_submissions(limit=500)

    print("Processing submissions and fetching problem details...", file=sys.stderr)
    data = fetcher.process_data(profile_stats, submissions)

    # Output JSON data to stdout
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Successfully fetched and processed data for {username}.", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) != 7:
        print("Usage: python fetcher.py --username <username> --session <session_cookie> --csrf <csrf_token>", file=sys.stderr)
        sys.exit(1)
    
    username = sys.argv[2] if sys.argv[1] == "--username" else None
    session_cookie = sys.argv[4] if sys.argv[3] == "--session" else None
    csrf_token = sys.argv[6] if sys.argv[5] == "--csrf" else None
    
    if not all([username, session_cookie, csrf_token]):
        print("Missing required arguments.", file=sys.stderr)
        sys.exit(1)
    
    try:
        main(username, session_cookie, csrf_token)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)