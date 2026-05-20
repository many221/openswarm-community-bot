"""Collect the past week's commits, ask Claude Sonnet for structured content, send via Resend."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

REPO = "openswarm-ai/openswarm"
SHOWCASE_PATH = "scripts/community_showcase.json"
TEMPLATE_PATH = "scripts/email_template.html"
PREVIEW_PATH = "digest_preview.html"
META_PATH = "digest_meta.json"
MODEL = "claude-sonnet-4-6"
FROM_ADDRESS = "Manny from OpenSwarm <manny@ink.openswarm.com>"
FIRST_EMAIL_SUBJECT = "Building the operating system of the future, together"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
MODE = os.environ.get("MODE", "").lower()  # "render", "send", or "" (one-shot)
FEEDBACK = os.environ.get("FEEDBACK", "").strip()


def gh_get(url: str) -> dict | list:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def commits_past_week() -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return gh_get(
        f"https://api.github.com/repos/{REPO}/commits?since={since}&per_page=100"
    )


def fetch_compare(old_sha: str, new_sha: str) -> dict:
    return gh_get(f"https://api.github.com/repos/{REPO}/compare/{old_sha}...{new_sha}")


def load_showcase() -> dict:
    try:
        with open(SHOWCASE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def parse_model_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        # strip a ``` or ```json fence
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            if inner.lstrip().startswith("json"):
                inner = inner.lstrip()[4:]
            text = inner.strip()
    return json.loads(text)


def build_content(commits: list[dict], diff_summary: str, showcase: dict) -> dict:
    is_first = bool(showcase.get("first_email"))
    contributors = sorted({
        c["commit"]["author"]["name"]
        for c in commits
        if c.get("commit", {}).get("author", {}).get("name")
    })
    messages = "\n".join(
        f"- {c['commit']['message'].splitlines()[0]} "
        f"({c['commit']['author']['name']})"
        for c in commits
    )

    first_email_note = ""
    if is_first:
        first_email_note = (
            f"\n\nIMPORTANT: This is the FIRST weekly email. The subject MUST be exactly: "
            f'"{FIRST_EMAIL_SUBJECT}". '
            "The greeting should thank the community for bearing with us while we build, "
            "and frame these weekly updates as a commitment to transparency."
        )

    feedback_note = ""
    if FEEDBACK:
        feedback_note = (
            "\n\nREVIEWER FEEDBACK (apply these adjustments to this draft, "
            "they override conflicting voice rules if necessary):\n"
            f"{FEEDBACK}"
        )

    prompt = f"""You are Manny from OpenSwarm. Write the weekly update email for the community.

Return ONLY valid JSON, no prose around it, with this exact shape:
{{
  "subject": "string — short, specific, intriguing (never 'Weekly Update')",
  "preheader": "string — one sentence preview text shown in the inbox",
  "greeting": "string — ONE OR TWO short sentences, 22-35 words total, that hooks the reader like a friend sharing good news. This is the editorial lead, so keep it tight.",
  "shipped": ["3 to 5 plain-English bullets; lead each with what the reader can DO now"],
  "spotlight": "string OR null — Mamdani-style 'you told us X was broken, so we fixed it', drawn from the community showcase data. Use null if the showcase has no entries.",
  "shoutouts": "string — name the contributors below in a natural sentence or two",
  "cta": "string — invite people to share what they built, report problems, or collaborate",
  "signoff": "Manny and the OpenSwarm team"
}}

Voice rules:
- 320-400 words total across all fields combined (the greeting must stay under 35 words; spend the rest on shipped/spotlight/shoutouts/cta)
- No corporate speak, no jargon (no 'refactor', 'PR', 'commit', 'endpoint', 'API', 'async')
- No em-dashes anywhere
- Plain English a non-developer would understand{first_email_note}{feedback_note}

Commits this week:
{messages}

Code change highlights (truncated):
{diff_summary[:15000]}

Community showcase data (use for spotlight; if 'spotlights' array is empty or missing, return null for spotlight):
{json.dumps(showcase, indent=2)}

Contributors to shout out: {', '.join(contributors) if contributors else '(none)'}
"""

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    content = parse_model_json(resp.content[0].text)

    if is_first:
        content["subject"] = FIRST_EMAIL_SUBJECT
    return content


def render_email(content: dict) -> str:
    from jinja2 import Template
    with open(TEMPLATE_PATH) as f:
        tmpl = Template(f.read())
    return tmpl.render(**content)


def send_via_resend(subject: str, html: str, preheader: str) -> str:
    api_key = os.environ["RESEND_API_KEY"].strip()
    audience_id = os.environ["RESEND_AUDIENCE_ID"].strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    create_body = {
        "audience_id": audience_id,
        "from": FROM_ADDRESS,
        "subject": subject,
        "html": html,
        "preview_text": preheader,
    }
    r = requests.post(
        "https://api.resend.com/broadcasts",
        headers=headers,
        json=create_body,
        timeout=30,
    )
    r.raise_for_status()
    broadcast_id = r.json()["id"]

    r = requests.post(
        f"https://api.resend.com/broadcasts/{broadcast_id}/send",
        headers=headers,
        json={},
        timeout=30,
    )
    r.raise_for_status()
    return broadcast_id


def clear_first_email_flag() -> None:
    showcase = load_showcase()
    if not showcase.get("first_email"):
        return
    showcase["first_email"] = False
    with open(SHOWCASE_PATH, "w") as f:
        json.dump(showcase, f, indent=2)
        f.write("\n")
    print("Cleared first_email flag in community_showcase.json (commit manually if you want it persisted).")


def render_and_save() -> dict | None:
    """Build the email content, render the HTML, and persist preview + meta files."""
    commits = commits_past_week()
    if not commits:
        print("No commits in the past 7 days; skipping digest.")
        return None

    new_sha = commits[0]["sha"]
    old_sha = commits[-1]["sha"]
    if old_sha != new_sha:
        compare = fetch_compare(old_sha, new_sha)
    else:
        compare = {"files": []}

    diff_blob = "\n\n".join(
        f"File: {f['filename']}\n{f.get('patch', '')[:1500]}"
        for f in compare.get("files", [])[:30]
    )

    showcase = load_showcase()
    content = build_content(commits, diff_blob, showcase)
    html = render_email(content)

    with open(PREVIEW_PATH, "w") as f:
        f.write(html)
    meta = {
        "subject": content["subject"],
        "preheader": content.get("preheader", ""),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    print(f"Rendered email to {PREVIEW_PATH} / {META_PATH}")
    print(f"  subject:   {content['subject']!r}")
    print(f"  preheader: {meta['preheader']!r}")
    print(f"  word count: ~{sum(len(str(v).split()) for v in content.values() if v)}")
    return content


def send_from_artifact() -> str:
    """Load the previously rendered HTML + meta and send via Resend."""
    with open(PREVIEW_PATH) as f:
        html = f.read()
    with open(META_PATH) as f:
        meta = json.load(f)
    broadcast_id = send_via_resend(meta["subject"], html, meta.get("preheader", ""))
    print(f"Sent broadcast {broadcast_id}: {meta['subject']!r}")
    return broadcast_id


def main() -> int:
    if MODE == "render":
        render_and_save()
        return 0

    if MODE == "send":
        send_from_artifact()
        clear_first_email_flag()
        return 0

    # One-shot mode (manual run with no MODE set): render, then send unless DRY_RUN
    content = render_and_save()
    if content is None:
        return 0
    if DRY_RUN:
        print("DRY_RUN: skipped Resend.")
        return 0
    send_from_artifact()
    clear_first_email_flag()
    return 0


if __name__ == "__main__":
    sys.exit(main())
