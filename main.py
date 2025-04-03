import json
import argparse
import sys
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

        print("Testing API connection...", file=sys.stderr)
        fetcher.test_connection()
        print("API connection successful.", file=sys.stderr)

        print("Fetching profile stats...", file=sys.stderr)
        profile_stats = fetcher.fetch_profile_stats()

        print("Fetching submission history...", file=sys.stderr)
        # Consider if a limit is appropriate or if fetching all is desired
        # The previous limit was high (500), implying fetching most/all recent.
        # The current implementation fetches *all* accepted submissions via solved questions.
        submissions = fetcher.fetch_submissions() 

        print("Processing submissions and fetching problem details...", file=sys.stderr)
        data = fetcher.process_data(profile_stats, submissions)

        # Output the final data as JSON to stdout
        print(json.dumps(data, indent=None)) # No indentation for cleaner parsing

        print(f"Successfully fetched and processed data for {username}.", file=sys.stderr)

    except Exception as e:
        # Print error message to stderr
        print(f"Error: {str(e)}", file=sys.stderr)
        # Exit with a non-zero status code to indicate failure
        sys.exit(1)

if __name__ == "__main__":
    main()