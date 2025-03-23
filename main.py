import json
import os
from src.fetcher import LeetCodeFetcher

def main():
    config_path = "config/config.json"
    output_dir = "output"
    output_path = os.path.join(output_dir, "leetcode_data.json")

    with open(config_path, "r") as f:
        config = json.load(f)
    
    username = config["username"]
    session_cookie = config["session_cookie"]
    csrf_token = config["csrf_token"]

    print(f"Fetching data for user: {username}")
    fetcher = LeetCodeFetcher(username, session_cookie, csrf_token)

    print("Testing API connection...")
    fetcher.test_connection()
    print("API connection successful.")

    print("Fetching profile stats...")
    profile_stats = fetcher.fetch_profile_stats()

    print("Fetching submission history...")
    submissions = fetcher.fetch_submissions(limit=500)  # High limit to get all

    print("Processing submissions and fetching problem details...")
    data = fetcher.process_data(profile_stats, submissions)

    os.makedirs(output_dir, exist_ok=True)
    print(f"Saving data to {output_path}...")
    fetcher.save_data(data, output_path)
    print(f"Successfully saved LeetCode data to {output_path}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {str(e)}")