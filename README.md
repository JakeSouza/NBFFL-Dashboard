# NBFFL Dashboard

A local ESPN fantasy football dashboard generator for a league. It pulls your league data from ESPN, builds a rich HTML dashboard, and saves it as `index.html` so you can open it in a browser or publish it anywhere.

## What this project does

This script generates a single-page dashboard with:

- Current season standings
- Historical standings and all-time league view
- Weekly matchup cards with projected-score outlooks
- Power rankings and luck index
- Draft report card and draft board
- Prediction accuracy against ESPN projections
- League champions and rivalry tracker
- Recent transaction activity

## Project files

- `espn_dashboard.py` — data fetcher and HTML generator
- `index.html` — generated dashboard output

## Requirements

- Python 3
- `espn_api` package

Install dependencies:

```bash
pip install espn_api
```

## Configuration

The script reads configuration from environment variables first and falls back to the defaults in the file.

Edit the top of `espn_dashboard.py` or set these environment variables before running it:

```bash
export LEAGUE_ID=1234567
export YEAR=2026
export ESPN_S2="your_espn_s2_value"
export SWID="your_swid_value"
export HISTORY_START_YEAR=2018
```

### Getting your ESPN credentials

For private leagues, you need the ESPN authentication cookies:

1. Log in to your fantasy league on `fantasy.espn.com`
2. Open browser dev tools
3. Go to the Application/Storage tab and inspect cookies for `fantasy.espn.com`
4. Copy:
   - `espn_s2`
   - `SWID`
5. Paste those values into the environment variables or the script config section

> Keep these values private. Do not commit real `ESPN_S2` or `SWID` values to a public repository.

## Run it

From the project root:

```bash
python espn_dashboard.py
```

This writes `index.html` in the same folder.

Open the generated file in a browser to view the dashboard.

## Notes

- The script is intended for local generation and refreshes.
- You can rerun it anytime to update the dashboard with the latest league data.
- If a historical season cannot be fetched, it is skipped rather than stopping the whole run.

## Security note

The script sends your ESPN credentials directly to ESPN's API only from your machine. It does not upload or transmit your private league data anywhere else.

## Example output

After running the script, the generated dashboard includes sections such as:

- Standings
- Matchups
- Power Rankings
- Draft Report Card
- Prediction Accuracy
- History
- Recent Transactions
- Draft Board

This repo is a lightweight way to turn your ESPN league data into a shareable, browser-friendly dashboard.
