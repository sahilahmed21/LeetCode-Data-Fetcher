import json
import argparse
import sys
# Ensure src directory is in path or adjust import if needed based on execution context
from src.fetcher import LeetCodeFetcher

def main():
    parser = argparse.ArgumentParser(description="Fetch LeetCode data for a user.")
    parser.add_argument("--username", required=True, help="LeetCode username")
    parser.add_argument("--session", required=True, help="LEETCODE_SESSION cookie value")
    parser.add_argument("--csrf", required=True, help="csrftoken cookie value")

    args = parser.parse_args()

    username = args.username
    session_cookie = args.session
    csrf_token = args.csrf

    # Use stderr for progress messages so stdout remains clean for JSON output
    print(f"Fetching data for user: {username}", file=sys.stderr)

    try:
        fetcher = LeetCodeFetcher(username, session_cookie, csrf_token)

        # 1. Test Connection
        fetcher.test_connection() # Will raise exception on failure

        # 2. Fetch Profile Stats
        profile_stats = fetcher.fetch_profile_stats() # Will raise exception on failure

        # 3. Fetch List of Solved Questions (slugs, titles, difficulty)
        solved_questions = fetcher.fetch_solved_questions()

        # Check if solved_questions fetch was successful before proceeding
        if solved_questions is None: # fetch_solved_questions might return None on critical error
             raise Exception("Failed to retrieve the list of solved questions.")

        # 4. Process Data (Fetch Submissions & Details for each solved question)
        # Pass the list of solved questions and profile stats
        data = fetcher.process_data(solved_questions, profile_stats)

        # 5. Output the final data as JSON to stdout
        # Use compact separators for potentially smaller output, but None indent for single line
        print(json.dumps(data, indent=None, separators=(',', ':')))

        print(f"Successfully fetched and processed data for {username}.", file=sys.stderr)

    except Exception as e:
        # Print error message to stderr
        print(f"Error: {str(e)}", file=sys.stderr)
        # Exit with a non-zero status code to indicate failure
        sys.exit(1)

if __name__ == "__main__":
    main()