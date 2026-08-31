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
import os

# ============ CONFIG ============
# Values are read from environment variables first (used by the GitHub
# Actions workflow / GitHub Secrets), falling back to the literals below
# for local runs. If running locally, you can either fill in the literals
# below OR set the same-named environment variables instead — never commit
# real ESPN_S2/SWID values to a public repo.
def _env_or_default(name, default):
    """Falls back to default if the env var is missing OR set but blank."""
    value = os.environ.get(name)
    return value if value else default

LEAGUE_ID = int(_env_or_default("LEAGUE_ID", 1234567))
YEAR = int(_env_or_default("YEAR", 2026))
ESPN_S2 = _env_or_default("ESPN_S2", "PASTE_ESPN_S2_HERE")
SWID = _env_or_default("SWID", "PASTE_SWID_HERE")  # looks like {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
OUTPUT_FILE = "index.html"
RECENT_ACTIVITY_COUNT = 50  # how many waiver-wire moves to show on the Transactions tab
# The league's first season — used as the default start point for the
# History tab, all-time standings, and rivalry tracker. Override with the
# HISTORY_START_YEAR env var/secret if you only want a partial history.
HISTORY_START_YEAR = int(_env_or_default("HISTORY_START_YEAR", 2018))
# ==================================================


def compute_playoff_picture(league):
    """
    Approximates the current playoff picture from live standings math:
    who's in, who's clinched, who's on the bubble, who's mathematically
    eliminated. Returns None if the league doesn't expose the settings
    needed (playoff_team_count / reg_season_count).

    Seeding uses the same (wins, losses, points_for) ordering as the rest
    of the dashboard's standings tables. This can differ slightly from
    ESPN's own seed order in leagues with divisions or head-to-head
    tiebreakers, so treat seed # as indicative rather than official.

    Clinched/eliminated calls are intentionally conservative — they only
    fire when the math is airtight regardless of who wins which remaining
    games:
      - A team has CLINCHED if its current win total already beats every
        outside team's best-case (win-out) win total.
      - A team is ELIMINATED if its own best-case (win-out) win total
        can't reach the win total the last playoff-spot team has ALREADY
        secured (not their best case too, which would double-count
        uncertainty).
    Neither check accounts for head-to-head or points tiebreakers, so a
    team sitting exactly even with the cutoff will show as "in the hunt"
    rather than clinched/eliminated until the math is unambiguous.
    """
    settings = getattr(league, "settings", None)
    playoff_spots = getattr(settings, "playoff_team_count", 0) or 0
    reg_season_weeks = getattr(settings, "reg_season_count", None)
    if not playoff_spots or not reg_season_weeks or not league.teams:
        return None

    standings = sorted(league.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
    entries = []
    for seed, team in enumerate(standings, start=1):
        games_played = team.wins + team.losses + team.ties
        remaining = max(0, reg_season_weeks - games_played)
        entries.append({
            "seed": seed, "team": team, "wins": team.wins, "losses": team.losses,
            "ties": team.ties, "remaining": remaining,
            "max_possible_wins": team.wins + remaining,
        })

    in_the_hunt = entries[:playoff_spots]
    outside = entries[playoff_spots:]
    last_in = in_the_hunt[-1] if in_the_hunt else None

    for e in in_the_hunt:
        e["clinched"] = bool(outside) and all(e["wins"] > o["max_possible_wins"] for o in outside)
        e["status"] = "Clinched" if e["clinched"] else "In the hunt"

    for e in outside:
        e["eliminated"] = last_in is not None and e["max_possible_wins"] < last_in["wins"]
        e["status"] = "Eliminated" if e["eliminated"] else "On the bubble"
        # Standard "games back" of the last playoff spot.
        e["games_back"] = round(((last_in["wins"] - e["wins"]) + (e["losses"] - last_in["losses"])) / 2, 1) if last_in else 0

    return {
        "playoff_spots": playoff_spots,
        "in_the_hunt": in_the_hunt,
        "outside": outside,
        "season_over": all(e["remaining"] == 0 for e in entries),
    }


def build_playoff_picture_panel(league):
    """Renders the Playoff Picture standings sub-tab, or a placeholder if unavailable."""
    picture = compute_playoff_picture(league)
    if not picture:
        return '<p class="empty">Playoff settings unavailable for this league.</p>'

    def row(e, badge_class):
        team = e["team"]
        record = f"{e['wins']}-{e['losses']}" + (f"-{e['ties']}" if e['ties'] else "")
        detail = "Season complete" if e["remaining"] == 0 else f"{e['remaining']} games left"
        return f"""
        <div class="playoff-row">
          <div class="playoff-seed">{e['seed']}</div>
          <div class="team-cell">{team_cell_html(team.team_name, get_owner_name(team))}</div>
          <div class="playoff-record">{record}</div>
          <div class="playoff-detail">{detail}</div>
          <div class="playoff-badge {badge_class}">{e['status']}</div>
        </div>"""

    in_rows = "".join(row(e, "badge-clinched" if e["clinched"] else "badge-hunt") for e in picture["in_the_hunt"])
    out_rows = "".join(
        row(e, "badge-eliminated" if e["eliminated"] else "badge-bubble")
        for e in picture["outside"]
    ) or '<p class="empty">Every team in the league makes the playoffs.</p>'

    note = "The regular season has wrapped — this reflects the final playoff field." if picture["season_over"] else \
        "Updates automatically as more of the regular season completes."

    return f"""
    <p class="section-note">Top {picture['playoff_spots']} make the playoffs. Seeding follows the same win-loss-PF order as the standings table above; ESPN's own tiebreakers may differ slightly. {note}</p>
    <div class="playoff-grid">
      <div class="playoff-col">
        <h3 class="playoff-col-title">In the Playoffs</h3>
        {in_rows}
      </div>
      <div class="playoff-col">
        <h3 class="playoff-col-title">On the Outside</h3>
        {out_rows}
      </div>
    </div>"""


def build_standings_tabs(league, history):
    """
    Builds the Standings section as a set of sub-tabs: current season,
    each historical season fetched, and an All-Time cumulative view.
    Returns (sub_nav_html, sub_panels_html). Playoff Picture now lives
    under the Power Rankings tab instead of here.
    """
    season_standings = history.get("season_standings", {}) if history else {}
    all_time = history.get("all_time", {}) if history else {}

    sub_nav = ['<button class="subtab active" onclick="showSubTab(\'std-current\', this)">Current</button>']
    panels = [f"""
    <div id="std-current" class="subpanel active">
      <table>
        <thead><tr><th>#</th><th>Team</th><th>Record</th><th>Win%</th><th>PF</th><th>PA</th><th>Streak</th><th>Trend</th></tr></thead>
        <tbody>{build_standings_rows(league)}</tbody>
      </table>
    </div>"""]

    for year in sorted(season_standings.keys(), reverse=True):
        if year == league.year:
            continue  # current season already shown above
        rows = "".join(f"""
        <tr>
          <td>{s['rank']}</td>
          <td class="team-cell">{team_cell_html(s['name'], s.get('owner'))}</td>
          <td>{s['wins']}-{s['losses']}{f"-{s['ties']}" if s['ties'] else ""}</td>
          <td>{s['points_for']:.1f}</td>
          <td>{s['points_against']:.1f}</td>
        </tr>""" for s in season_standings[year])
        tab_id = f"std-{year}"
        sub_nav.append(f'<button class="subtab" onclick="showSubTab(\'{tab_id}\', this)">{year}</button>')
        panels.append(f"""
        <div id="{tab_id}" class="subpanel">
          <table>
            <thead><tr><th>#</th><th>Team</th><th>Record</th><th>PF</th><th>PA</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>""")

    if all_time:
        ranked = sorted(all_time.values(), key=lambda e: (-e["win_pct"], -e["points_for"]))
        rows = "".join(f"""
        <tr>
          <td>{i}</td>
          <td class="team-cell">{team_cell_html(e['name'], e.get('owner'))}</td>
          <td>{e['wins']}-{e['losses']}{f"-{e['ties']}" if e['ties'] else ""}</td>
          <td>{e['win_pct'] * 100:.1f}%</td>
          <td>{e['points_for']:.1f}</td>
          <td>{e['seasons']}</td>
        </tr>""" for i, e in enumerate(ranked, start=1))
        sub_nav.append('<button class="subtab" onclick="showSubTab(\'std-alltime\', this)">All-Time</button>')
        panels.append(f"""
        <div id="std-alltime" class="subpanel">
          <table>
            <thead><tr><th>#</th><th>Team</th><th>Record</th><th>Win%</th><th>Total PF</th><th>Seasons</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>""")

    return "".join(sub_nav), "".join(panels)


def _format_single_owner(o):
    """
    Extract a single manager's display name from one ESPN owner entry.
    Prefers firstName + lastName (since ESPN's 'displayName' field is often
    just the person's chosen username, e.g. "j_souza17") and falls back to
    displayName only if no first/last name is available. Returns None if
    nothing usable is found.
    """
    if not isinstance(o, dict):
        return None
    first = (o.get("firstName") or "").strip()
    last = (o.get("lastName") or "").strip()
    combined = f"{first} {last}".strip()
    if combined:
        return combined
    return o.get("displayName") or None


def get_owner_name(team):
    """
    Best-effort extraction of a team's manager name(s) from ESPN's raw
    'owners' data on the Team object. Some teams have co-managers, so this
    pulls the name for *every* manager listed (joined with ' & ') rather
    than just the first. Prefers firstName + lastName, since ESPN's
    'displayName' field is often just the person's chosen username
    (e.g. "j_souza17") rather than their actual name. Falls back to
    displayName only if no first/last name is available. Returns None if
    nothing usable is found, so callers can decide how to render that
    (rather than showing a fake placeholder).
    """
    owners = getattr(team, "owners", None) or []
    if not owners:
        return None
    names = []
    for o in owners:
        name = _format_single_owner(o)
        if name:
            names.append(name)
    if not names:
        return None
    return " & ".join(names)

def team_cell_html(name, owner=None):
    owner_html = f'<div class="owner-name">{html.escape(owner)}</div>' if owner else ""
    return f'<div class="team-name-main">{html.escape(name)}</div>{owner_html}'


def progress_bar_html(pct, color="var(--gradient)"):
    """Small inline horizontal bar for a 0-100 percentage value."""
    pct = max(0.0, min(100.0, pct))
    return (f"<div class='pbar'><div class='pbar-track'>"
            f"<div class='pbar-fill' style='width:{pct:.1f}%; background:{color};'></div>"
            f"</div><span class='pbar-label'>{pct:.0f}%</span></div>")


def sparkline_svg(values, width=90, height=26, color="var(--accent4)"):
    """
    Compact inline SVG line chart for a season's weekly scores — no
    charting library needed, just a hand-built polyline scaled to fit.
    Returns "" if there isn't enough data to draw a meaningful line.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pad = 3  # keep the line/dot from touching the SVG edges
    usable_h = height - pad * 2
    step = width / (len(vals) - 1)
    points = []
    for i, v in enumerate(vals):
        x = i * step
        y = pad + usable_h - ((v - lo) / span) * usable_h
        points.append((x, y))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    last_x, last_y = points[-1]
    # Color goes in style= rather than the stroke/fill attributes directly —
    # var() resolution inside raw SVG presentation attributes is
    # inconsistent across browsers, but is always reliable inside style=.
    return (f"<svg class='sparkline' viewBox='0 0 {width} {height}' preserveAspectRatio='none' "
            f"aria-hidden='true'>"
            f"<polyline points='{path}' style='fill:none; stroke:{color}; stroke-width:1.6; "
            f"stroke-linecap:round; stroke-linejoin:round;'/>"
            f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='2.2' style='fill:{color};'/>"
            f"</svg>")


def team_logo_html(team):
    """
    Renders a team's ESPN logo defensively. Real-world ESPN logo URLs can:
    - be protocol-relative ("//g.espncdn.com/...") which some contexts
      don't resolve correctly without an explicit scheme
    - occasionally 403/404 (stale URL, hotlink protection, or a team that
      never set a custom logo) — onerror hides the broken-image icon
      instead of showing a broken box
    - not be perfectly square — object-fit keeps the circular crop clean
    Returns "" if the team has no logo_url at all (nothing ESPN gave us to
    render).
    """
    url = (getattr(team, "logo_url", "") or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    return (f"<img src='{html.escape(url)}' class='logo' loading='lazy' "
            f"referrerpolicy='no-referrer' onerror=\"this.style.display='none'\">")


def build_standings_rows(league):
    standings = sorted(league.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
    rows = []
    for rank, team in enumerate(standings, start=1):
        logo = team_logo_html(team)
        games = team.wins + team.losses + team.ties
        win_pct = ((team.wins + 0.5 * team.ties) / games * 100) if games else 0
        # Only completed weeks (skip trailing zeros for weeks not yet
        # played) so the trend line doesn't nosedive to 0 at the end.
        completed_scores = [s for s in team.scores if s]
        trend = sparkline_svg(completed_scores)
        rows.append(f"""
        <tr>
          <td>{rank}</td>
          <td class="team-cell">
            <div class="team-cell-inner">
              {logo}
              {team_cell_html(team.team_name, get_owner_name(team))}
            </div>
          </td>
          <td>{team.wins}-{team.losses}{f"-{team.ties}" if team.ties else ""}</td>
          <td>{progress_bar_html(win_pct)}</td>
          <td>{team.points_for:.1f}</td>
          <td>{team.points_against:.1f}</td>
          <td>{team.streak_type} {team.streak_length}</td>
          <td>{trend}</td>
        </tr>""")
    return "\n".join(rows)


ACTION_LABELS = {
    "FA ADDED": "Free agent add",
    "WAIVER ADDED": "Waiver add",
    "DROPPED": "Dropped",
    "TRADE_SENT": "Traded away",
    "TRADE_RECEIVED": "Traded for",
}


WAIVER_ACTIONS = {"FA ADDED", "WAIVER ADDED", "DROPPED"}
TRADE_ACTIONS = {"TRADE_SENT", "TRADE_RECEIVED"}
TRADE_FETCH_SIZE = 500  # generous window so no trade this season gets pushed out by waiver-wire noise


def build_transactions_section(league):
    """
    Renders the Transactions tab: the 50 most recent waiver-wire moves
    (adds/drops) this season, plus every trade this season shown as a
    grouped card — all sides of the same trade together, not flattened
    into disconnected rows the way a flat activity feed would.
    """
    try:
        activity = league.recent_activity(size=TRADE_FETCH_SIZE)
    except Exception:
        activity = []

    waiver_entries = []
    trade_events = []
    for act in activity:
        date_str = datetime.fromtimestamp(act.date / 1000).strftime("%b %d, %Y")
        trade_actions_here = [a for a in act.actions if a[1] in TRADE_ACTIONS]
        if trade_actions_here:
            trade_events.append((date_str, trade_actions_here))
        for team, action, player, bid in act.actions:
            if action in WAIVER_ACTIONS:
                waiver_entries.append((date_str, team, action, player, bid))

    waiver_entries = waiver_entries[:RECENT_ACTIVITY_COUNT]
    waiver_rows = []
    for date_str, team, action, player, bid in waiver_entries:
        team_name = html.escape(team.team_name) if team and hasattr(team, "team_name") else "Unknown"
        player_name = player.name if hasattr(player, "name") else str(player)
        label = ACTION_LABELS.get(action, action.replace("_", " ").title())
        bid_str = f" (${bid})" if bid else ""
        waiver_rows.append(f"""
        <tr>
          <td>{date_str}</td>
          <td>{team_name}</td>
          <td class="action">{html.escape(label)}</td>
          <td>{html.escape(str(player_name))}{bid_str}</td>
        </tr>""")
    if not waiver_rows:
        waiver_rows.append("<tr><td colspan='4' class='empty'>No waiver activity found this season.</td></tr>")

    trade_cards = []
    for date_str, actions_here in trade_events:
        by_team = {}
        for team, action, player, bid in actions_here:
            team_name = html.escape(team.team_name) if team and hasattr(team, "team_name") else "Unknown"
            player_name = html.escape(str(player.name if hasattr(player, "name") else player))
            by_team.setdefault(team_name, {"gets": [], "gives": []})
            if action == "TRADE_RECEIVED":
                by_team[team_name]["gets"].append(player_name)
            elif action == "TRADE_SENT":
                by_team[team_name]["gives"].append(player_name)
        sides = "".join(
            f"""<div class="matchup-team"><div class="team-name-main">{name}</div>
                <div class="owner-name">Gets: {', '.join(info['gets']) or '&mdash;'}</div></div>"""
            for name, info in by_team.items()
        )
        trade_cards.append(f"""
        <div class="matchup-card">
          <div class="section-note" style="margin-bottom:8px;">{date_str}</div>
          <div class="matchup-teams">{sides}</div>
        </div>""")
    if not trade_cards:
        trade_cards.append("<p class='empty'>No trades found this season.</p>")

    return f"""
    <h2 class="section-title">Waiver Wire</h2>
    <p class="section-note">Most recent {RECENT_ACTIVITY_COUNT} adds/drops this season.</p>
    <table>
      <thead><tr><th>Date</th><th>Team</th><th>Action</th><th>Player</th></tr></thead>
      <tbody>{"".join(waiver_rows)}</tbody>
    </table>

    <h2 class="section-title" style="margin-top:28px;">Trades</h2>
    <p class="section-note">Every trade this season.</p>
    <div class="matchup-list">{"".join(trade_cards)}</div>
    """


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


def delta_color(delta, dead_zone=3, max_delta=15):
    """
    Green the more a player has risen vs. draft slot, red the more they've
    fallen. Moves of `dead_zone` spots or fewer are treated as noise and
    stay neutral; the gradient only ramps up beyond that.
    """
    if delta is None or abs(delta) <= dead_zone:
        return "#2a3348", "#8a92a8"  # neutral gray, no meaningful change
    span = max(max_delta - dead_zone, 1)
    magnitude = min(abs(delta) - dead_zone, span) / span  # 0..1
    intensity = 0.25 + 0.65 * magnitude
    if delta > 0:
        r, g, b = 34, 139, 34   # forest green
    else:
        r, g, b = 178, 34, 34   # firebrick red
    bg = f"rgba({r},{g},{b},{intensity:.2f})"
    border = f"rgba({r},{g},{b},{min(intensity + 0.25, 1):.2f})"
    return bg, border


def build_matchups(league):
    """Builds the weekly matchups section: projected scores + a generated outlook."""
    week = league.current_week
    try:
        matchups = league.box_scores(week)
    except Exception:
        matchups = []

    if not matchups:
        return "<p class='empty'>No matchup data available for this week yet.</p>", week

    cards = []
    for m in matchups:
        if not m.home_team or not m.away_team:
            bye_team = m.home_team or m.away_team
            if bye_team:
                cards.append(f"""
                <div class="matchup-card bye">
                  <div class="bye-label">BYE WEEK</div>
                  <div class="team-name">{html.escape(bye_team.team_name)}</div>
                </div>""")
            continue

        home, away = m.home_team, m.away_team
        home_proj = round(m.home_projected, 1)
        away_proj = round(m.away_projected, 1)
        favorite, underdog, fav_proj, dog_proj = (
            (home, away, home_proj, away_proj) if home_proj >= away_proj
            else (away, home, away_proj, home_proj)
        )
        outlook = generate_matchup_outlook(favorite, underdog, fav_proj, dog_proj)

        cards.append(f"""
        <div class="matchup-card">
          <div class="matchup-teams">
            <div class="matchup-team">
              <div class="team-name">{html.escape(away.team_name)}</div>
              <div class="team-record">{away.wins}-{away.losses}{f"-{away.ties}" if away.ties else ""}</div>
              <div class="proj-score">{away_proj}</div>
            </div>
            <div class="vs">@</div>
            <div class="matchup-team">
              <div class="team-name">{html.escape(home.team_name)}</div>
              <div class="team-record">{home.wins}-{home.losses}{f"-{home.ties}" if home.ties else ""}</div>
              <div class="proj-score">{home_proj}</div>
            </div>
          </div>
          <p class="outlook">{html.escape(outlook)}</p>
        </div>""")

    return "\n".join(cards), week


def generate_matchup_outlook(favorite, underdog, fav_proj, dog_proj):
    """Generates a short, varied narrative blurb for a matchup using
    deterministic-but-varied templates based on the matchup's own numbers
    (no external calls — keeps this fast and free to regenerate)."""
    gap = round(fav_proj - dog_proj, 1)
    fav_name = favorite.team_name
    dog_name = underdog.team_name

    # Pick a template bucket based on projected point gap and each team's
    # current form, seeded by team names + week so it's stable per matchup
    # but still varies week to week and across pairings.
    seed = sum(ord(c) for c in (fav_name + dog_name)) + int(fav_proj * 10)
    variants_close = [
        f"This one's a coin flip. {fav_name} is given the slimmest of edges over {dog_name}, "
        f"projected to win by just {gap} points — a single big play could flip this.",
        f"{fav_name} and {dog_name} are neck and neck heading in, separated by only {gap} "
        f"projected points. Expect this to come down to the last game on the board.",
        f"Too close to call. {fav_name} holds a razor-thin projected edge over {dog_name} "
        f"({gap} points), so bench decisions and Monday night performances could decide it.",
    ]
    variants_moderate = [
        f"{fav_name} enters as the favorite over {dog_name}, projected to win by about {gap} "
        f"points. Not a lock, but {dog_name} will need some breakout performances to keep pace.",
        f"On paper, {fav_name} has the edge here, out-projecting {dog_name} by {gap} points. "
        f"{dog_name} isn't out of it, but they're chasing points from the jump.",
        f"{fav_name} looks like the safer bet against {dog_name} this week, favored by roughly "
        f"{gap} points — though fantasy football has a way of humbling favorites.",
    ]
    variants_blowout = [
        f"{fav_name} is projected to run away with this one, out-scoring {dog_name} by a "
        f"lopsided {gap} points. {dog_name} will need a near-perfect week and some help from "
        f"the projections being wrong.",
        f"This has blowout potential — {fav_name} is favored by {gap} points over {dog_name}. "
        f"Barring injuries or busts, {dog_name} is fighting an uphill battle.",
        f"The numbers aren't kind to {dog_name} here, with {fav_name} projected to win by "
        f"{gap} points. A statement upset would be one for the ages.",
    ]

    if gap < 8:
        pool = variants_close
    elif gap < 20:
        pool = variants_moderate
    else:
        pool = variants_blowout

    return pool[seed % len(pool)]


def _completed_week_indices(league):
    """
    Index positions (0-based) of REGULAR SEASON weeks that have a decided
    outcome for at least one team. Deliberately excludes playoff weeks:
    once playoffs start, not every team has a real matchup each week
    (some are eliminated, some get a bye, brackets split into
    championship/consolation groups), so the "compare your score against
    every other team this week" methodology used by Power Rankings and the
    Luck Index would be comparing against a shrinking, non-representative
    slice of the league rather than the full field. Capping at
    league.settings.reg_season_count keeps every computed week apples-to-
    apples across the whole league.
    """
    reg_season_weeks = getattr(getattr(league, "settings", None), "reg_season_count", None)
    max_len = max((len(t.outcomes) for t in league.teams), default=0)
    if reg_season_weeks:
        max_len = min(max_len, reg_season_weeks)
    completed = []
    for i in range(max_len):
        if any(i < len(t.outcomes) and t.outcomes[i] in ("W", "L", "T") for t in league.teams):
            completed.append(i)
    return completed


def compute_power_rankings(league):
    """
    Blends season scoring average, average margin of victory, and recent-form
    (last 3 completed weeks) into a single composite score per team. This is
    NOT the same as the win/loss standings — it's meant to surface teams that
    are playing better/worse than their record suggests.
    """
    completed = _completed_week_indices(league)
    if not completed:
        return []

    recent = completed[-3:]
    raw = []
    for team in league.teams:
        pts = [team.scores[i] for i in completed if i < len(team.scores)]
        margins = [team.mov[i] for i in completed if i < len(team.mov)]
        recent_pts = [team.scores[i] for i in recent if i < len(team.scores)]
        avg_pts = sum(pts) / len(pts) if pts else 0
        avg_margin = sum(margins) / len(margins) if margins else 0
        avg_recent = sum(recent_pts) / len(recent_pts) if recent_pts else avg_pts
        raw.append({"team": team, "avg_pts": avg_pts, "avg_margin": avg_margin, "avg_recent": avg_recent})

    def normalize(values):
        lo, hi = min(values), max(values)
        span = hi - lo
        return [50.0 if span == 0 else (v - lo) / span * 100 for v in values]

    norm_pts = normalize([r["avg_pts"] for r in raw])
    norm_margin = normalize([r["avg_margin"] for r in raw])
    norm_recent = normalize([r["avg_recent"] for r in raw])

    for i, r in enumerate(raw):
        r["power_score"] = round(0.45 * norm_pts[i] + 0.25 * norm_margin[i] + 0.30 * norm_recent[i], 1)

    raw.sort(key=lambda r: -r["power_score"])

    # Compare to actual standings rank so we can show "overrated"/"underrated" moves
    standings_order = sorted(league.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
    standings_rank = {t.team_id: i + 1 for i, t in enumerate(standings_order)}

    results = []
    for power_rank, r in enumerate(raw, start=1):
        team = r["team"]
        std_rank = standings_rank.get(team.team_id, power_rank)
        results.append({
            "team": team,
            "power_rank": power_rank,
            "power_score": r["power_score"],
            "avg_pts": round(r["avg_pts"], 1),
            "avg_margin": round(r["avg_margin"], 1),
            "standings_rank": std_rank,
            "rank_delta": std_rank - power_rank,  # positive = power ranking thinks they're better than their record
        })
    return results


def compute_luck_index(league):
    """
    'All-play' luck: each week, compares a team's score against every other
    team's score that week (not just their actual opponent) to get an
    expected win rate. Comparing that to their real win rate shows who's
    over/under-performing their scoring.

    Both sides of that comparison MUST cover the exact same set of weeks or
    the "luck" delta is meaningless. _completed_week_indices() already
    restricts 'completed' to the regular season. actual_pct is computed
    the same way — directly from each team's outcomes over those same
    weeks — rather than from team.wins/team.losses/team.ties, since ESPN's
    API labels those fields "overall" and they can include playoff-bracket
    results in leagues that count playoff games toward the record. Using
    the season-long total there while expected_pct only covers the regular
    season would silently compare two different samples.
    """
    completed = _completed_week_indices(league)
    teams = league.teams
    if not completed or len(teams) < 2:
        return []

    all_play_pct = {t.team_id: [] for t in teams}
    for i in completed:
        week_scores = {t.team_id: t.scores[i] for t in teams if i < len(t.scores) and t.scores[i] is not None}
        n = len(week_scores)
        if n < 2:
            continue
        for tid, score in week_scores.items():
            wins = sum(1 for oid, oscore in week_scores.items() if oid != tid and score > oscore)
            ties = sum(1 for oid, oscore in week_scores.items() if oid != tid and score == oscore)
            all_play_pct[tid].append((wins + 0.5 * ties) / (n - 1))

    results = []
    for team in teams:
        pct_list = all_play_pct.get(team.team_id, [])
        if not pct_list:
            continue
        expected_pct = sum(pct_list) / len(pct_list)

        # Actual record over the SAME weeks used above — not team.wins/losses.
        reg_outcomes = [team.outcomes[i] for i in completed if i < len(team.outcomes)]
        w = reg_outcomes.count("W")
        l = reg_outcomes.count("L")
        t_ = reg_outcomes.count("T")
        games = w + l + t_
        actual_pct = (w + 0.5 * t_) / games if games else 0

        luck = actual_pct - expected_pct
        results.append({
            "team": team,
            "actual_pct": round(actual_pct * 100, 1),
            "expected_pct": round(expected_pct * 100, 1),
            "luck": round(luck * 100, 1),
        })

    # Label relative to this league's own spread rather than a fixed
    # +/-12% cutoff. A fixed threshold looks fine for a big, high-variance
    # league but with a typical 10-12 team league over a single season the
    # actual spread of luck values is usually much narrower than that, so
    # nearly everyone landed in "About Right" regardless of how lucky/
    # unlucky they actually were relative to their own league-mates.
    # Instead, rank teams by luck and label the top/bottom quarter (by
    # count) as Lucky/Unlucky — always proportional to the number of teams,
    # whatever the raw spread of values happens to be this season.
    n = len(results)
    if n >= 4:
        by_luck = sorted(results, key=lambda r: -r["luck"])
        cutoff = max(1, round(n * 0.25))
        lucky_ids = {r["team"].team_id for r in by_luck[:cutoff]}
        unlucky_ids = {r["team"].team_id for r in by_luck[-cutoff:]}
        for r in results:
            tid = r["team"].team_id
            if tid in lucky_ids and r["luck"] > 0:
                r["label"] = "Lucky"
            elif tid in unlucky_ids and r["luck"] < 0:
                r["label"] = "Unlucky"
            else:
                r["label"] = "About Right"
    else:
        # Too few teams for quartile ranking to mean anything — fall back
        # to a fixed threshold.
        for r in results:
            if r["luck"] > 12:
                r["label"] = "Lucky"
            elif r["luck"] < -12:
                r["label"] = "Unlucky"
            else:
                r["label"] = "About Right"
    results.sort(key=lambda r: -r["luck"])
    return results


def _fetch_championship_score(lg, champion_id, runnerup_id):
    """
    Best-effort lookup of the final score of a season's championship game.
    Tries the handful of weeks just after the regular season ends and
    looks for the WINNERS_BRACKET matchup between the season's #1 and #2
    finishers. Returns (champion_score, runnerup_score), or None if it
    can't be pinned down (older seasons, bracket quirks, API gaps) — the
    trophy case still renders fine without it.
    """
    if champion_id is None or runnerup_id is None:
        return None
    reg_weeks = getattr(getattr(lg, "settings", None), "reg_season_count", None) or 0
    for week in range(reg_weeks + 1, reg_weeks + 6):
        try:
            matchups = lg.box_scores(week)
        except Exception:
            continue
        for m in matchups:
            if getattr(m, "matchup_type", None) != "WINNERS_BRACKET":
                continue
            home_id = getattr(m.home_team, "team_id", None)
            away_id = getattr(m.away_team, "team_id", None)
            if {home_id, away_id} != {champion_id, runnerup_id}:
                continue
            if home_id == champion_id:
                return round(m.home_score, 1), round(m.away_score, 1)
            return round(m.away_score, 1), round(m.home_score, 1)
    return None


def _update_streak(state, team_id, outcome, year, week, name, owner):
    """
    Rolling win/loss streak tracker keyed by team_id. Called once per
    completed game in ASCENDING year order. Streaks are contained to a
    single season — crossing into a new year always breaks a streak in
    progress, even if the outcome type would otherwise have continued it,
    so "longest win/loss streak" reflects one season's run rather than one
    stitched across a season boundary. A tie also breaks both a win and a
    loss streak. Records the best win streak and best loss streak seen so
    far for that team, each with the year/week span it covers.
    """
    s = state.setdefault(team_id, {
        "current_type": None, "current_len": 0, "current_start": None,
        "best_win": None, "best_loss": None, "last_year": None,
    })
    if s["last_year"] is not None and year != s["last_year"]:
        s["current_type"], s["current_len"], s["current_start"] = None, 0, None
    s["last_year"] = year
    if outcome == "T":
        s["current_type"], s["current_len"], s["current_start"] = None, 0, None
        return
    if outcome == s["current_type"]:
        s["current_len"] += 1
    else:
        s["current_type"] = outcome
        s["current_len"] = 1
        s["current_start"] = (year, week)
    entry = {
        "length": s["current_len"], "team": name, "owner": owner,
        "start_year": s["current_start"][0], "start_week": s["current_start"][1],
        "end_year": year, "end_week": week,
    }
    key = "best_win" if outcome == "W" else "best_loss"
    if s[key] is None or entry["length"] > s[key]["length"]:
        s[key] = entry


def fetch_historical_data(current_league, start_year, end_year):
    """
    Walks each season from start_year..end_year (inclusive), fetching a
    League() instance for every year except the current one (already have
    that). Extracts:
      - champions: list of dicts (year, team, owner, runnerup_team,
        runnerup_owner, score, record) for completed seasons, newest first
      - head_to_head: {frozenset({id_a, id_b}): {'meetings', 'wins': {}, 'points': {}}}
      - name_by_id / owner_by_id: best-known display name/owner for each team_id
      - season_standings: {year: [ {team_id, name, owner, wins, losses, ties,
        points_for, points_against, rank}, ... ]} sorted best-to-worst
      - all_time: {team_id: {name, owner, wins, losses, ties, points_for,
        points_against, seasons}} accumulated across every fetched year
      - records: league records book — highest/lowest single-week score,
        biggest blowout, closest game, longest win/loss streak, most
        points scored in a loss — computed across every fetched season

    Any year that fails to fetch (league didn't exist yet, network hiccup,
    etc.) is skipped rather than aborting the whole run.
    """
    champions = []
    head_to_head = {}
    name_by_id = {t.team_id: t.team_name for t in current_league.teams}
    owner_by_id = {t.team_id: get_owner_name(t) for t in current_league.teams}
    season_standings = {}
    all_time = {}
    records = {
        "highest_score": None, "lowest_score": None, "biggest_blowout": None,
        "closest_game": None, "most_points_loss": None,
    }
    streak_state = {}

    for year in range(start_year, end_year + 1):
        if year == current_league.year:
            lg = current_league
        else:
            try:
                print(f"  Fetching {year} season...")
                lg = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
            except Exception as e:
                print(f"  Skipping {year}: {e}")
                continue

        if not lg.teams:
            continue

        for team in lg.teams:
            name_by_id[team.team_id] = team.team_name
            owner = get_owner_name(team)
            if owner:
                owner_by_id[team.team_id] = owner

        if year != current_league.year:
            finished = [t for t in lg.teams if getattr(t, "final_standing", 0) == 1]
            if finished:
                champ_team = finished[0]
                runnerup_list = [t for t in lg.teams if getattr(t, "final_standing", 0) == 2]
                runnerup_team = runnerup_list[0] if runnerup_list else None
                score = _fetch_championship_score(
                    lg, champ_team.team_id, runnerup_team.team_id if runnerup_team else None
                )
                champions.append({
                    "year": year,
                    "team": champ_team.team_name,
                    "owner": get_owner_name(champ_team),
                    "runnerup_team": runnerup_team.team_name if runnerup_team else None,
                    "runnerup_owner": get_owner_name(runnerup_team) if runnerup_team else None,
                    "record": f"{champ_team.wins}-{champ_team.losses}" + (f"-{champ_team.ties}" if champ_team.ties else ""),
                    "score": score,
                })

        # Per-season standings: always sort by actual regular-season record
        # (wins, then fewest losses, then points-for as a tiebreaker) — not
        # by ESPN's final_standing, which reflects PLAYOFF results and can
        # rank a team below one it out-won during the season (e.g. a #1
        # seed that lost early vs. a lower seed that made a title run).
        # The League Champions section already shows playoff winners
        # separately, so this table stays a true win-loss standings.
        ordered = sorted(lg.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
        season_standings[year] = [{
            "team_id": t.team_id,
            "name": t.team_name,
            "owner": get_owner_name(t),
            "wins": t.wins, "losses": t.losses, "ties": t.ties,
            "points_for": t.points_for, "points_against": t.points_against,
            "rank": i + 1,
        } for i, t in enumerate(ordered)]

        for t in lg.teams:
            entry = all_time.setdefault(t.team_id, {
                "name": t.team_name, "owner": None, "wins": 0, "losses": 0, "ties": 0,
                "points_for": 0.0, "points_against": 0.0, "seasons": 0,
            })
            entry["name"] = t.team_name  # keep most recent name
            owner = get_owner_name(t)
            if owner:
                entry["owner"] = owner
            entry["wins"] += t.wins
            entry["losses"] += t.losses
            entry["ties"] += t.ties
            entry["points_for"] += t.points_for
            entry["points_against"] += t.points_against
            entry["seasons"] += 1

        for team in lg.teams:
            team_owner = get_owner_name(team)
            for week_idx, (opp, score, outcome) in enumerate(zip(team.schedule, team.scores, team.outcomes)):
                if outcome not in ("W", "L", "T"):
                    continue
                if not opp or getattr(opp, "team_id", None) in (None, team.team_id):
                    continue  # bye week
                week_num = week_idx + 1
                opp_score = opp.scores[week_idx] if week_idx < len(opp.scores) else None

                _update_streak(streak_state, team.team_id, outcome, year, week_num, team.team_name, team_owner)

                if score is not None:
                    if records["highest_score"] is None or score > records["highest_score"]["value"]:
                        records["highest_score"] = {"value": score, "team": team.team_name, "owner": team_owner, "year": year, "week": week_num}
                    if records["lowest_score"] is None or score < records["lowest_score"]["value"]:
                        records["lowest_score"] = {"value": score, "team": team.team_name, "owner": team_owner, "year": year, "week": week_num}
                    if outcome == "L" and (records["most_points_loss"] is None or score > records["most_points_loss"]["value"]):
                        records["most_points_loss"] = {"value": score, "team": team.team_name, "owner": team_owner, "year": year, "week": week_num}

                # Game-level records (blowout/closest) are symmetric across both
                # sides of the matchup, so only compute them from one side
                # (lower team_id) to avoid recording the same game twice.
                if opp_score is not None and score is not None and team.team_id < opp.team_id:
                    margin = round(abs(score - opp_score), 1)
                    if score >= opp_score:
                        winner, loser, w_score, l_score = team, opp, score, opp_score
                    else:
                        winner, loser, w_score, l_score = opp, team, opp_score, score
                    game = {
                        "margin": margin, "winner": winner.team_name, "winner_owner": get_owner_name(winner),
                        "loser": loser.team_name, "loser_owner": get_owner_name(loser),
                        "winner_score": w_score, "loser_score": l_score, "year": year, "week": week_num,
                        "tie": outcome == "T",
                    }
                    if records["biggest_blowout"] is None or margin > records["biggest_blowout"]["margin"]:
                        records["biggest_blowout"] = game
                    if records["closest_game"] is None or margin < records["closest_game"]["margin"]:
                        records["closest_game"] = game

                key = frozenset({team.team_id, opp.team_id})
                h2h = head_to_head.setdefault(key, {"meetings": 0, "wins": {}, "points": {}})
                h2h["meetings"] += 1  # counted from both sides below; halved at the end
                h2h["wins"].setdefault(team.team_id, 0)
                h2h["points"].setdefault(team.team_id, 0.0)
                if outcome == "W":
                    h2h["wins"][team.team_id] += 1
                elif outcome == "T":
                    h2h["wins"][team.team_id] += 0.5
                h2h["points"][team.team_id] += score or 0

    for h2h in head_to_head.values():
        h2h["meetings"] //= 2

    for tid, entry in all_time.items():
        games = entry["wins"] + entry["losses"] + entry["ties"]
        entry["win_pct"] = (entry["wins"] + 0.5 * entry["ties"]) / games if games else 0

    # Roll up the per-team streak tracking into single league-wide records.
    for s in streak_state.values():
        if s["best_win"] and (records.get("longest_win_streak") is None or s["best_win"]["length"] > records["longest_win_streak"]["length"]):
            records["longest_win_streak"] = s["best_win"]
        if s["best_loss"] and (records.get("longest_loss_streak") is None or s["best_loss"]["length"] > records["longest_loss_streak"]["length"]):
            records["longest_loss_streak"] = s["best_loss"]
    records.setdefault("longest_win_streak", None)
    records.setdefault("longest_loss_streak", None)

    champions.sort(key=lambda c: -c["year"])
    return {
        "champions": champions,
        "head_to_head": head_to_head,
        "name_by_id": name_by_id,
        "owner_by_id": owner_by_id,
        "season_standings": season_standings,
        "all_time": all_time,
        "records": records,
    }


def _streak_span_label(entry):
    """Human-readable year/week span for a streak record dict."""
    if entry["start_year"] == entry["end_year"]:
        if entry["start_week"] == entry["end_week"]:
            return f"Week {entry['start_week']}, {entry['start_year']}"
        return f"Weeks {entry['start_week']}&ndash;{entry['end_week']}, {entry['start_year']}"
    return f"{entry['start_year']} Wk{entry['start_week']} &ndash; {entry['end_year']} Wk{entry['end_week']}"


def build_trophy_case_section(champions):
    """
    Renders the League Champions table as a proper trophy wall: one card
    per title, with the champion's record and (when it could be found)
    the actual championship-game score against the runner-up.
    """
    if not champions:
        return """
        <h2 class="section-title">Hall of Fame &middot; Trophy Case</h2>
        <p class="section-note">No completed prior seasons found yet.</p>"""

    cards = []
    for c in champions:
        score = c.get("score")
        matchup_line = ""
        if c.get("runnerup_team"):
            if score:
                champ_score, runnerup_score = score
                matchup_line = f"<div class='trophy-score'>{champ_score:.1f} &ndash; {runnerup_score:.1f} <span class='trophy-vs'>vs {html.escape(c['runnerup_team'])}</span></div>"
            else:
                matchup_line = f"<div class='trophy-vs'>def. {html.escape(c['runnerup_team'])}</div>"
        cards.append(f"""
        <div class="trophy-card">
          <div class="trophy-year">{c['year']}</div>
          <div class="trophy-icon">&#127942;</div>
          {team_cell_html(c['team'], c.get('owner'))}
          <div class="trophy-record">{c.get('record', '')}</div>
          {matchup_line}
        </div>""")

    return f"""
    <h2 class="section-title">Hall of Fame &middot; Trophy Case</h2>
    <p class="section-note">Every champion from every season fetched, in one wall.</p>
    <div class="trophy-wall">{"".join(cards)}</div>"""


def build_records_book_section(records):
    """Renders the League Records Book: pure all-time trivia, no strategic angle."""
    if not records or not records.get("highest_score"):
        return """
        <h2 class="section-title" style="margin-top:28px;">League Records Book</h2>
        <p class="section-note">Not enough historical data yet to compute records.</p>"""

    cards = []

    hs = records["highest_score"]
    cards.append(f"""
    <div class="record-card">
      <div class="record-label">&#128293; Highest Single-Week Score</div>
      <div class="record-value">{hs['value']:.1f}</div>
      {team_cell_html(hs['team'], hs.get('owner'))}
      <div class="record-context">Week {hs['week']}, {hs['year']}</div>
    </div>""")

    ls = records["lowest_score"]
    cards.append(f"""
    <div class="record-card">
      <div class="record-label">&#128703; Toilet Bowl (Lowest Score)</div>
      <div class="record-value">{ls['value']:.1f}</div>
      {team_cell_html(ls['team'], ls.get('owner'))}
      <div class="record-context">Week {ls['week']}, {ls['year']}</div>
    </div>""")

    bo = records.get("biggest_blowout")
    if bo:
        cards.append(f"""
        <div class="record-card">
          <div class="record-label">&#128165; Biggest Blowout</div>
          <div class="record-value">{bo['margin']:.1f} <span class="record-unit">pt margin</span></div>
          {team_cell_html(bo['winner'], bo.get('winner_owner'))}
          <div class="record-context">beat {html.escape(bo['loser'])} {bo['winner_score']:.1f}&ndash;{bo['loser_score']:.1f} &middot; Week {bo['week']}, {bo['year']}</div>
        </div>""")

    cg = records.get("closest_game")
    if cg:
        tie_note = " (Tie)" if cg.get("tie") else ""
        verb = "tied" if cg.get("tie") else "edged"
        cards.append(f"""
        <div class="record-card">
          <div class="record-label">&#127919; Closest Game{tie_note}</div>
          <div class="record-value">{cg['margin']:.1f} <span class="record-unit">pt margin</span></div>
          {team_cell_html(cg['winner'], cg.get('winner_owner'))}
          <div class="record-context">{verb} {html.escape(cg['loser'])} {cg['winner_score']:.1f}&ndash;{cg['loser_score']:.1f} &middot; Week {cg['week']}, {cg['year']}</div>
        </div>""")

    ws = records.get("longest_win_streak")
    if ws:
        cards.append(f"""
        <div class="record-card">
          <div class="record-label">&#128200; Longest Win Streak</div>
          <div class="record-value">{ws['length']} <span class="record-unit">games</span></div>
          {team_cell_html(ws['team'], ws.get('owner'))}
          <div class="record-context">{_streak_span_label(ws)}</div>
        </div>""")

    lsk = records.get("longest_loss_streak")
    if lsk:
        cards.append(f"""
        <div class="record-card">
          <div class="record-label">&#128201; Longest Losing Streak</div>
          <div class="record-value">{lsk['length']} <span class="record-unit">games</span></div>
          {team_cell_html(lsk['team'], lsk.get('owner'))}
          <div class="record-context">{_streak_span_label(lsk)}</div>
        </div>""")

    mpl = records.get("most_points_loss")
    if mpl:
        cards.append(f"""
        <div class="record-card">
          <div class="record-label">&#128148; Most Points in a Loss</div>
          <div class="record-value">{mpl['value']:.1f}</div>
          {team_cell_html(mpl['team'], mpl.get('owner'))}
          <div class="record-context">Week {mpl['week']}, {mpl['year']}</div>
        </div>""")

    return f"""
    <h2 class="section-title" style="margin-top:28px;">League Records Book</h2>
    <p class="section-note">All-time records across every season fetched. Pure trivia &mdash; bragging rights only.</p>
    <div class="record-grid">{"".join(cards)}</div>"""


def build_history_section(history, current_year, top_rivalries=8):
    champions = history["champions"]
    h2h = history["head_to_head"]
    names = history["name_by_id"]

    champions_html = build_trophy_case_section(champions)
    records_html = build_records_book_section(history.get("records"))

    if h2h:
        ranked_pairs = sorted(h2h.items(), key=lambda kv: -kv[1]["meetings"])[:top_rivalries]
        rivalry_cards = []
        for pair, data in ranked_pairs:
            ids = list(pair)
            if len(ids) < 2:
                continue
            id_a, id_b = ids[0], ids[1]
            name_a = names.get(id_a, f"Team {id_a}")
            name_b = names.get(id_b, f"Team {id_b}")
            wins_a = data["wins"].get(id_a, 0)
            wins_b = data["wins"].get(id_b, 0)
            pts_a = round(data["points"].get(id_a, 0), 1)
            pts_b = round(data["points"].get(id_b, 0), 1)
            rivalry_cards.append(f"""
            <div class="rivalry-card">
              <div class="rivalry-meetings">{data['meetings']} all-time meetings</div>
              <div class="rivalry-matchup">
                <div class="rivalry-team">
                  <div class="team-name">{html.escape(name_a)}</div>
                  <div class="rivalry-record">{wins_a}-{wins_b}</div>
                  <div class="rivalry-points">{pts_a} pts total</div>
                </div>
                <div class="vs">vs</div>
                <div class="rivalry-team">
                  <div class="team-name">{html.escape(name_b)}</div>
                  <div class="rivalry-record">{wins_b}-{wins_a}</div>
                  <div class="rivalry-points">{pts_b} pts total</div>
                </div>
              </div>
            </div>""")
        rivalry_html = f"""
        <h2 class="section-title" style="margin-top:28px;">Rivalry Tracker</h2>
        <p class="section-note">All-time head-to-head records across every season fetched.</p>
        <div class="rivalry-grid">{"".join(rivalry_cards)}</div>"""
    else:
        rivalry_html = """
        <h2 class="section-title" style="margin-top:28px;">Rivalry Tracker</h2>
        <p class="section-note">No head-to-head history found yet.</p>"""

    return champions_html + records_html + rivalry_html


def compute_prediction_accuracy(league):
    """
    Compares each team's actual weekly score to ESPN's own projection for
    that week. Reveals who consistently outplays projections vs. who
    underperforms them.

    The projection itself checks out: espn_api sources it from that
    specific week's pre-game starter-only projection (not a live-
    recalculated value), matching the same starters-only scope as the
    actual score — an apples-to-apples comparison.

    Restricted to regular-season weeks only, for the same reason Power
    Rankings and the Luck Index are: playoff weeks have byes, a
    championship/consolation split, and sometimes less effort from
    eliminated teams, all of which would distort "beat projection %"
    without reflecting real forecasting accuracy.
    """
    results_by_team = {t.team_id: {"team": t, "played": 0, "beat": 0, "diffs": []} for t in league.teams}

    reg_season_weeks = getattr(getattr(league, "settings", None), "reg_season_count", None)
    last_week = league.current_week - 1
    if reg_season_weeks:
        last_week = min(last_week, reg_season_weeks)

    for week in range(1, last_week + 1):
        try:
            matchups = league.box_scores(week)
        except Exception:
            continue
        for m in matchups:
            for team_obj, actual, projected in (
                (m.home_team, m.home_score, m.home_projected),
                (m.away_team, m.away_score, m.away_projected),
            ):
                if not team_obj or projected in (None, -1):
                    continue
                entry = results_by_team.get(team_obj.team_id)
                if not entry:
                    continue
                entry["played"] += 1
                entry["diffs"].append(round(actual - projected, 1))
                if actual >= projected:
                    entry["beat"] += 1

    output = []
    for entry in results_by_team.values():
        if entry["played"] == 0:
            continue
        output.append({
            "team": entry["team"],
            "played": entry["played"],
            "beat_pct": round(entry["beat"] / entry["played"] * 100, 1),
            "avg_diff": round(sum(entry["diffs"]) / len(entry["diffs"]), 1),
        })
    output.sort(key=lambda r: -r["beat_pct"])
    return output


def build_prediction_accuracy_section(league):
    results = compute_prediction_accuracy(league)
    if not results:
        return "<p class='empty'>No completed weeks with projection data yet this season.</p>"

    rows = []
    for r in results:
        diff_class = "luck-good" if r["avg_diff"] > 0 else ("luck-bad" if r["avg_diff"] < 0 else "")
        rows.append(f"""
        <tr>
          <td class="team-cell">{team_cell_html(r['team'].team_name, get_owner_name(r['team']))}</td>
          <td>{r['played']}</td>
          <td>{progress_bar_html(r['beat_pct'])}</td>
          <td class="{diff_class}">{r['avg_diff']:+.1f} pts/wk</td>
        </tr>""")

    return f"""
    <h2 class="section-title">Prediction Accuracy</h2>
    <p class="section-note">How often each team beats ESPN's own weekly score projection, and by how much on average.</p>
    <table>
      <thead><tr><th>Team</th><th>Weeks</th><th>Beat Projection</th><th>Avg vs. Projection</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    """


def build_draft_report_card(league, rank_data):
    """
    Rolls up the per-pick draft-slot-vs-current-rank deltas (already computed
    for the draft board) into a per-team grade, plus each team's best value
    pick and biggest bust.
    """
    if not rank_data:
        return "<p class='empty'>Draft ranking data isn't available yet.</p>"

    by_team = {}
    for pick in league.draft:
        if not pick.team:
            continue
        info = rank_data.get(pick.playerId)
        if not info or info["delta"] is None:
            continue
        by_team.setdefault(pick.team.team_id, {
            "team": pick.team, "deltas": [], "picks": []
        })
        by_team[pick.team.team_id]["deltas"].append(info["delta"])
        by_team[pick.team.team_id]["picks"].append({
            "player": pick.playerName, "position": info["position"], "delta": int(info["delta"]),
            "round": pick.round_num, "pick": pick.round_pick,
        })

    if not by_team:
        return "<p class='empty'>Not enough draft ranking data yet to grade teams.</p>"

    for entry in by_team.values():
        entry["avg_delta"] = sum(entry["deltas"]) / len(entry["deltas"])
        entry["best"] = max(entry["picks"], key=lambda p: p["delta"])
        entry["worst"] = min(entry["picks"], key=lambda p: p["delta"])

    ranked = sorted(by_team.values(), key=lambda e: -e["avg_delta"])
    n = len(ranked)

    def grade_for_position(i):
        pct = i / max(n - 1, 1)  # 0 = best, 1 = worst
        if pct <= 0.2:
            return "A"
        elif pct <= 0.4:
            return "B"
        elif pct <= 0.6:
            return "C"
        elif pct <= 0.8:
            return "D"
        else:
            return "F"

    grade_class = {"A": "grade-a", "B": "grade-b", "C": "grade-c", "D": "grade-d", "F": "grade-f"}

    cards = []
    for i, entry in enumerate(ranked):
        grade = grade_for_position(i)
        best, worst = entry["best"], entry["worst"]
        cards.append(f"""
        <div class="report-card">
          <div class="grade-badge {grade_class[grade]}">{grade}</div>
          <div class="report-team">{html.escape(entry['team'].team_name)}</div>
          <div class="report-stat">Avg draft-slot movement: {entry['avg_delta']:+.1f} spots</div>
          <div class="report-line best">
            Best value: {html.escape(str(best['player']))} ({best['position']}, R{best['round']}.{best['pick']}) — {best['delta']:+d} spots
          </div>
          <div class="report-line worst">
            Biggest bust: {html.escape(str(worst['player']))} ({worst['position']}, R{worst['round']}.{worst['pick']}) — {worst['delta']:+d} spots
          </div>
        </div>""")

    return f"""
    <h2 class="section-title">Draft Report Card</h2>
    <p class="section-note">Grades based on how each team's picks are trending vs. their draft slot, curved across the league.</p>
    <div class="report-grid">{"".join(cards)}</div>
    """


def build_power_rankings_section(league):
    power = compute_power_rankings(league)
    luck = compute_luck_index(league)

    if not power:
        return "<p class='empty'>Not enough completed weeks yet to compute power rankings.</p>"

    power_rows = []
    for r in power:
        if r["rank_delta"] > 0:
            move = f"<span class='move-up'>▲ {r['rank_delta']}</span>"
        elif r["rank_delta"] < 0:
            move = f"<span class='move-down'>▼ {abs(r['rank_delta'])}</span>"
        else:
            move = "<span class='move-flat'>–</span>"
        power_rows.append(f"""
        <tr>
          <td>{r['power_rank']}</td>
          <td class="team-cell">{html.escape(r['team'].team_name)}</td>
          <td>{progress_bar_html(r['power_score'])}</td>
          <td>{r['avg_pts']}</td>
          <td>{r['avg_margin']:+.1f}</td>
          <td>vs #{r['standings_rank']} in standings {move}</td>
        </tr>""")

    luck_rows = []
    for r in luck:
        luck_class = "luck-good" if r["luck"] > 0 else ("luck-bad" if r["luck"] < 0 else "")
        bar_color = "#2fb344" if r["luck"] > 0 else ("#e05252" if r["luck"] < 0 else "var(--accent2)")
        luck_rows.append(f"""
        <tr>
          <td class="team-cell">{html.escape(r['team'].team_name)}</td>
          <td>{progress_bar_html(r['actual_pct'])}</td>
          <td>{progress_bar_html(r['expected_pct'])}</td>
          <td class="{luck_class}">{r['luck']:+.1f}%</td>
          <td>{r['label']}</td>
        </tr>""")

    return f"""
    <h2 class="section-title">Power Rankings</h2>
    <p class="section-note">Blends scoring average, margin of victory, and last-3-week form — not just wins/losses.</p>
    <table>
      <thead><tr><th>#</th><th>Team</th><th>Score</th><th>Avg PF</th><th>Avg Margin</th><th>vs Standings</th></tr></thead>
      <tbody>{"".join(power_rows)}</tbody>
    </table>

    <h2 class="section-title" style="margin-top:28px;">Luck Index</h2>
    <p class="section-note">Compares each team's real record to an "all-play" record (their score vs. every other team, every week).</p>
    <table>
      <thead><tr><th>Team</th><th>Actual Win%</th><th>Expected Win%</th><th>Luck</th><th></th></tr></thead>
      <tbody>{"".join(luck_rows)}</tbody>
    </table>

    <h2 class="section-title" style="margin-top:28px;">Playoff Picture</h2>
    {build_playoff_picture_panel(league)}
    """


def build_draft_board(league, rank_data):
    """
    Renders the draft board as a rigid column-per-team table.

    Each draft slot (1..N) gets its own column, labeled with the team that
    owned that slot in round 1. Every team keeps its column across all
    rounds, so the snake order is visible: round 1 fills left-to-right,
    round 2 fills right-to-left, etc. Picks acquired via trade land in the
    picking team's own column (stacking if a team makes two picks in one
    round), which preserves the "who drafted whom" story without breaking
    the grid.
    """
    if not league.draft:
        return "<p class='empty'>No draft data available for this league/year yet.</p>"

    # Group picks by round, kept in round-pick order within each round.
    by_round = {}
    for pick in league.draft:
        by_round.setdefault(pick.round_num, []).append(pick)

    rounds = sorted(by_round)
    if not rounds:
        return "<p class='empty'>No draft data available for this league/year yet.</p>"

    # Column count = number of teams (one column per draft slot). Fall back
    # to the round-1 pick count if league.teams isn't populated yet.
    n_cols = len(league.teams) if league.teams else len(by_round.get(rounds[0], []))
    n_cols = max(n_cols, 1)

    def snake_slot(pick):
        """Natural draft slot for a pick based on snake-draft order."""
        if pick.round_num % 2 == 1:
            return pick.round_pick          # odd rounds: 1..N left-to-right
        return n_cols - pick.round_pick + 1  # even rounds: N..1 right-to-left

    # Map each team (by id) to its natural column. Derived from the first
    # round that has picks: for each pick in that round, the team's natural
    # slot is the snake-derived slot for that pick (round 1: 1..N, round 2:
    # N..1, etc.), so this stays correct even if the draft data is missing
    # round 1. We also capture a display label for every column from that
    # same round; slots with no owning team fall back to "Slot N".
    first_round = rounds[0]
    slot_by_team = {}
    slot_label = {}
    for pick in sorted(by_round.get(first_round, []), key=lambda p: p.round_pick):
        if pick.team:
            s = snake_slot(pick)
            slot_by_team[pick.team.team_id] = s
            slot_label[s] = pick.team.team_name
    for s in range(1, n_cols + 1):
        slot_label.setdefault(s, f"Slot {s}")

    def slot_for(pick):
        """
        Column a pick belongs in: the picking team's own column when known
        (handles traded picks landing in the acquiring team's column),
        otherwise the snake-derived slot as a defensive fallback.
        """
        if pick.team and pick.team.team_id in slot_by_team:
            return slot_by_team[pick.team.team_id]
        return snake_slot(pick)

    def render_pick(pick, round_num):
        team_name = html.escape(pick.team.team_name) if pick.team else "Unknown"
        player_name = html.escape(pick.playerName or "—")
        # Always render a bid line (blank when not applicable) so every
        # cell has the same number of stacked elements — that, plus the
        # fixed CSS heights below, is what keeps all boxes uniform.
        bid = f"<div class='bid'>${pick.bid_amount}</div>" if pick.bid_amount else "<div class='bid'>&nbsp;</div>"

        info = rank_data.get(pick.playerId)
        bg, border = delta_color(info["delta"] if info else None)
        if info and info["delta"] is not None:
            pos = info["position"]
            arrow = "&#9650;" if info["delta"] > 0 else ("&#9660;" if info["delta"] < 0 else "&#8211;")
            rank_line = (f"<div class='rank-move'>{pos}{info['draft_pos_rank']} "
                         f"&rarr; {pos}{info['current_pos_rank']} {arrow}</div>")
        elif info:
            rank_line = f"<div class='rank-move'>{info['position']}{info['draft_pos_rank']} &rarr; n/a</div>"
        else:
            rank_line = "<div class='rank-move'>&nbsp;</div>"

        return f"""
            <div class="draft-cell" style="background:{bg}; border-color:{border};">
              <div class="pick-num">{round_num}.{pick.round_pick}</div>
              <div class="player" title="{player_name}">{player_name}</div>
              <div class="drafted-by" title="{team_name}">{team_name}</div>
              {rank_line}
              {bid}
            </div>"""

    # Bucket each pick into [round][slot]; a slot can hold multiple picks
    # when a team makes more than one pick in a round via trades.
    round_picks = {r: {s: [] for s in range(1, n_cols + 1)} for r in rounds}
    for round_num in rounds:
        for pick in sorted(by_round[round_num], key=lambda p: p.round_pick):
            slot = slot_for(pick)
            if slot < 1 or slot > n_cols:
                slot = snake_slot(pick)
            round_picks[round_num][slot].append(render_pick(pick, round_num))

    # Header row: round-label corner cell + one labeled column per slot.
    header_cells = "<th class='round-label'>Rd</th>" + "".join(
        f"<th>{html.escape(slot_label.get(s, f'Slot {s}'))}</th>"
        for s in range(1, n_cols + 1)
    )

    # One body row per round, led by a round-number label cell.
    body_rows = []
    for round_num in rounds:
        cells = [f"<td class='round-label'>{round_num}</td>"]
        for s in range(1, n_cols + 1):
            cells.append(f"<td>{''.join(round_picks[round_num][s])}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table = f"""
    <table class="draft-board">
      <thead><tr>{header_cells}</tr></thead>
      <tbody>{''.join(body_rows)}</tbody>
    </table>"""

    legend = """
    <div class="legend">
      <span><i class="dot" style="background:rgba(34,139,34,0.7)"></i> Outperforming draft slot (4+ spots)</span>
      <span><i class="dot" style="background:#2a3348"></i> Within 3 spots of draft slot / no data</span>
      <span><i class="dot" style="background:rgba(178,34,34,0.7)"></i> Underperforming draft slot (4+ spots)</span>
    </div>"""
    return f'<div class="draft-board-wrap">{legend}{table}</div>'


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{league_name} — League Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Bebas+Neue&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0d0f13;
    --panel: #15181e;
    --border: #252a33;
    --text: #f2f0ec;
    --muted: #8a8f9a;
    --accent: #c81e3a;
    --accent2: #5b7a99;
    --accent3: #d4a017;
    --accent4: #7fa8c9;
    --gradient: linear-gradient(90deg, var(--accent2), var(--accent3));
    --gradient-warm: linear-gradient(135deg, var(--accent), var(--accent3));
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
  }}
  header {{
    margin-bottom: 28px;
  }}
  h1 {{
    font-family: 'Anton', sans-serif;
    font-weight: 400;
    text-transform: uppercase;
    margin: 0 0 4px 0;
    font-size: 28px;
    letter-spacing: 0.5px;
  }}
  .subtitle {{
    color: var(--muted);
    font-size: 14px;
  }}

  /* ---------- Hero / title section ---------- */
  .hero {{
    position: relative;
    overflow: hidden;
    border-radius: 12px;
    border: 1px solid var(--border);
    padding: 36px 32px;
    margin-bottom: 20px;
    background: radial-gradient(ellipse at 50% -10%, rgba(200,30,58,0.26), transparent 60%), var(--bg);
  }}
  .hero-glow {{
    position: absolute;
    inset: -40%;
    background: radial-gradient(circle at 50% 0%, rgba(200,30,58,0.20), transparent 55%);
    filter: blur(10px);
    pointer-events: none;
  }}
  .hero-content {{ position: relative; z-index: 1; }}
  .onclock {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--accent);
    padding: 6px 14px;
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 16px;
    color: #fff;
  }}
  .onclock .pulse {{
    width: 7px; height: 7px; border-radius: 50%; background: #fff;
    animation: pulse 1.4s ease-in-out infinite;
  }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .3; }} }}
  .hero-eyebrow {{
    font-family: 'Bebas Neue', sans-serif;
    color: var(--accent2);
    font-size: 16px;
    font-weight: 400;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin-bottom: 10px;
  }}
  .hero-title {{
    font-family: 'Anton', sans-serif;
    font-weight: 400;
    text-transform: uppercase;
    margin: 0 0 18px 0;
    font-size: 46px;
    letter-spacing: 0.5px;
    line-height: 1.0;
    background: linear-gradient(90deg, #ffffff 0%, #e8e2d8 60%, var(--accent3) 130%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }}
  .hero-meta {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .hero-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 7px 15px;
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
  }}
  .hero-chip-muted {{
    color: var(--muted);
    font-weight: 400;
    background: transparent;
    border-color: var(--border);
  }}
  .ticker {{
    background: var(--accent);
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.4px;
    padding: 9px 0;
    overflow: hidden;
    white-space: nowrap;
    border-radius: 8px;
    margin-bottom: 18px;
  }}
  .ticker-track {{ display: inline-block; padding-left: 100%; animation: ticker-scroll 38s linear infinite; }}
  .ticker-track span {{ display: inline-block; padding-right: 56px; }}
  .ticker-track span::after {{ content: '\25CF'; color: var(--accent3); margin-left: 56px; font-size: 8px; vertical-align: middle; }}
  @keyframes ticker-scroll {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-100%); }} }}
  @media (prefers-reduced-motion: reduce) {{ .ticker-track {{ animation: none; padding-left: 16px; }} }}
  nav {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px 8px;
    margin: 20px 0 24px 0;
    border-bottom: 1px solid var(--border);
  }}
  nav button {{
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    background: none;
    border: none;
    color: var(--muted);
    font-size: 17px;
    padding: 10px 14px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
  }}
  nav button.active {{
    color: var(--text);
    border-bottom: 2px solid transparent;
    border-image: var(--gradient-warm) 1;
  }}
  section {{ display: none; opacity: 0; transform: translateY(8px); transition: opacity 0.25s ease, transform 0.25s ease; }}
  section.active {{ display: block; }}
  section.active.show {{ opacity: 1; transform: translateY(0); }}
  .panel {{
    box-shadow: 0 4px 16px rgba(0,0,0,0.28);
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
    font-family: 'JetBrains Mono', monospace;
    text-align: left;
    color: var(--muted);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 10px;
    border-bottom: 1px solid var(--border);
  }}
  tr:last-child td {{ border-bottom: none; }}
  .team-cell {{ font-weight: 600; }}
  .team-cell-inner {{ display: flex; align-items: center; gap: 8px; }}
  .team-name-main {{ font-weight: 600; }}
  .owner-name {{ color: var(--muted); font-weight: 400; font-size: 11px; margin-top: 2px; }}
  .logo {{ width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0; object-fit: cover; background: #1b1f27; }}
  .action {{ color: var(--accent2); }}
  .empty {{ color: var(--muted); text-align: center; padding: 24px; }}
  .pbar {{ display: flex; align-items: center; gap: 8px; min-width: 90px; }}
  .pbar-track {{
    flex: 1;
    height: 6px;
    border-radius: 999px;
    background: rgba(255,255,255,0.08);
    overflow: hidden;
  }}
  .pbar-fill {{
    height: 100%;
    border-radius: 999px;
    transition: width 0.4s ease;
  }}
  .pbar-label {{ font-size: 12px; color: var(--muted); min-width: 32px; text-align: right; }}
  .sparkline {{ width: 90px; height: 26px; display: block; }}
  .draft-cell {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
  }}
  .draft-cell:hover {{ transform: translateY(-2px); box-shadow: 0 6px 14px rgba(0,0,0,0.35); }}
  .draft-board-wrap {{ overflow-x: auto; margin-top: 8px; }}
  .draft-board {{ border-collapse: separate; border-spacing: 6px; width: max-content; }}
  .draft-board th {{ color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; padding: 4px 6px; text-align: center; vertical-align: bottom; min-width: 124px; max-width: 140px; }}
  .draft-board td {{ vertical-align: top; padding: 0; min-width: 124px; max-width: 140px; }}
  .draft-board .round-label {{ color: var(--accent); font-weight: 700; font-size: 13px; text-align: center; min-width: 28px; width: 28px; }}
  .draft-board .draft-cell {{ width: 100%; min-width: 0; height: 112px; margin-bottom: 6px; }}
  .draft-board .draft-cell:last-child {{ margin-bottom: 0; }}
  .pick-num {{ color: var(--accent); font-size: 12px; font-weight: 700; flex-shrink: 0; }}
  .player {{
    font-weight: 600; margin: 4px 0 2px 0; font-size: 14px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    flex-shrink: 0;
  }}
  .drafted-by {{
    color: var(--muted); font-size: 12px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    flex-shrink: 0;
  }}
  .rank-move {{ font-size: 11px; margin-top: 6px; color: var(--text); opacity: 0.9; flex-shrink: 0; }}
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
  .section-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 18px;
    letter-spacing: 1.5px;
    color: var(--muted);
    text-transform: uppercase;
    margin: 0 0 16px 0;
  }}
  .matchup-list {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
  }}
  .matchup-card {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .matchup-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.4); }}
  .matchup-card.bye {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: var(--muted);
  }}
  .bye-label {{
    font-size: 11px;
    letter-spacing: 1px;
    color: var(--accent);
    font-weight: 700;
    margin-bottom: 6px;
  }}
  .matchup-teams {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }}
  .matchup-team {{
    flex: 1;
    text-align: center;
  }}
  .matchup-team .team-name {{
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 2px;
  }}
  .matchup-team .team-record {{
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 8px;
  }}
  .matchup-team .proj-score {{
    font-size: 24px;
    font-weight: 800;
    color: var(--accent2);
  }}
  .vs {{
    color: var(--muted);
    font-size: 13px;
    font-weight: 600;
  }}
  .outlook {{
    margin: 14px 0 0 0;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    font-size: 13px;
    line-height: 1.5;
    color: var(--text);
    opacity: 0.9;
  }}
  .section-note {{
    color: var(--muted);
    font-size: 12px;
    margin: -8px 0 16px 0;
  }}
  .subnav {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 16px;
  }}
  .subtab {{
    background: #1b1f27;
    border: 1px solid var(--border);
    color: var(--muted);
    font-size: 13px;
    padding: 6px 12px;
    border-radius: 20px;
    cursor: pointer;
  }}
  .subtab.active {{
    color: var(--text);
    border-color: var(--accent);
    background: rgba(255, 90, 31, 0.12);
  }}
  .subpanel {{ display: none; opacity: 0; transform: translateY(6px); transition: opacity 0.2s ease, transform 0.2s ease; }}
  .subpanel.active {{ display: block; }}
  .subpanel.active.show {{ opacity: 1; transform: translateY(0); }}
  .move-up {{ color: #2fb344; font-weight: 600; }}
  .move-down {{ color: #e05252; font-weight: 600; }}
  .move-flat {{ color: var(--muted); }}
  .luck-good {{ color: #2fb344; font-weight: 600; }}
  .luck-bad {{ color: #e05252; font-weight: 600; }}
  .report-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
  }}
  .report-card {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    position: relative;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .report-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.4); }}
  .grade-badge {{
    position: absolute;
    top: 14px;
    right: 14px;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 15px;
  }}
  .grade-a {{ background: rgba(47,179,68,0.2); color: #2fb344; }}
  .grade-b {{ background: rgba(61,139,253,0.2); color: #3d8bfd; }}
  .grade-c {{ background: rgba(138,146,168,0.25); color: var(--text); }}
  .grade-d {{ background: rgba(255,159,28,0.2); color: #ff9f1c; }}
  .grade-f {{ background: rgba(224,82,82,0.2); color: #e05252; }}
  .report-team {{ font-weight: 700; font-size: 15px; margin-bottom: 6px; padding-right: 40px; }}
  .report-stat {{ color: var(--muted); font-size: 12px; margin-bottom: 10px; }}
  .report-line {{ font-size: 12px; line-height: 1.5; margin-top: 4px; }}
  .report-line.best {{ color: #2fb344; }}
  .report-line.worst {{ color: #e05252; }}
  .rivalry-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
  }}
  .rivalry-card {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .rivalry-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.4); }}
  .rivalry-meetings {{
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
  }}
  .rivalry-matchup {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }}
  .rivalry-team {{ flex: 1; text-align: center; }}
  .rivalry-team .team-name {{ font-weight: 700; font-size: 13px; }}
  .rivalry-record {{ color: var(--accent2); font-weight: 700; font-size: 15px; margin: 4px 0 2px 0; }}
  .rivalry-points {{ color: var(--muted); font-size: 11px; }}

  /* ---------- Trophy Case ---------- */
  .trophy-wall {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 14px;
  }}
  .trophy-card {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 16px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .trophy-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.4); }}
  .trophy-year {{
    color: var(--accent);
    font-weight: 800;
    font-size: 13px;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
  }}
  .trophy-icon {{ font-size: 26px; margin-bottom: 8px; }}
  .trophy-card .team-name-main {{ font-size: 14px; }}
  .trophy-record {{ color: var(--muted); font-size: 12px; margin: 6px 0 4px 0; }}
  .trophy-score {{ font-weight: 700; font-size: 15px; color: var(--accent2); margin-top: 6px; }}
  .trophy-vs {{ color: var(--muted); font-size: 11px; margin-top: 4px; }}

  /* ---------- League Records Book ---------- */
  .record-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
  }}
  .record-card {{
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.25);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .record-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.4); }}
  .record-label {{
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }}
  .record-value {{ font-size: 24px; font-weight: 800; color: var(--text); margin-bottom: 8px; }}
  .record-unit {{ font-size: 12px; font-weight: 600; color: var(--muted); }}
  .record-card .team-name-main {{ font-size: 14px; }}
  .record-context {{ color: var(--muted); font-size: 11.5px; margin-top: 6px; line-height: 1.4; }}

  /* ---------- Playoff Picture ---------- */
  .playoff-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }}
  .playoff-col-title {{
    font-size: 13px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 10px 0;
  }}
  .playoff-row {{
    display: grid;
    grid-template-columns: 24px 1fr auto auto auto;
    align-items: center;
    gap: 10px;
    background: #1b1f27;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
  }}
  .playoff-seed {{ color: var(--muted); font-weight: 700; font-size: 13px; }}
  .playoff-record {{ font-size: 13px; font-weight: 600; white-space: nowrap; }}
  .playoff-detail {{ color: var(--muted); font-size: 11.5px; white-space: nowrap; }}
  .playoff-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 4px 9px;
    border-radius: 20px;
    white-space: nowrap;
  }}
  .badge-clinched {{ background: rgba(47,179,68,0.2); color: #2fb344; }}
  .badge-hunt {{ background: rgba(61,139,253,0.2); color: #3d8bfd; }}
  .badge-bubble {{ background: rgba(255,159,28,0.2); color: #ff9f1c; }}
  .badge-eliminated {{ background: rgba(224,82,82,0.2); color: #e05252; }}

  footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; text-align: center; }}

  /* ---------- Mobile / small-screen adjustments ---------- */
  @media (max-width: 640px) {{
    body {{ padding: 12px; }}
    h1 {{ font-size: 21px; }}
    .subtitle {{ font-size: 12px; }}
    .panel {{ padding: 12px; border-radius: 10px; }}
    .hero {{ padding: 24px 18px; border-radius: 14px; margin-bottom: 18px; }}
    .hero-title {{ font-size: 28px; }}
    .hero-chip {{ font-size: 12px; padding: 5px 11px; }}

    /* Tab bar becomes a single horizontally-scrolling row instead of
       wrapping to multiple lines, which eats a lot of vertical space on
       a phone and is a less familiar pattern than swipeable tabs. */
    nav {{
      flex-wrap: nowrap;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }}
    nav::-webkit-scrollbar {{ display: none; }}
    nav button {{
      padding: 10px 12px;
      font-size: 14px;
      min-height: 44px; /* comfortable touch target */
    }}

    table {{ font-size: 12.5px; }}
    th, td {{ padding: 7px 8px; }}
    .logo {{ width: 18px; height: 18px; }}
    .pbar {{ min-width: 64px; gap: 5px; }}
    .pbar-label {{ font-size: 11px; min-width: 26px; }}
    .sparkline {{ width: 60px; height: 20px; }}

    /* Card grids: allow a single, full-width column on narrow phones
       instead of the wider desktop minimum, and tighten the gap. */
    .matchup-list, .report-grid, .rivalry-grid, .trophy-wall, .record-grid {{
      grid-template-columns: 1fr;
      gap: 10px;
    }}
    .matchup-team .proj-score {{ font-size: 20px; }}

    .playoff-grid {{ grid-template-columns: 1fr; gap: 16px; }}
    .playoff-row {{
      grid-template-columns: 20px 1fr;
      grid-template-areas: "seed team" "record record" "detail detail" "badge badge";
      row-gap: 4px;
    }}
    .playoff-seed {{ grid-area: seed; }}
    .playoff-row .team-cell {{ grid-area: team; }}
    .playoff-record {{ grid-area: record; }}
    .playoff-detail {{ grid-area: detail; }}
    .playoff-badge {{ grid-area: badge; justify-self: start; }}

    .subnav {{ gap: 4px; }}
    .subtab {{ padding: 5px 10px; font-size: 12px; }}

    .draft-board th, .draft-board td {{ min-width: 96px; max-width: 108px; }}
    .draft-board .draft-cell {{ height: 100px; padding: 8px; }}
    .grade-badge {{ width: 28px; height: 28px; font-size: 13px; }}
  }}
</style>
</head>
<body>
{ticker_html}
<header class="hero">
  <div class="hero-glow"></div>
  <div class="hero-content">
    <div class="onclock"><span class="pulse"></span>Week {matchup_week_hero} &middot; On the Clock</div>
    <div class="hero-eyebrow">Fantasy Football &middot; {year} Season</div>
    <h1 class="hero-title">{league_name}</h1>
    <div class="hero-meta">
      <span class="hero-chip">Week {matchup_week_hero}</span>
      <span class="hero-chip">{team_count} Teams</span>
      <span class="hero-chip">🏆 {leader_name}</span>
      <span class="hero-chip hero-chip-muted">Updated {updated}</span>
    </div>
  </div>
</header>

<nav>
  <button class="active" onclick="showTab('standings', this)">Standings</button>
  <button onclick="showTab('power', this)">Power Rankings</button>
  <button onclick="showTab('matchups', this)">Matchups</button>
  <button onclick="showTab('activity', this)">Transactions</button>
  <button onclick="showTab('predictions', this)">Prediction Accuracy</button>
  <button onclick="showTab('draft', this)">Draft Analysis</button>
  <button onclick="showTab('history', this)">History</button>
</nav>

<section id="standings" class="active">
  <div class="panel">
    <div class="subnav">{standings_subnav}</div>
    {standings_panels}
  </div>
</section>

<section id="power">
  <div class="panel">
    {power_rankings}
  </div>
</section>

<section id="matchups">
  <div class="panel">
    <h2 class="section-title">Week {matchup_week} Matchups</h2>
    <div class="matchup-list">
      {matchups}
    </div>
  </div>
</section>

<section id="activity">
  <div class="panel">
    {activity_rows}
  </div>
</section>

<section id="predictions">
  <div class="panel">
    {prediction_accuracy}
  </div>
</section>

<section id="draft">
  <div class="panel">
    {draft_report_card}
    <h2 class="section-title" style="margin-top:28px;">Draft Board</h2>
    {draft_board}
  </div>
</section>

<section id="history">
  <div class="panel">
    {history_section}
  </div>
</section>

<footer>Generated locally from your ESPN league data. Not affiliated with ESPN.</footer>

<script>
function showTab(id, btn) {{
  document.querySelectorAll('body > section').forEach(s => {{ s.classList.remove('active'); s.classList.remove('show'); }});
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  const target = document.getElementById(id);
  target.classList.add('active');
  void target.offsetWidth; // force a reflow so the browser renders the "before" state first
  requestAnimationFrame(() => target.classList.add('show'));
  btn.classList.add('active');
}}
function showSubTab(id, btn) {{
  const panel = document.getElementById(id);
  const container = btn.closest('.panel');
  container.querySelectorAll('.subpanel').forEach(p => {{ p.classList.remove('active'); p.classList.remove('show'); }});
  container.querySelectorAll('.subtab').forEach(b => b.classList.remove('active'));
  panel.classList.add('active');
  void panel.offsetWidth;
  requestAnimationFrame(() => panel.classList.add('show'));
  btn.classList.add('active');
}}
// Trigger the entrance transition for whichever tab/subtab is active on
// initial page load too, not just on click.
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('section.active, .subpanel.active').forEach(el => {{
    void el.offsetWidth;
    requestAnimationFrame(() => el.classList.add('show'));
  }});
}});
</script>
</body>
</html>
"""


def build_ticker_html(league, history, leader_name, leader_record):
    """
    Signature Draft Day War Room element: a scrolling strip of short
    headline facts (league leader, most recent champion, a League Records
    Book highlight). Falls back to just a season/week line if none of that
    data is available yet (e.g. a brand-new league's first season).
    """
    items = []
    if leader_name:
        items.append(f"{leader_name.upper()} LEADS AT {leader_record}")

    champions = history.get("champions") or []
    if champions:
        c = champions[0]
        items.append(f"{c['team'].upper()} WON THE {c['year']} CHAMPIONSHIP")

    records = history.get("records") or {}
    hs = records.get("highest_score")
    if hs:
        items.append(f"RECORD BOOK: {hs['team'].upper()} PUT UP {hs['value']:.1f} IN WEEK {hs['week']}, {hs['year']}")

    if not items:
        items = [f"WEEK {YEAR} SEASON UNDERWAY"]

    spans = "".join(f"<span>{html.escape(item)}</span>" for item in items)
    return f'<div class="ticker"><div class="ticker-track">{spans}{spans}</div></div>'


def main():
    print(f"Connecting to league {LEAGUE_ID} ({YEAR})...")
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

    league_name = getattr(league.settings, "name", "Fantasy Football League")

    print("Fetching current player rankings for draft comparison...")
    rank_data = fetch_player_rank_data(league)

    print("Building matchup outlooks...")
    matchups_html, matchup_week = build_matchups(league)

    print("Computing prediction accuracy...")
    prediction_html = build_prediction_accuracy_section(league)

    print(f"Fetching league history back to {HISTORY_START_YEAR}...")
    history = fetch_historical_data(league, HISTORY_START_YEAR, YEAR)

    standings_subnav, standings_panels = build_standings_tabs(league, history)

    team_count = len(league.teams)
    leader = sorted(league.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))[0] if league.teams else None
    leader_name = leader.team_name if leader else ""
    leader_record = f"{leader.wins}-{leader.losses}" if leader else ""
    ticker_html = build_ticker_html(league, history, leader_name, leader_record)

    html_out = HTML_TEMPLATE.format(
        league_name=html.escape(league_name),
        year=YEAR,
        updated=datetime.now().strftime("%b %d, %Y %I:%M %p"),
        team_count=team_count,
        matchup_week_hero=matchup_week,
        leader_name=html.escape(leader_name),
        ticker_html=ticker_html,
        standings_subnav=standings_subnav,
        standings_panels=standings_panels,
        matchups=matchups_html,
        matchup_week=matchup_week,
        power_rankings=build_power_rankings_section(league),
        draft_report_card=build_draft_report_card(league, rank_data),
        prediction_accuracy=prediction_html,
        history_section=build_history_section(history, YEAR),
        activity_rows=build_transactions_section(league),
        draft_board=build_draft_board(league, rank_data),
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Done. Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()