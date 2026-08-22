"""
ESPN Fantasy Football Dashboard Generator
==========================================
Generates a self-contained HTML page showing your league's standings,
recent transactions, and draft board.

SETUP (one-time)
-----------------
1. Install the library:
       pip install espn_api

2. Get your league ID:
   Go to your league on fantasy.espn.com and look at the URL, e.g.
       https://fantasy.espn.com/football/league?leagueId=1234567
   Your league ID is 1234567.

3. Get your espn_s2 and SWID cookies (needed for private leagues):
   - Log into fantasy.espn.com in Chrome
   - Right-click -> Inspect -> Application tab -> Cookies -> fantasy.espn.com
   - Copy the values for "espn_s2" and "SWID" (SWID includes the curly braces)

4. Fill in the CONFIG section below.

USAGE
-----
    python espn_dashboard.py

This writes "fantasy_dashboard.html" in the same folder. Open it in any
browser, or upload it somewhere to share with your league. Re-run the
script any time to refresh the data (e.g. weekly, or set up a scheduled
task/cron job to regenerate it automatically).

Your espn_s2/SWID values stay on your own machine — they are never sent
anywhere except directly to ESPN's API.
"""

from espn_api.football import League
from datetime import datetime
import html

# ============ CONFIG — fill these in ============
LEAGUE_ID = 1234567          # your league ID
YEAR = 2026                  # season year
ESPN_S2 = "PASTE_ESPN_S2_HERE"
SWID = "PASTE_SWID_HERE"     # looks like {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
OUTPUT_FILE = "fantasy_dashboard.html"
RECENT_ACTIVITY_COUNT = 25
# ==================================================


