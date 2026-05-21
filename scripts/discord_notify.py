"""Poll the openswarm repo for new commits, summarize with Claude Haiku, post to Discord."""

import os
import sys

import anthropic
import requests

REPO = "openswarm-ai/openswarm"
SHA_FILE = "last_sha.txt"
MODEL = "claude-haiku-4-5-20251001"
BOT_NAME = "Inki"
INTRO_MESSAGE = (
    "Hi, I'm Inki. I'll be keeping you updated with any and all "
    "OpenSwarm software updates."
)
FORCE_TEST = os.environ.get("FORCE_TEST", "").lower() == "true"
SEND_INTRO = os.environ.get("SEND_INTRO", "").lower() == "true"


def gh_get(url: str) -> dict | list:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_latest_version() -> str | None:
    """Newest release tag for the repo, falling back to the newest git tag."""
    try:
        rel = gh_get(f"https://api.github.com/repos/{REPO}/releases/latest")
        if isinstance(rel, dict) and rel.get("tag_name"):
            return rel["tag_name"]
    except requests.HTTPError:
        pass
    try:
        tags = gh_get(f"https://api.github.com/repos/{REPO}/tags?per_page=1")
        if isinstance(tags, list) and tags and tags[0].get("name"):
            return tags[0]["name"]
    except requests.HTTPError:
        pass
    return None


def read_last_sha() -> str | None:
    try:
        with open(SHA_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def write_last_sha(sha: str) -> None:
    with open(SHA_FILE, "w") as f:
        f.write(sha)


def summarize(commit_messages: str, diff_blob: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    prompt = f"""You are Inki, the cheerful community companion for OpenSwarm.
Write a short Discord update (2-4 sentences) sharing what just changed in the project.

Voice and rules:
- Speak in first person as Inki, like you're genuinely thrilled to share the news
- Happy, bright, and warm; the kind of energy that makes people smile when they read it
- Casual and friendly, never corporate
- No developer jargon (no "refactor", "PR", "commit", "endpoint", "API", "async")
- Flowing sentences, no bullet points
- Do not use em-dashes
- End with a short upbeat call to action that invites people in
- Do NOT include a link or URL; the link is added separately

Commit messages:
{commit_messages}

Code changes (truncated):
{diff_blob[:8000]}
"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def post_to_discord(
    text: str, compare_url: str | None = None, version: str | None = None
) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"].strip()
    if compare_url and version:
        content = f"{text}\n\nOpenSwarm {version}\n{compare_url}"
    elif compare_url:
        content = f"{text}\n\n{compare_url}"
    else:
        content = text
    body = {"content": content, "username": BOT_NAME}
    r = requests.post(webhook, json=body, timeout=30)
    r.raise_for_status()


def main() -> int:
    if SEND_INTRO:
        post_to_discord(INTRO_MESSAGE)
        print("Sent intro message as Inki.")
        return 0

    commits = gh_get(f"https://api.github.com/repos/{REPO}/commits?per_page=10")
    if not commits:
        print("No commits returned from GitHub.")
        return 0

    latest = commits[0]["sha"]

    if FORCE_TEST:
        if len(commits) < 2:
            print("FORCE_TEST: upstream has fewer than 2 commits, nothing to compare.")
            return 0
        last = commits[1]["sha"]
        print(f"FORCE_TEST: using {last[:7]} as a fake 'last seen' SHA (cache not touched).")
    else:
        last = read_last_sha()
        if last is None:
            print(f"First run — seeding cache with {latest}, no notification sent.")
            write_last_sha(latest)
            return 0
        if last == latest:
            print(f"No new commits since {last[:7]}.")
            return 0

    compare = gh_get(f"https://api.github.com/repos/{REPO}/compare/{last}...{latest}")
    new_commits = compare.get("commits", [])
    if not new_commits:
        print("Compare returned no commits; updating cache and exiting.")
        write_last_sha(latest)
        return 0

    messages = "\n".join(
        f"- {c['commit']['message'].splitlines()[0]}" for c in new_commits
    )
    files = compare.get("files", [])
    diff_blob = "\n\n".join(
        f"File: {f['filename']}\n{f.get('patch', '')[:1000]}"
        for f in files[:20]
    )

    text = summarize(messages, diff_blob)
    compare_url = compare.get("html_url", f"https://github.com/{REPO}/commit/{latest}")
    version = get_latest_version()
    if FORCE_TEST:
        text = f"[TEST] {text}"
    post_to_discord(text, compare_url, version)
    if not FORCE_TEST:
        write_last_sha(latest)
    print(
        f"{'FORCE_TEST: ' if FORCE_TEST else ''}"
        f"Posted update covering {len(new_commits)} new commit(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
