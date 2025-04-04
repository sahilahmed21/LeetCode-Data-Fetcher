import json
import time
from collections import defaultdict
import requests
import sys
from .utils import make_request, handle_rate_limit, parse_html_content
from .scraper import scrape_problem_description, scrape_submission_code # Ensure scrape_submission_code is imported

# --- Helper to log progress to stderr ---
def log_stderr(message):
    print(message, file=sys.stderr)

class LeetCodeFetcher:
    def __init__(self, username, session_cookie, csrf_token):
        """Initialize LeetCode fetcher with user credentials."""
        self.username = username
        self.graphql_url = "https://leetcode.com/graphql"
        self.api_base_url = "https://leetcode.com/api"
        self.cookies = {"LEETCODE_SESSION": session_cookie, "csrftoken": csrf_token}
        # Base headers, Cookie will be handled by requests library via cookies param
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://leetcode.com/problemset/all/", # More specific referer
            "X-CSRFToken": csrf_token,
            # REMOVED "Cookie": f"LEETCODE_SESSION={session_cookie}; csrftoken={csrf_token}"
        }
        log_stderr(f"Fetcher initialized for {username}. CSRF: {csrf_token[:5]}..., Session: {session_cookie[:5]}...")

    def test_connection(self):
        """Test GraphQL API connectivity and authentication."""
        log_stderr("Testing GraphQL connection...")
        query = """{ userStatus { isSignedIn } }"""
        payload = {"query": query}
        try:
            # Use make_request for POST to GraphQL
            response_data = handle_rate_limit(
                lambda: make_request(self.graphql_url, payload, self.cookies, self.base_headers)
            )
            if not response_data.get("data") or not response_data["data"]["userStatus"]["isSignedIn"]:
                raise Exception("Authentication failed or user not signed in (checked via GraphQL).")
            log_stderr("GraphQL Connection Test: User is signed in.")
        except Exception as e:
            log_stderr(f"Error during connection test: {e}")
            # Check if the error suggests auth failure specifically
            if "Authentication failed" in str(e):
                 raise Exception(f"Authentication failed during connection test: {e}. Check cookies.")
            raise Exception(f"API Connection Test Failed: {e}")

    def fetch_profile_stats(self):
        """Fetch user profile statistics using GraphQL."""
        log_stderr("Fetching profile stats via GraphQL...")
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
        try:
            response_data = handle_rate_limit(
                lambda: make_request(self.graphql_url, payload, self.cookies, self.base_headers)
            )
            if "errors" in response_data or not response_data.get("data") or not response_data["data"].get("matchedUser"):
                 error_msg = f"GraphQL error fetching profile stats: {response_data.get('errors', 'No data returned')}"
                 log_stderr(error_msg)
                 raise Exception(error_msg)

            stats = response_data["data"]["matchedUser"]
            log_stderr(f"Profile stats fetched successfully for {stats.get('username', 'user')}.")
            return stats
        except Exception as e:
            log_stderr(f"Error in fetch_profile_stats: {e}")
            # Re-raise but ensure sensitive details aren't leaked if needed
            raise Exception(f"Failed to fetch profile stats: {e}")


    def fetch_solved_questions(self):
        """Fetch all solved questions using the REST API endpoint."""
        log_stderr("Fetching solved questions list via REST API...")
        url = f"{self.api_base_url}/problems/algorithms/"
        try:
            # Use requests.get for REST endpoint
            response = requests.get(url, headers=self.base_headers, cookies=self.cookies, timeout=30)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            data = response.json()
            questions = []
             # Use LeetCode's actual difficulty names from API if possible, else map
            difficulties = {1: "Easy", 2: "Medium", 3: "Hard"}
            for pair in data.get("stat_status_pairs", []):
                # Filter for 'ac' (Accepted) status
                if pair.get("status") != "ac":
                    continue
                stat = pair.get("stat", {})
                difficulty_info = pair.get("difficulty", {})
                slug = stat.get("question__title_slug")
                title = stat.get("question__title") # Get title directly if available
                level = difficulty_info.get("level")

                if not slug:
                     log_stderr(f"Warning: Skipping question pair due to missing slug: {stat.get('question_id')}")
                     continue

                questions.append({
                    "slug": slug,
                    "title": title or slug.replace('-', ' ').title(), # Fallback title from slug
                    "difficulty": difficulties.get(level, "Unknown")
                })

            log_stderr(f"Fetched {len(questions)} solved question slugs.")
            return questions

        except requests.exceptions.HTTPError as http_err:
             log_stderr(f"HTTP error fetching solved questions: {http_err} - Status: {response.status_code}")
             if response.status_code in [401, 403]:
                 raise Exception(f"Authentication failed fetching solved questions (Status {response.status_code}). Check cookies.")
             else:
                 raise Exception(f"HTTP error fetching solved questions: {http_err}")
        except requests.exceptions.RequestException as req_err:
            log_stderr(f"Request error fetching solved questions: {req_err}")
            raise Exception(f"Network error fetching solved questions: {req_err}")
        except Exception as e:
            log_stderr(f"Error parsing solved questions data: {e}")
            raise Exception(f"Failed to parse solved questions list: {e}")

    def fetch_submissions_for_question(self, title_slug):
        """Fetch submissions for a specific question using the REST API."""
        url = f"{self.api_base_url}/submissions/{title_slug}/"
        log_stderr(f"Attempting to fetch submissions for: {title_slug} via REST API")
        try:
            # Use simple GET request with cookies handled by requests library
            response = requests.get(url, headers=self.base_headers, cookies=self.cookies, timeout=45) # Increased timeout

            # Explicitly check for 403 before raising generic error
            if response.status_code == 403:
                 log_stderr(f"Failed to fetch submissions for {title_slug}: Status 403 (Forbidden). Check authentication/permissions.")
                 # Return empty list on auth failure for this specific slug
                 return []
            elif response.status_code == 429:
                 log_stderr(f"Rate limited fetching submissions for {title_slug}. Consider adding delays.")
                 # Could implement retry here or let higher level handle
                 return []

            response.raise_for_status() # Raise for other errors (4xx, 5xx)

            data = response.json()
            api_submissions = data.get("submissions_dump", [])
            if not api_submissions:
                log_stderr(f"No submissions found in API response for {title_slug}.")
                return []

            # Filter for accepted submissions and get the latest per language, fetch code if needed
            accepted_subs_details = {}
            for sub in api_submissions:
                if sub.get("status_display") != "Accepted":
                    continue

                lang = sub.get("lang")
                if not lang:
                    continue

                try:
                    current_ts = int(sub["timestamp"])
                except (ValueError, TypeError):
                    log_stderr(f"Warning: Invalid timestamp '{sub.get('timestamp')}' for submission ID {sub.get('id')} in {title_slug}")
                    continue

                # Check if this submission is newer for the language
                if lang not in accepted_subs_details or current_ts > int(accepted_subs_details[lang]["timestamp"]):
                    submission_id = sub.get("id")
                    code = sub.get("code") # Sometimes the API includes it
                    if not code and submission_id:
                        log_stderr(f"Code not in API dump for submission {submission_id}, attempting scrape...")
                        # Add a small delay before scraping
                        time.sleep(0.5)
                        code = scrape_submission_code(submission_id, self.cookies)
                        if not code:
                             log_stderr(f"Warning: Failed to scrape code for submission {submission_id}")
                             code = "// Code could not be retrieved"

                    # Store the details needed by the backend
                    accepted_subs_details[lang] = {
                        "status": sub["status_display"],
                        "timestamp": str(sub["timestamp"]), # Ensure string
                        "runtime": sub.get("runtime", "N/A"),
                        "memory": sub.get("memory", "N/A"),
                        "language": lang,
                        "submission_id": str(submission_id), # Ensure string
                        "code": code or ""
                    }
            log_stderr(f"Found {len(accepted_subs_details)} accepted submissions for {title_slug}.")
            return list(accepted_subs_details.values())

        except requests.exceptions.HTTPError as http_err:
            # Log non-403 HTTP errors specifically
            log_stderr(f"HTTP error fetching submissions for {title_slug}: {http_err} - Status: {response.status_code}")
            # Return empty list on error for this slug, allows processing others
            return []
        except requests.exceptions.RequestException as req_err:
            log_stderr(f"Request error fetching submissions for {title_slug}: {req_err}")
            return [] # Return empty list on network error for this slug
        except Exception as e:
            # Catch potential JSON parsing errors or others
            log_stderr(f"Unexpected error processing submissions for {title_slug}: {e}")
            return [] # Return empty list on unexpected error for this slug

    def fetch_problem_details(self, slug):
        """Fetch problem details by slug using GraphQL (with scraper fallback)."""
        log_stderr(f"Fetching details for problem: {slug} via GraphQL")
        query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                title
                content
                difficulty
                topicTags { name }
            }
        }
        """
        payload = {"query": query, "variables": {"titleSlug": slug}}
        try:
            # Use make_request for POST to GraphQL
            response_data = handle_rate_limit(
                lambda: make_request(self.graphql_url, payload, self.cookies, self.base_headers)
            )

            if "errors" in response_data or not response_data.get("data") or not response_data["data"].get("question"):
                log_stderr(f"GraphQL failed for {slug}, falling back to scraper. Errors: {response_data.get('errors')}")
                # Fallback to scraper
                time.sleep(0.5) # Small delay before scraping
                scraped_data = scrape_problem_description(slug, self.cookies)
                return {
                    "title": scraped_data.get("title", slug),
                    "description": scraped_data.get("description", "Could not fetch description."),
                    "difficulty": scraped_data.get("difficulty", "Unknown"),
                    "tags": scraped_data.get("tags", [])
                }

            question = response_data["data"]["question"]
            description_text = parse_html_content(question.get("content", ""))
            tags = [tag["name"] for tag in question.get("topicTags", []) if tag and "name" in tag]

            log_stderr(f"Successfully fetched details for {slug} via GraphQL.")
            return {
                "title": question.get("title", slug),
                "description": description_text,
                "difficulty": question.get("difficulty", "Unknown"),
                "tags": tags
            }
        except Exception as e:
            log_stderr(f"Error during fetch_problem_details for {slug} (GraphQL/Scraper): {e}")
            # Critical failure for this problem, return minimal info
            return {
                "title": slug.replace('-', ' ').title(),
                "description": f"Error fetching details: {e}",
                "difficulty": "Unknown",
                "tags": []
            }

    def process_data(self, solved_questions, profile_stats):
        """Fetch submissions & details for solved questions and structure data."""
        log_stderr("Starting data processing: Fetching submissions and details...")
        # Process profile stats
        difficulty_map = {"Easy": 0, "Medium": 0, "Hard": 0}
        total_solved = 0
        if profile_stats and profile_stats.get("submitStats"):
             for item in profile_stats["submitStats"].get("acSubmissionNum", []):
                 difficulty = item.get("difficulty")
                 count = item.get("count", 0)
                 if difficulty in difficulty_map:
                     difficulty_map[difficulty] = count
                     total_solved += count
        log_stderr(f"Profile Stats Processed: Total={total_solved}, E={difficulty_map['Easy']}, M={difficulty_map['Medium']}, H={difficulty_map['Hard']}")

        problems_output = []
        total_to_process = len(solved_questions)

        # Fetch submissions and details per solved question
        for i, question_info in enumerate(solved_questions):
            slug = question_info["slug"]
            log_stderr(f"Processing {i+1}/{total_to_process}: {slug}")

            # 1. Fetch submissions for this specific slug
            submissions_list = self.fetch_submissions_for_question(slug)
            # If submissions fail (e.g., 403), submissions_list will be empty, but we still fetch details

            # 2. Fetch problem details
            problem_details = self.fetch_problem_details(slug)

            # 3. Combine into the final structure
            problems_output.append({
                "title": problem_details.get("title", question_info.get("title", slug)), # Use best available title
                "slug": slug, # Ensure slug is always included
                "difficulty": problem_details.get("difficulty", question_info.get("difficulty", "Unknown")), # Best available difficulty
                "description": problem_details.get("description", ""),
                "tags": problem_details.get("tags", []),
                "submissions": submissions_list # Attach the (potentially empty) list of submissions
            })

            # Add delay to avoid rate limiting (adjust as needed)
            if i > 0 and i % 10 == 0:
                time.sleep(1.5)
            else:
                time.sleep(0.7)

        log_stderr(f"Finished processing {len(problems_output)} problems.")
        return {
            "profile_stats": {
                "total_solved": total_solved,
                "easy": difficulty_map["Easy"],
                "medium": difficulty_map["Medium"],
                "hard": difficulty_map["Hard"]
            },
            "problems": problems_output # This list now contains problems with details and their submissions
        }

# Main Execution Logic (No changes needed in main.py structure itself)
# main.py should call these methods in the correct order:
# 1. fetcher = LeetCodeFetcher(...)
# 2. fetcher.test_connection()
# 3. profile_stats = fetcher.fetch_profile_stats()
# 4. solved_questions = fetcher.fetch_solved_questions()
# 5. data = fetcher.process_data(solved_questions, profile_stats) <--- Pass solved_questions here
# 6. print(json.dumps(data))