def build_standings_rows(league):
    standings = sorted(league.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
    rows = []
    for rank, team in enumerate(standings, start=1):
        rows.append(f"""
        <tr>
          <td>{rank}</td>
          <td class="team-cell">
            {"<img src='" + html.escape(team.logo_url) + "' class='logo'>" if team.logo_url else ""}
            {html.escape(team.team_name)}
          </td>
          <td>{team.wins}-{team.losses}{f"-{team.ties}" if team.ties else ""}</td>
          <td>{team.points_for:.1f}</td>
          <td>{team.points_against:.1f}</td>
          <td>{team.streak_type} {team.streak_length}</td>
        </tr>""")
    return "\n".join(rows)


ACTION_LABELS = {
    "FA ADDED": "Free agent add",
    "WAIVER ADDED": "Waiver add",
    "DROPPED": "Dropped",
    "TRADE_SENT": "Traded away",
    "TRADE_RECEIVED": "Traded for",
}


def build_activity_rows(league):
    try:
        activity = league.recent_activity(size=RECENT_ACTIVITY_COUNT)
    except Exception:
        activity = []

    rows = []
    for act in activity:
        date_str = datetime.fromtimestamp(act.date / 1000).strftime("%b %d, %Y")
        for team, action, player, bid in act.actions:
            team_name = html.escape(team.team_name) if team and hasattr(team, "team_name") else "Unknown"
            player_name = player.name if hasattr(player, "name") else str(player)
            label = ACTION_LABELS.get(action, action.replace("_", " ").title())
            bid_str = f" (${bid})" if bid else ""
            rows.append(f"""
            <tr>
              <td>{date_str}</td>
              <td>{team_name}</td>
              <td class="action">{html.escape(label)}</td>
              <td>{html.escape(str(player_name))}{bid_str}</td>
            </tr>""")
    if not rows:
        rows.append("<tr><td colspan='4' class='empty'>No recent activity found.</td></tr>")
    return "\n".join(rows)


def fetch_player_rank_data(league):
    """
    Returns a dict: playerId -> {
        'position': 'RB',
        'draft_pos_rank': 15,      # e.g. the 15th RB taken in THIS draft
        'current_pos_rank': 10,    # ESPN's live positional ranking
        'delta': 5,                # positive = risen (better than drafted), negative = fallen
    }
    """
    if not league.draft:
        return {}

    player_ids = [pick.playerId for pick in league.draft if pick.playerId]
    if not player_ids:
        return {}

    # Single batched call for every drafted player's current info
    players = league.player_info(playerId=player_ids)
    if players is None:
        players = []
    elif not isinstance(players, list):
        players = [players]
    player_lookup = {p.playerId: p for p in players}

    # Walk the draft in actual draft order to work out each player's
    # "positional draft rank" — i.e. he was the Nth RB/WR/etc. taken.
    ordered_picks = sorted(league.draft, key=lambda p: (p.round_num, p.round_pick))
    position_counters = {}
    rank_data = {}
    for pick in ordered_picks:
        player = player_lookup.get(pick.playerId)
        if not player or not player.position:
            continue
        pos = player.position
        position_counters[pos] = position_counters.get(pos, 0) + 1
        draft_pos_rank = position_counters[pos]
        current_pos_rank = player.posRank
        delta = None
        if current_pos_rank and current_pos_rank > 0:
            delta = draft_pos_rank - current_pos_rank
        rank_data[pick.playerId] = {
            "position": pos,
            "draft_pos_rank": draft_pos_rank,
            "current_pos_rank": current_pos_rank,
            "delta": delta,
        }
    return rank_data


def delta_color(delta, max_delta=15):
    """Green the more a player has risen vs. draft slot, red the more they've fallen."""
    if delta is None:
        return "#2a3348", "#8a92a8"  # neutral gray, no data
    magnitude = min(abs(delta), max_delta) / max_delta  # 0..1
    intensity = 0.25 + 0.65 * magnitude  # keep even small moves visible
    if delta > 0:
        r, g, b = 34, 139, 34   # forest green
    elif delta < 0:
        r, g, b = 178, 34, 34   # firebrick red
    else:
        return "#2a3348", "#8a92a8"
    bg = f"rgba({r},{g},{b},{intensity:.2f})"
    border = f"rgba({r},{g},{b},{min(intensity + 0.25, 1):.2f})"
    return bg, border


def build_draft_board(league, rank_data):
    if not league.draft:
        return "<p class='empty'>No draft data available for this league/year yet.</p>"

    by_round = {}
    for pick in league.draft:
        by_round.setdefault(pick.round_num, []).append(pick)

    sections = []
    for round_num in sorted(by_round):
        picks = sorted(by_round[round_num], key=lambda p: p.round_pick)
        cells = []
        for pick in picks:
            team_name = html.escape(pick.team.team_name) if pick.team else "Unknown"
            player_name = html.escape(pick.playerName or "—")
            bid = f"<div class='bid'>${pick.bid_amount}</div>" if pick.bid_amount else ""

            info = rank_data.get(pick.playerId)
            bg, border = delta_color(info["delta"] if info else None)
            if info and info["delta"] is not None:
                pos = info["position"]
                arrow = "▲" if info["delta"] > 0 else ("▼" if info["delta"] < 0 else "–")
                rank_line = (f"<div class='rank-move'>{pos}{info['draft_pos_rank']} "
                             f"&rarr; {pos}{info['current_pos_rank']} {arrow}</div>")
            elif info:
                rank_line = f"<div class='rank-move'>{info['position']}{info['draft_pos_rank']} &rarr; n/a</div>"
            else:
                rank_line = ""

            cells.append(f"""
            <div class="draft-cell" style="background:{bg}; border-color:{border};">
              <div class="pick-num">{round_num}.{pick.round_pick}</div>
              <div class="player">{player_name}</div>
              <div class="drafted-by">{team_name}</div>
              {rank_line}
              {bid}
            </div>""")
        sections.append(f"""
        <div class="draft-round">
          <h3>Round {round_num}</h3>
          <div class="draft-grid">{''.join(cells)}</div>
        </div>""")

    legend = """
    <div class="legend">
      <span><i class="dot" style="background:rgba(34,139,34,0.7)"></i> Outperforming draft slot</span>
      <span><i class="dot" style="background:#2a3348"></i> No change / no data</span>
      <span><i class="dot" style="background:rgba(178,34,34,0.7)"></i> Underperforming draft slot</span>
    </div>"""
    return legend + "\n".join(sections)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{league_name} — League Dashboard</title>
<style>
  :root {{
    --bg: #0f1420;
    --panel: #171d2e;
    --border: #2a3348;
    --text: #e8ecf4;
    --muted: #8a92a8;
    --accent: #ff5a1f;
    --accent2: #3d8bfd;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
  }}
  header {{
    margin-bottom: 28px;
  }}
  h1 {{
    margin: 0 0 4px 0;
    font-size: 28px;
    letter-spacing: -0.5px;
  }}
  .subtitle {{
    color: var(--muted);
    font-size: 14px;
  }}
  nav {{
    display: flex;
    gap: 8px;
    margin: 20px 0 24px 0;
    border-bottom: 1px solid var(--border);
  }}
  nav button {{
    background: none;
    border: none;
    color: var(--muted);
    font-size: 15px;
    padding: 10px 16px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }}
  nav button.active {{
    color: var(--text);
    border-bottom-color: var(--accent);
  }}
  section {{ display: none; }}
  section.active {{ display: block; }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  th {{
    text-align: left;
    color: var(--muted);
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 10px;
    border-bottom: 1px solid var(--border);
  }}
  tr:last-child td {{ border-bottom: none; }}
  .team-cell {{ display: flex; align-items: center; gap: 8px; font-weight: 600; }}
  .logo {{ width: 22px; height: 22px; border-radius: 50%; }}
  .action {{ color: var(--accent2); }}
  .empty {{ color: var(--muted); text-align: center; padding: 24px; }}
  .draft-round h3 {{ color: var(--muted); font-size: 13px; text-transform: uppercase; margin: 20px 0 10px 0; }}
  .draft-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
  }}
  .draft-cell {{
    background: #1c2438;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    transition: transform 0.1s ease;
  }}
  .draft-cell:hover {{ transform: translateY(-2px); }}
  .pick-num {{ color: var(--accent); font-size: 12px; font-weight: 700; }}
  .player {{ font-weight: 600; margin: 4px 0 2px 0; font-size: 14px; }}
  .drafted-by {{ color: var(--muted); font-size: 12px; }}
  .rank-move {{ font-size: 11px; margin-top: 6px; color: var(--text); opacity: 0.9; }}
  .bid {{ color: var(--accent2); font-size: 12px; margin-top: 4px; }}
  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }}
  .legend .dot {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }}
  footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>{league_name}</h1>
  <div class="subtitle">{year} season · updated {updated}</div>
