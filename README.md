# openswarm-community-bot

Two scheduled GitHub Actions that watch the public [openswarm-ai/openswarm](https://github.com/openswarm-ai/openswarm) repo and keep the community in the loop:

- **Discord poller** — every 15 minutes, summarizes new commits with Claude Haiku and posts to a Discord webhook.
- **Weekly email digest** — every Monday at 7am PT, drafts a community newsletter with Claude Sonnet and sends it via Resend Broadcasts.

This repo does not need any permissions on the upstream repo. It only reads the public commits API.

## Setup

1. Push this repo to GitHub.
2. Add these repository secrets (Settings → Secrets and variables → Actions):

   | Secret | Value |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | Your Anthropic API key |
   | `DISCORD_WEBHOOK_URL` | Discord channel webhook |
   | `RESEND_API_KEY` | Resend API key |
   | `RESEND_AUDIENCE_ID` | Your Resend audience ID |

3. Optional: trigger each workflow once from the Actions tab to verify (`workflow_dispatch` is enabled on both).

The first Discord poll seeds the cached SHA without notifying, so you will not see a giant catch-up post on the first run.

## Files

```
.github/workflows/
  discord-poll.yml          # cron */15 * * * *
  weekly-email-digest.yml   # cron 0 14 * * 1 (Monday 14:00 UTC)
scripts/
  discord_notify.py         # poll → summarize → post to Discord
  weekly_digest.py          # collect week → Sonnet → render → Resend
  email_template.html       # Jinja2 template for the digest
  community_showcase.json   # manually updated spotlights/shoutouts
```

## State

The Discord workflow stores the last-seen commit SHA in `last_sha.txt`, persisted between runs through the `actions/cache` API under the key prefix `last-commit-sha-`. The cache refreshes on every run, so the 7-day TTL never expires in practice.

## Updating the showcase

Edit `scripts/community_showcase.json` whenever you want to spotlight something in the next Monday email:

```json
{
  "first_email": false,
  "spotlights": [
    {
      "feedback": "You told us the install step was confusing on Windows.",
      "fix": "We rewrote the setup guide and added a one-line installer."
    }
  ],
  "shoutouts": ["jess", "marcus"]
}
```

Leave `spotlights` empty if there is nothing to spotlight that week — the section is skipped automatically.

The `first_email` flag is set to `true` initially. The very first weekly run uses the launch subject *"Building the operating system of the future, together"* and frames the message as a transparency commitment, then flips the flag off.

## Time zone note

The weekly cron is set to `0 14 * * 1` (14:00 UTC Monday), which is 7am PT during PST. During PDT (mid-March through early November) it fires at 6am PT. Adjust if you want exact 7am PT year-round.

## Rate limits

- GitHub default token: 1,000 req/hr. Each poll uses ~2-3 calls (~8-12/hr at 15-min intervals). Weekly digest uses ~5-10 calls. Plenty of headroom.
- Anthropic: Haiku for polls, Sonnet for the weekly. Both are short prompts.
