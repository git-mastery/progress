from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import json
import os
import threading

from github import Github

g = Github(os.environ["GITHUB_TOKEN"])
repo = g.get_repo(os.environ["GITHUB_REPOSITORY"])

os.makedirs("students", exist_ok=True)


# These are all shared states that we want to protect
lock = threading.Lock()
user_map = {}
latest_sync_hashes = {}  # These include the user_id: latest commit hash to decide if we need to update the data
with open("latest_sync_hashes.json", "a") as latest_sync_hashes_file:
    latest_sync_hashes = json.load(latest_sync_hashes_file)


def process_pr(pr):
    username = pr.user.login
    user_id = pr.user.id
    pr_repo = pr.head.repo
    pr_ref = pr.head.ref

    head_sha = pr.head.sha

    with lock:
        if user_id in latest_sync_hashes and latest_sync_hashes[user_id] == head_sha:
            # Means we already saw the latest
            return None

    try:
        contents = pr_repo.get_contents("progress.json", ref=pr_ref)
        progress_data = json.loads(contents.decoded_content.decode())

        with open(f"students/{user_id}.json", "w") as f:
            json.dump(progress_data, f, indent=2)

        with lock:
            user_map[user_id] = username
            latest_sync_hashes[user_id] = head_sha

        print(f"Processed PR from {username}")
        return username

    except Exception as e:
        print(f"Could not process PR from {username}: {e}")
        return None


prs = repo.get_pulls(state="open", base="main")

max_workers = 8

processed_users = []
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(process_pr, pr): pr for pr in prs}
    for future in as_completed(futures):
        processed_username = future.result()
        if processed_username is not None:
            processed_users.append(processed_username)


if processed_users:
    subprocess.run(["git", "add", "students"], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Update progress for {len(processed_users)} students"],
        check=True,
    )


with open("user_map.json", "w") as f:
    json.dump(user_map, f, indent=2)

with open("latest_sync_hashes.json", "w") as f:
    json.dump(latest_sync_hashes, f, indent=2)

user_map_diff_result = subprocess.run(
    ["git", "diff", "--quiet", "user_map.json"], capture_output=True
)

if user_map_diff_result.returncode != 0:
    subprocess.run(["git", "add", "user_map.json"], check=True)
    subprocess.run(["git", "commit", "-m", "Update user_map.json"], check=True)
else:
    print("No changes to user_map.json")

latest_sync_hashes_diff_result = subprocess.run(
    ["git", "diff", "--quiet", "latest_sync_hashes.json"], capture_output=True
)

if latest_sync_hashes_diff_result.returncode != 0:
    subprocess.run(["git", "add", "latest_sync_hashes.json"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "Update latest_sync_hashes.json"], check=True
    )
else:
    print("No changes to latest_sync_hashes.json")

subprocess.run(["git", "push", "origin", "tracker"], check=True)