</header>

<nav>
  <button class="active" onclick="showTab('standings', this)">Standings</button>
  <button onclick="showTab('activity', this)">Recent Transactions</button>
  <button onclick="showTab('draft', this)">Draft Board</button>
</nav>

<section id="standings" class="active">
  <div class="panel">
    <table>
      <thead>
        <tr><th>#</th><th>Team</th><th>Record</th><th>PF</th><th>PA</th><th>Streak</th></tr>
      </thead>
      <tbody>
        {standings_rows}
      </tbody>
    </table>
  </div>
</section>

<section id="activity">
  <div class="panel">
    <table>
      <thead>
        <tr><th>Date</th><th>Team</th><th>Action</th><th>Player</th></tr>
      </thead>
      <tbody>
        {activity_rows}
      </tbody>
    </table>
  </div>
</section>

<section id="draft">
  <div class="panel">
    {draft_board}
  </div>
</section>

<footer>Generated locally from your ESPN league data. Not affiliated with ESPN.</footer>

<script>
function showTab(id, btn) {{
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>
"""


def main():
    print(f"Connecting to league {LEAGUE_ID} ({YEAR})...")
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

    league_name = getattr(league.settings, "name", "Fantasy Football League")

    print("Fetching current player rankings for draft comparison...")
    rank_data = fetch_player_rank_data(league)

    html_out = HTML_TEMPLATE.format(
        league_name=html.escape(league_name),
        year=YEAR,
        updated=datetime.now().strftime("%b %d, %Y %I:%M %p"),
        standings_rows=build_standings_rows(league),
        activity_rows=build_activity_rows(league),
        draft_board=build_draft_board(league, rank_data),
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Done. Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()