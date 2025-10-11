import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

from github import Github

g = Github(os.environ["GITHUB_TOKEN"])
repo = g.get_repo(os.environ["GITHUB_REPOSITORY"])


def load_json_from_file(filename: str) -> Dict[str, Any]:
    with open(filename, "r") as f:
        return json.load(f)


def write_json_to_file(filename: str, json_obj: Any) -> None:
    with open(filename, "w") as f:
        json.dump(json_obj, f, indent=2)


def has_change_cached() -> bool:
    diff_result = subprocess.run(
        ["git", "diff", "--quiet", "--cached"], capture_output=True
    )
    return diff_result.returncode != 0


def has_change(filepath: str) -> bool:
    diff_result = subprocess.run(
        ["git", "diff", "--quiet", filepath], capture_output=True
    )
    return diff_result.returncode != 0


def add_and_commit(filepath: str, message: str) -> None:
    subprocess.run(["git", "add", filepath], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)


USER_MAP_FILENAME = "user_map.json"
LATEST_SYNC_HASHES_FILENAME = "latest_sync_hashes.json"

MAX_WORKERS = 8

# These are all shared states that we want to protect
LOCK = threading.Lock()
USER_MAP = {}
LATEST_SYNC_HASHES = {
    int(key): value
    for key, value in load_json_from_file(LATEST_SYNC_HASHES_FILENAME).items()
}  # These include the user_id: latest commit hash to decide if we need to update the data


def process_pr(pr):
    username = pr.user.login
    user_id = pr.user.id
    pr_repo = pr.head.repo
    pr_ref = pr.head.ref
    head_sha = pr.head.sha

    with LOCK:
        if user_id in LATEST_SYNC_HASHES and LATEST_SYNC_HASHES[user_id] == head_sha:
            # Means we already saw the latest
            USER_MAP[user_id] = username
            LATEST_SYNC_HASHES[user_id] = head_sha
            print(f"Processing {username} ({user_id}) --- SKIPPED")
            return None

    try:
        contents = pr_repo.get_contents("progress.json", ref=pr_ref)
        progress_data = json.loads(contents.decoded_content.decode())

        write_json_to_file(f"students/{user_id}.json", progress_data)

        with LOCK:
            USER_MAP[user_id] = username
            LATEST_SYNC_HASHES[user_id] = head_sha

        print(f"Processing {username} ({user_id}) --- UPDATED")
        return username

    except Exception as e:
        print(f"Processing {username} ({user_id}) --- FAILED ({e})")
        return None


def main():
    os.makedirs("students", exist_ok=True)

    prs = repo.get_pulls(state="open", base="main")

    processed_users = []
    total_processed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_pr, pr): pr for pr in prs}
        for future in as_completed(futures):
            processed_username = future.result()
            total_processed += 1
            if processed_username is not None:
                processed_users.append(processed_username)

    print(processed_users)
    if processed_users:
        add_and_commit(
            "students/", f"Update progress for {len(processed_users)} students"
        )
    else:
        print("No processed users to update")

    write_json_to_file(USER_MAP_FILENAME, USER_MAP)
    write_json_to_file(LATEST_SYNC_HASHES_FILENAME, LATEST_SYNC_HASHES)

    if has_change(USER_MAP_FILENAME):
        add_and_commit(USER_MAP_FILENAME, f"Update {USER_MAP_FILENAME}")
    else:
        print("No changes to user_map.json")

    if has_change(LATEST_SYNC_HASHES_FILENAME):
        add_and_commit(
            LATEST_SYNC_HASHES_FILENAME, f"Update {LATEST_SYNC_HASHES_FILENAME}"
        )
    else:
        print("No changes to latest_sync_hashes.json")

    subprocess.run(["git", "push", "origin", "tracker"], check=True)
    print(f"Processed {total_processed} students!")


if __name__ == "__main__":
    main()
