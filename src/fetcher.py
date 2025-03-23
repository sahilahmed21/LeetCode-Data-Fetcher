import json
import time
from collections import defaultdict
import requests
from .utils import make_request, handle_rate_limit, parse_html_content
from .scraper import scrape_problem_description

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
                print(f"Failed to fetch solved questions: Status {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return []
            data = response.json()
            questions = []
            difficulties = {1: "easy", 2: "medium", 3: "hard"}
            for pair in data.get("stat_status_pairs", []):
                if pair.get("status") != "ac":
                    continue
                stat = pair["stat"]
                difficulty = difficulties.get(pair["difficulty"]["level"], "unknown")
                questions.append({
                    "question_id": stat["question_id"],
                    "frontend_question_id": stat["frontend_question_id"],
                    "title_slug": stat["question__title_slug"],
                    "status": pair["status"],
                    "difficulty": difficulty
                })
            print(f"Fetched {len(questions)} solved questions.")
            return questions
        except Exception as e:
            print(f"Error fetching solved questions: {str(e)}")
            return []

    def fetch_submissions_for_question(self, title_slug):
        """Fetch submissions for a specific question."""
        url = f"{self.api_base}/submissions/{title_slug}/"
        try:
            response = requests.get(url, headers=self.headers, cookies=self.cookies, timeout=30)
            if response.status_code != 200:
                print(f"Failed to fetch submissions for {title_slug}: Status {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return []
            data = response.json()
            submissions = data.get("submissions_dump", [])
            # Filter for accepted submissions and get the latest per language
            accepted_subs = {}
            for sub in submissions:
                if sub.get("status_display") != "Accepted":
                    continue
                lang = sub["lang"]
                if lang not in accepted_subs or int(sub["timestamp"]) > int(accepted_subs[lang]["timestamp"]):
                    accepted_subs[lang] = sub
            return list(accepted_subs.values())
        except Exception as e:
            print(f"Error fetching submissions for {title_slug}: {str(e)}")
            return []

    def fetch_submissions(self, limit=500):
        """Fetch all submissions by first getting solved questions, then submissions per question."""
        questions = self.fetch_solved_questions()
        if not questions:
            return []
        
        submissions = []
        total_questions = len(questions)
        for i, q in enumerate(questions):
            title_slug = q["title_slug"]
            print(f"Fetching submissions for question {i+1}/{total_questions}: {title_slug}")
            subs = self.fetch_submissions_for_question(title_slug)
            for sub in subs:
                submissions.append({
                    "title": title_slug.replace('-', ' ').title(),
                    "titleSlug": title_slug,
                    "timestamp": str(sub["timestamp"]),
                    "statusDisplay": sub["status_display"],
                    "lang": sub["lang"],
                    "runtime": sub.get("runtime", "N/A"),
                    "memory": sub.get("memory", "N/A"),
                    "id": str(sub["id"]),
                    "code": sub.get("code", "")
                })
            time.sleep(1)  # Avoid rate limiting
        print(f"Fetched {len(submissions)} total submissions.")
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
            print(f"Couldn't fetch problem details for {slug} via GraphQL, trying scraper...")
            return self.scrape_problem_fallback(slug)
        question = response["data"]["question"]
        question["description"] = parse_html_content(question.get("content", ""))
        del question["content"]
        question["tags"] = [tag["name"] for tag in question.get("topicTags", [])]
        del question["topicTags"]
        return question

    def fetch_problem_set(self, limit=50, skip=0, category_slug="", filters={}):
        """Fetch a list of LeetCode problems."""
        query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
          problemsetQuestionList: questionList(
            categorySlug: $categorySlug
            limit: $limit
            skip: $skip
            filters: $filters
          ) {
            total: totalNum
            questions: data {
              acRate
              difficulty
              frontendQuestionId: questionFrontendId
              paidOnly: isPaidOnly
              title
              titleSlug
              topicTags { name }
              hasSolution
            }
          }
        }
        """
        payload = {
            "query": query,
            "variables": {
                "categorySlug": category_slug,
                "limit": limit,
                "skip": skip,
                "filters": filters
            }
        }
        response = handle_rate_limit(
            lambda: make_request(self.url, payload, self.cookies, self.headers)
        )
        return response["data"]["problemsetQuestionList"]

    def scrape_problem_fallback(self, slug):
        """Fallback method to scrape problem details if GraphQL fails."""
        try:
            problem_data = scrape_problem_description(slug, self.cookies)
            return {
                "title": problem_data.get("title", slug),
                "description": problem_data.get("description", ""),
                "difficulty": problem_data.get("difficulty", "Unknown"),
                "tags": problem_data.get("tags", [])
            }
        except Exception as e:
            print(f"Scraping fallback failed for {slug}: {str(e)}")
            return {
                "title": slug,
                "description": "",
                "difficulty": "Unknown",
                "tags": []
            }

    def process_data(self, profile_stats, submissions):
        """Process and structure fetched data into the required format."""
        difficulty_stats = {
            item["difficulty"]: item["count"]
            for item in profile_stats["submitStats"]["acSubmissionNum"]
            if item["difficulty"] in ["Easy", "Medium", "Hard"]
        }
        problem_submissions = defaultdict(list)
        for sub in submissions:
            slug = sub["titleSlug"]
            problem_submissions[slug].append({
                "status": sub["statusDisplay"],
                "timestamp": sub["timestamp"],
                "runtime": sub["runtime"],
                "memory": sub["memory"],
                "language": sub["lang"],
                "id": sub["id"],
                "code": sub["code"]
            })
        problems = []
        for i, slug in enumerate(problem_submissions.keys()):
            print(f"Fetching details for problem {i+1}/{len(problem_submissions)}: {slug}")
            problem_info = self.fetch_problem_details(slug)
            problem_info["slug"] = slug
            problem_info["submissions"] = problem_submissions[slug]
            problems.append(problem_info)
            if i % 5 == 0 and i > 0:
                time.sleep(1)  # Avoid rate limiting
        return {
            "username": self.username,
            "profile_stats": {
                "total_solved": sum(difficulty_stats.values()),
                "easy": difficulty_stats.get("Easy", 0),
                "medium": difficulty_stats.get("Medium", 0),
                "hard": difficulty_stats.get("Hard", 0)
            },
            "problems": problems
        }

    def save_data(self, data, output_path):
        """Save structured data to JSON file."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)