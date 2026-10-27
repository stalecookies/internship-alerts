# Embedded / RTL / Hardware Internship Discord Alerts

A Python alert service that polls publicly available internship sources, filters for embedded/firmware, digital design/RTL/FPGA, ASIC/semiconductor, circuits/hardware, signal integrity/RF and photonics, and posts Discord **embeds** with colored left borders. It recognizes internships and co-ops. It **does not filter by internship season, graduation year, GPA, citizenship, or degree requirements**. The default configuration **only alerts for United States locations**, including explicitly US-based remote jobs. A location marked merely `Remote` or missing a region is skipped to avoid international notifications.

## Current source coverage

- **Simplify / Pitt CSC Summer 2027 Internships**: The maintained JSON list contains Summer 2027 and off-season postings, along with locations, terms, URLs and added dates when known. The list is updated by its maintainers, not in real time. Source: https://github.com/SimplifyJobs/Summer2027-Internships
- **Greenhouse** company boards, using the public Greenhouse Job Board API.
- **Lever** company boards, using the public Lever Postings API (paginated).
- **Ashby** company boards, using the public Ashby Job Postings API.

For Greenhouse, Lever, and Ashby, **only companies explicitly included in `config.json` are monitored**. These ATS providers do not offer a public universal list of every company. Boards on Workday, LinkedIn, Handshake, proprietary career sites, etc. are **not monitored in this starter project**, except when a posting appears in the Simplify source. It cannot guarantee that every internship on the internet is found.

## Zero-cost cloud setup (recommended; laptop may be turned off)

Use GitHub Actions on a **public** GitHub repository. Standard GitHub-hosted runners for public repositories are currently free. A 15-minute cron schedule periodically checks the sources and saves deduplication state back to the repository. No always-on server or paid Discord Nitro is required.

1. In Discord, click **+** on the left > **Create My Own** > create a server (e.g. `Internship Alerts`). Add a text channel named `internship-alerts`.
2. In the text channel settings, open **Integrations** > **Webhooks** > **New Webhook** > **Copy Webhook URL**. **Treat this URL like a password: do not paste it into the GitHub repository or share it publicly.**
3. Create a **new, empty, public** GitHub repository, e.g. `internship-alerts`. Do not add a README during repository creation because this folder has its own.
4. Unzip this project locally. From a macOS Terminal opened inside `internship-alert-bot`, run:

   ```bash
   git init -b main
   git add .
   git commit -m "Set up US internship alert bot"
   git remote add origin https://github.com/YOUR_USERNAME/internship-alerts.git
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` with your own GitHub username. You must sign in to GitHub for the push. Keep any `.env` file out of Git.
5. On GitHub: repository **Settings** > **Secrets and variables** > **Actions** > **New repository secret**. Name it **`DISCORD_WEBHOOK_URL`** and paste the copied webhook URL as its value. This secret must not appear in any code or README.
6. On GitHub: **Actions** > **US hardware internship alerts** > **Run workflow**, and select **`send_test`**. You should receive a sample Discord embed. Next choose **`scan`** to initialize the database without flooding the channel with old jobs.
7. Thereafter, scheduled scans run near `:07`, `:22`, `:37`, and `:52` each hour, subject to GitHub scheduling delays. The `.github/workflows/internship-alerts.yml` file handles everything. Every successful scan writes seen-job hashes to `state/seen_jobs.sqlite3` and automatically commits new state back to the repo.

**Important free-hosting caveats:** GitHub Actions schedules can be delayed or occasionally dropped, and GitHub automatically disables a public repository's scheduled workflow after 60 days of repository inactivity. Check the Actions tab periodically, especially outside recruitment season. You can reactivate it there. When adding company feeds to `config.json`, commit the updated config to GitHub. Workflows require `contents: write` permission; if state persistence fails, check **Settings > Actions > General > Workflow permissions**. The seen-job database is committed to a public repository, but no Discord secrets or message contents are stored in it.

**Coverage:** This starter version polls Simplify's public Summer 2027 feed and any individual ATS boards you configure. It does not discover every company's ATS board on its own and is not a guarantee of all U.S. internships. Add verified board identifiers in `config.json` to improve coverage and update yearly sources as future internship lists become available.

## Quick start (macOS / Linux)

