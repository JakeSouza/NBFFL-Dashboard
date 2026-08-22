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
RECENT_ACTIVITY_COUNT = 25
# The league's first season — used as the default start point for the
# History tab, all-time standings, and rivalry tracker. Override with the
# HISTORY_START_YEAR env var/secret if you only want a partial history.
HISTORY_START_YEAR = int(_env_or_default("HISTORY_START_YEAR", 2018))
# ==================================================


def build_standings_tabs(league, history):
    """
    Builds the Standings section as a set of sub-tabs: current season,
    each historical season fetched, and an All-Time cumulative view.
    Returns (sub_nav_html, sub_panels_html).
    """
    season_standings = history.get("season_standings", {}) if history else {}
    all_time = history.get("all_time", {}) if history else {}

    sub_nav = ['<button class="subtab active" onclick="showSubTab(\'std-current\', this)">Current</button>']
    panels = [f"""
    <div id="std-current" class="subpanel active">
      <table>
        <thead><tr><th>#</th><th>Team</th><th>Record</th><th>PF</th><th>PA</th><th>Streak</th></tr></thead>
        <tbody>{build_standings_rows(league)}</tbody>
      </table>
    </div>"""]

    for year in sorted(season_standings.keys(), reverse=True):
        if year == league.year:
            continue  # current season already shown above
        rows = "".join(f"""
        <tr>
          <td>{s['rank']}</td>
          <td class="team-cell">{html.escape(s['name'])}</td>
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
          <td class="team-cell">{html.escape(e['name'])}</td>
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
    """Index positions (0-based) of weeks that have a decided outcome for at least one team."""
    max_len = max((len(t.outcomes) for t in league.teams), default=0)
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
            beat = sum(1 for other_id, other_score in week_scores.items() if other_id != tid and score > other_score)
            all_play_pct[tid].append(beat / (n - 1))

    results = []
    for team in teams:
        pct_list = all_play_pct.get(team.team_id, [])
        if not pct_list:
            continue
        expected_pct = sum(pct_list) / len(pct_list)
        games = team.wins + team.losses + team.ties
        actual_pct = (team.wins + 0.5 * team.ties) / games if games else 0
        luck = actual_pct - expected_pct
        if luck > 0.12:
            label = "Lucky"
        elif luck < -0.12:
            label = "Unlucky"
        else:
            label = "About Right"
        results.append({
            "team": team,
            "actual_pct": round(actual_pct * 100, 1),
            "expected_pct": round(expected_pct * 100, 1),
            "luck": round(luck * 100, 1),
            "label": label,
        })
    results.sort(key=lambda r: -r["luck"])
    return results


def fetch_historical_data(current_league, start_year, end_year):
    """
    Walks each season from start_year..end_year (inclusive), fetching a
    League() instance for every year except the current one (already have
    that). Extracts:
      - champions: list of (year, team_name) for completed seasons
      - head_to_head: {frozenset({id_a, id_b}): {'meetings', 'wins': {}, 'points': {}}}
      - name_by_id: best-known display name for each team_id encountered
      - season_standings: {year: [ {team_id, name, wins, losses, ties,
        points_for, points_against, rank}, ... ]} sorted best-to-worst
      - all_time: {team_id: {name, wins, losses, ties, points_for,
        points_against, seasons}} accumulated across every fetched year

    Any year that fails to fetch (league didn't exist yet, network hiccup,
    etc.) is skipped rather than aborting the whole run.
    """
    champions = []
    head_to_head = {}
    name_by_id = {t.team_id: t.team_name for t in current_league.teams}
    season_standings = {}
    all_time = {}

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

        if year != current_league.year:
            finished = [t for t in lg.teams if getattr(t, "final_standing", 0) == 1]
            if finished:
                champions.append((year, finished[0].team_name))

        # Per-season standings: use final_standing for completed seasons
        # (reliable once the season wrapped), fall back to win/loss/PF sort
        # for the in-progress current season.
        is_completed = year != current_league.year
        if is_completed and all(getattr(t, "final_standing", 0) for t in lg.teams):
            ordered = sorted(lg.teams, key=lambda t: t.final_standing)
        else:
            ordered = sorted(lg.teams, key=lambda t: (-t.wins, t.losses, -t.points_for))
        season_standings[year] = [{
            "team_id": t.team_id,
            "name": t.team_name,
            "wins": t.wins, "losses": t.losses, "ties": t.ties,
            "points_for": t.points_for, "points_against": t.points_against,
            "rank": i + 1,
        } for i, t in enumerate(ordered)]

        for t in lg.teams:
            entry = all_time.setdefault(t.team_id, {
                "name": t.team_name, "wins": 0, "losses": 0, "ties": 0,
                "points_for": 0.0, "points_against": 0.0, "seasons": 0,
            })
            entry["name"] = t.team_name  # keep most recent name
            entry["wins"] += t.wins
            entry["losses"] += t.losses
            entry["ties"] += t.ties
            entry["points_for"] += t.points_for
            entry["points_against"] += t.points_against
            entry["seasons"] += 1

        for team in lg.teams:
            for opp, score, outcome in zip(team.schedule, team.scores, team.outcomes):
                if outcome not in ("W", "L", "T"):
                    continue
                if not opp or getattr(opp, "team_id", None) in (None, team.team_id):
                    continue  # bye week
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

    champions.sort(key=lambda c: -c[0])
    return {
        "champions": champions,
        "head_to_head": head_to_head,
        "name_by_id": name_by_id,
        "season_standings": season_standings,
        "all_time": all_time,
    }


def build_history_section(history, current_year, top_rivalries=8):
    champions = history["champions"]
    h2h = history["head_to_head"]
    names = history["name_by_id"]

    if champions:
        champ_rows = "".join(
            f"<tr><td>{year}</td><td>{html.escape(name)}</td></tr>"
            for year, name in champions
        )
        champions_html = f"""
        <h2 class="section-title">League Champions</h2>
        <table>
          <thead><tr><th>Season</th><th>Champion</th></tr></thead>
          <tbody>{champ_rows}</tbody>
        </table>"""
    else:
        champions_html = """
        <h2 class="section-title">League Champions</h2>
        <p class="section-note">No completed prior seasons found yet.</p>"""

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

    return champions_html + rivalry_html


def compute_prediction_accuracy(league):
    """
    Compares each team's actual weekly score to ESPN's own projection for
    that week, across all completed weeks this season. Reveals who
    consistently outplays projections vs. who underperforms them.
    """
    results_by_team = {t.team_id: {"team": t, "played": 0, "beat": 0, "diffs": []} for t in league.teams}

    for week in range(1, league.current_week):
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
          <td class="team-cell">{html.escape(r['team'].team_name)}</td>
          <td>{r['played']}</td>
          <td>{r['beat_pct']}%</td>
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
          <td>{r['power_score']}</td>
          <td>{r['avg_pts']}</td>
          <td>{r['avg_margin']:+.1f}</td>
          <td>vs #{r['standings_rank']} in standings {move}</td>
        </tr>""")

    luck_rows = []
    for r in luck:
        luck_class = "luck-good" if r["luck"] > 0 else ("luck-bad" if r["luck"] < 0 else "")
        luck_rows.append(f"""
        <tr>
          <td class="team-cell">{html.escape(r['team'].team_name)}</td>
          <td>{r['actual_pct']}%</td>
          <td>{r['expected_pct']}%</td>
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
    """


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
      <span><i class="dot" style="background:rgba(34,139,34,0.7)"></i> Outperforming draft slot (4+ spots)</span>
      <span><i class="dot" style="background:#2a3348"></i> Within 3 spots of draft slot / no data</span>
      <span><i class="dot" style="background:rgba(178,34,34,0.7)"></i> Underperforming draft slot (4+ spots)</span>
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
    flex-wrap: wrap;
    gap: 4px 8px;
    margin: 20px 0 24px 0;
    border-bottom: 1px solid var(--border);
  }}
  nav button {{
    background: none;
    border: none;
    color: var(--muted);
    font-size: 15px;
    padding: 10px 14px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
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
  .section-title {{
    font-size: 15px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 16px 0;
  }}
  .matchup-list {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
  }}
  .matchup-card {{
    background: #1c2438;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
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
    background: #1c2438;
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
  .subpanel {{ display: none; }}
  .subpanel.active {{ display: block; }}
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
    background: #1c2438;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    position: relative;
  }}
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
    background: #1c2438;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
  }}
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
  <button onclick="showTab('matchups', this)">Matchups</button>
  <button onclick="showTab('power', this)">Power Rankings</button>
  <button onclick="showTab('draftgrades', this)">Draft Report Card</button>
  <button onclick="showTab('predictions', this)">Prediction Accuracy</button>
  <button onclick="showTab('history', this)">History</button>
  <button onclick="showTab('activity', this)">Recent Transactions</button>
  <button onclick="showTab('draft', this)">Draft Board</button>
