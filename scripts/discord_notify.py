"""Poll the openswarm repo for new commits, summarize with Claude Haiku, post to Discord."""

import os
import sys

import anthropic
import requests

REPO = "openswarm-ai/openswarm"
SHA_FILE = "last_sha.txt"
MODEL = "claude-haiku-4-5-20251001"


def gh_get(url: str) -> dict | list:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


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
    client = anthropic.Anthropic()
    prompt = f"""Write a short Discord update (2-4 sentences) about what changed in the OpenSwarm project this round.

Rules:
- Warm and casual, like telling a friend what's new
- No developer jargon (no "refactor", "PR", "commit", "endpoint", "API", "async")
- Flowing sentences, no bullet points
- Do not use em-dashes
- End with a short call to action
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


def post_to_discord(text: str, compare_url: str) -> None:
    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    body = {"content": f"{text}\n\n{compare_url}"}
    r = requests.post(webhook, json=body, timeout=30)
    r.raise_for_status()


def main() -> int:
    commits = gh_get(f"https://api.github.com/repos/{REPO}/commits?per_page=10")
    if not commits:
        print("No commits returned from GitHub.")
        return 0

    latest = commits[0]["sha"]
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
    post_to_discord(text, compare_url)
    write_last_sha(latest)
    print(f"Posted update covering {len(new_commits)} new commit(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