1. Create a Discord channel for alerts. Then either:
   - **Webhook method (simpler)**: Edit channel > Integrations > Webhooks > New Webhook > Copy Webhook URL. Webhook messages use a bot-style name and avatar, without requiring a Discord application.
   - **Actual Discord bot**: Create an application at https://discord.com/developers/applications, add a bot, invite it to your server with **View Channel, Send Messages, Embed Links**, and obtain its token and channel ID.
2. Install Python 3.10+ (Python 3.12 recommended).
3. From this folder, run:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
4. Fill in `DISCORD_WEBHOOK_URL` in `.env` **or** `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`. Keep `.env` private and out of GitHub.
5. Run a no-network example preview:
   ```bash
   python bot.py --preview
   ```
6. Test Discord delivery:
   ```bash
   python bot.py --send-test
   ```
7. Start monitoring:
   ```bash
   python bot.py
   ```

When run locally or in Docker, polling occurs every **15 minutes** (`POLL_SECONDS=900`). For GitHub Actions the workflow uses a cron schedule instead. The **first successful scan of each source** saves matching existing postings to SQLite and does **not** spam historical alerts. Subsequent new matching URLs trigger notifications. If you want to send existing matching jobs too, set `BOOTSTRAP_MODE=notify_existing` in `.env` **before first start**, and consider reducing the per-cycle alert limit. Existing results may be very numerous.

To preview real matches without sending, run `python bot.py --dry-run --once`. This displays up to `max_alerts_per_cycle` candidate lines and does not modify your saved state.

## Company-specific boards (more comprehensive coverage)

Edit `config.json`, for example:

```json
{
  "simplify_2027": true,
  "greenhouse": {"Company A": "company_a_greenhouse_token"},
  "lever": {"Company B": "company_b_lever_site"},
  "ashby": {"Company C": "company_c_ashby_board_name"},
  "max_alerts_per_cycle": 50
}
```

Replace the example labels and tokens with **real board identifiers** before running. These are examples only, not verified live company boards. The identifier is typically the employer-specific part of its hosted careers URL:

- `https://job-boards.greenhouse.io/BOARD_TOKEN`
- `https://jobs.lever.co/SITE`
- `https://jobs.ashbyhq.com/BOARD_NAME`

The service independently polls each configured company. New boards added later are baselined separately to avoid flooding the channel with old jobs.

## Running continuously

For the direct Python/Docker method the script must run on a computer that remains powered on. It does **not** continue running after you close a laptop or stop the process. **The GitHub Actions method above runs in the cloud instead and does not require your laptop to be on.** Docker is supported:

```bash
cp .env.example .env
# Fill in .env first.
docker compose up --build -d
```

`compose.yaml` mounts the SQLite database in `./data` so deduplication persists across restarts. Do not use a deployment setup that discards this persistent database between runs.

## Notification fields

Colored embedded card with a clickable title and fields `Company`, `Location`, `Posted`, `Term`, `Matched on`, and a footer like `RTL / ASIC / FPGA | Score 6/10 | via Simplify`. The relevance score is a **simple keyword heuristic**, not a guarantee of personal fit. `Posted` is deliberately omitted when the provider does not supply an actual posting date; Greenhouse's `updated_at` is *not* treated as a creation date.

## Limits and operational details

- ATS polling is near-real-time relative to `POLL_SECONDS`; Simplify entries arrive only after the source is updated. Expect some detection delay.
- A posting found through multiple sources is deduplicated **if the application URL is the same** after removing tracking parameters. Different URLs for one job can still cause duplicates.
- Only explicitly US-located jobs trigger alerts with the provided configuration; unqualified `Remote` jobs are conservatively excluded. Only active/visible Simplify entries trigger alerts. Direct ATS feeds return their own published postings.
- `max_alerts_per_cycle` guards against sudden floods. Postings beyond the limit are reconsidered in future cycles.
- Failed source fetches do not erase existing state. Failed Discord sends are retried in a later cycle. Discord rate limits receive brief retries.
- When the next year's internship repository becomes the active source, change `SIMPLIFY_URL` in `bot.py` or extend the collector. Source coverage is currently focused on the 2027 repository and configured ATS boards.
- Search terms are intentionally broad, so some irrelevant matches are possible; edit `CATEGORIES` and `classify()` to tune relevance.

## Tests

```bash
python -m unittest discover -s tests -v
```

No Discord credentials are required for testing or preview.