</nav>

<section id="standings" class="active">
  <div class="panel">
    <div class="subnav">{standings_subnav}</div>
    {standings_panels}
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

<section id="power">
  <div class="panel">
    {power_rankings}
  </div>
</section>

<section id="draftgrades">
  <div class="panel">
    {draft_report_card}
  </div>
</section>

<section id="predictions">
  <div class="panel">
    {prediction_accuracy}
  </div>
</section>

<section id="history">
  <div class="panel">
    {history_section}
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
  document.querySelectorAll(':scope > section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
function showSubTab(id, btn) {{
  const panel = document.getElementById(id);
  const container = btn.closest('.panel');
  container.querySelectorAll('.subpanel').forEach(p => p.classList.remove('active'));
  container.querySelectorAll('.subtab').forEach(b => b.classList.remove('active'));
  panel.classList.add('active');
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

    print("Building matchup outlooks...")
    matchups_html, matchup_week = build_matchups(league)

    print("Computing prediction accuracy...")
    prediction_html = build_prediction_accuracy_section(league)

    print(f"Fetching league history back to {HISTORY_START_YEAR}...")
    history = fetch_historical_data(league, HISTORY_START_YEAR, YEAR)

    standings_subnav, standings_panels = build_standings_tabs(league, history)

    html_out = HTML_TEMPLATE.format(
        league_name=html.escape(league_name),
        year=YEAR,
        updated=datetime.now().strftime("%b %d, %Y %I:%M %p"),
        standings_subnav=standings_subnav,
        standings_panels=standings_panels,
        matchups=matchups_html,
        matchup_week=matchup_week,
        power_rankings=build_power_rankings_section(league),
        draft_report_card=build_draft_report_card(league, rank_data),
        prediction_accuracy=prediction_html,
        history_section=build_history_section(history, YEAR),
        activity_rows=build_activity_rows(league),
        draft_board=build_draft_board(league, rank_data),
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Done. Open {OUTPUT_FILE} in your browser.")


if __name__ == "__main__":
    main()