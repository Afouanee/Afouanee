"""Génère la carte des contributions survolée par l'avion du portfolio, à partir des vraies données GitHub.
Une image SVG ne peut pas exécuter de hasard : le trajet est tiré au sort à chaque génération, donc chaque jour.

    python scripts/build_contributions.py

Jeton lu dans GITHUB_TOKEN, sinon via `gh auth token`. En cas d'échec, les fichiers existants
ne sont pas touchés. Lancé chaque jour par .github/workflows/contributions.yml.
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_assets import MONO, OUT, POPPINS, THEMES, Svg  # noqa: E402

LOGIN = "Afouanee"
QUERY = """query($login: String!) { user(login: $login) { contributionsCollection { contributionCalendar {
  totalContributions weeks { contributionDays { date contributionCount contributionLevel } } } } } }"""

LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
# Dégradé du rouge de marque du portfolio (dernier palier = la couleur exacte).
SCALE = {
    "light": ["#F7CDD0", "#EF9299", "#E85A63", "#E11D2A"],
    "dark": ["#4A1D25", "#7F2B37", "#B83843", "#ED4456"],
}
MONTHS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]

CELL, GAP, LEFT, TOP = 17, 4, 44, 112
SPEED_RANGE = (70, 135)  # px/s par étape, autour des 96 px/s du portfolio
MIN_SPEED_FACTOR = 0.5  # ralentit en approchant une destination, comme dans le portfolio
PLANE = 15  # demi-envergure
STOPS = 12  # destinations par trajet
MIN_HOP = 170  # distance minimale entre deux destinations


def fetch() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def cell_xy(week_index: int, day: dict) -> tuple[int, int]:
    weekday = (date.fromisoformat(day["date"]).weekday() + 1) % 7
    return LEFT + week_index * (CELL + GAP), TOP + weekday * (CELL + GAP)


def destinations(weeks: list, rng: random.Random) -> list[tuple[float, float]]:
    """Tire au sort des jours actifs, les plus chargés ayant plus de chances : le vol reste lié à l'activité réelle."""
    days = [(cell_xy(i, day), day["contributionCount"]) for i, week in enumerate(weeks) for day in week["contributionDays"] if day["contributionCount"]]
    centers = [(x + CELL / 2, y + CELL / 2) for (x, y), _ in days]
    weights = [count ** 0.5 for _, count in days]
    stops: list[tuple[float, float]] = []
    for _ in range(STOPS * 40):
        if len(stops) == STOPS:
            break
        point = rng.choices(centers, weights)[0]
        if not stops or (math.dist(point, stops[-1]) >= MIN_HOP and point not in stops):
            stops.append(point)
    return stops


def edge_point(rng: random.Random, W: float, H: float) -> tuple[float, float]:
    """Un point hors de la carte, sur un bord au hasard."""
    side = rng.choice("lrtb")
    if side in "lr":
        return (-40.0 if side == "l" else W + 40.0, rng.uniform(TOP, H - 40))
    return (rng.uniform(60, W - 60), -40.0 if side == "t" else H + 40.0)


def plan_flight(weeks: list, W: float, H: float, rng: random.Random) -> dict:
    """Trajet commun aux deux thèmes : points de passage, vitesse variable, instants de passage aux destinations."""
    stops = destinations(weeks, rng)
    anchors = [edge_point(rng, W, H), *stops, edge_point(rng, W, H)]
    samples = 24
    route = smooth(anchors, samples)
    lengths, clock = [0.0], [0.0]
    speeds = [rng.uniform(*SPEED_RANGE) for _ in range(len(anchors) - 1)]
    for k, (a, b) in enumerate(zip(route, route[1:])):
        step = math.dist(a, b)
        leg, u = k // samples, (k % samples + 0.5) / samples
        factor = MIN_SPEED_FACTOR + (1 - MIN_SPEED_FACTOR) * math.sin(math.pi * u)
        lengths.append(lengths[-1] + step)
        clock.append(clock[-1] + step / (speeds[leg] * factor))
    total, dur = lengths[-1], clock[-1]
    keep = sorted({*range(0, len(route), 4), len(route) - 1})
    # Les instants doivent rester strictement croissants pour SMIL.
    times = [clock[k] / dur for k in keep]
    return {
        "d": "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in route),
        "length": total,
        "dur": dur,
        "key_points": ";".join(f"{lengths[k] / total:.4f}" for k in keep),
        "key_offsets": [lengths[k] for k in keep],
        "key_times": ";".join(f"{t:.4f}" for t in times),
        "passes": [(stop, clock[(i + 1) * samples] / dur) for i, stop in enumerate(stops)],
    }


def smooth(points: list[tuple[float, float]], samples: int = 24) -> list[tuple[float, float]]:
    """Courbe de Catmull-Rom : l'avion vire au lieu de pivoter d'un coup."""
    pts = [points[0], *points, points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1:i + 3]
        for k in range(samples):
            t = k / samples
            out.append(tuple(
                0.5 * (2 * p1[a] + (p2[a] - p0[a]) * t + (2 * p0[a] - 5 * p1[a] + 4 * p2[a] - p3[a]) * t * t + (3 * p1[a] - p0[a] - 3 * p2[a] + p3[a]) * t ** 3)
                for a in (0, 1)
            ))
    out.append(points[-1])
    return out


def plane_path(s: float) -> str:
    """Même silhouette que drawPlane() du portfolio : fuselage, nez, aile, empennage, pointe vers +X."""
    length, width = s * 2.2, s * 0.22
    rect = lambda x, y, w, h: f"M{x:.2f} {y:.2f}h{w:.2f}v{h:.2f}h{-w:.2f}z"  # noqa: E731
    return "".join([
        rect(-length * 0.45, -width / 2, length, width),
        f"M{length * 0.55:.2f} {-width / 2:.2f}L{length * 0.55 + s * 0.35:.2f} 0L{length * 0.55:.2f} {width / 2:.2f}z",
        rect(s * 0.15 - s * 0.21, -s * 1.15, s * 0.42, s * 2.3),
        rect(-s * 0.95 - s * 0.14, -s * 0.45, s * 0.28, s * 0.9),
    ])


def render(calendar: dict, theme: str, flight: dict) -> str:
    t, scale = THEMES[theme], SCALE[theme]
    weeks, total = calendar["weeks"], calendar["totalContributions"]
    step = CELL + GAP
    W, H = 1200, TOP + 7 * step + 34
    s = Svg(W, H, f"{total} contributions GitHub sur les douze derniers mois, survolées par un avion")
    s.raw(f'<defs><clipPath id="c"><rect x="2" y="2" width="{W - 4}" height="{H - 4}" rx="21"/></clipPath></defs>')
    s.raw(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="22" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="2"/>')

    label = f"{total:,}".replace(",", " ")
    s.raw(f'<rect x="{LEFT}" y="34" width="4" height="26" rx="2" fill="{t["red"]}"/>')
    s.text(LEFT + 14, 57, label, POPPINS[700], 28, t["text"], spacing=-0.4)
    s.text(LEFT + 24 + POPPINS[700].width(label, 28), 57, "contributions sur un an", POPPINS[500], 21, t["muted"])

    # Mois : libellé sur la première semaine du mois, sauf s'il touche le précédent.
    last_x = -100.0
    for i, week in enumerate(weeks):
        first = date.fromisoformat(week["contributionDays"][0]["date"])
        x = LEFT + i * step
        if first.day <= 7 and x - last_x >= 3 * step:
            s.text(x, TOP - 14, MONTHS[first.month - 1], MONO, 15, t["muted"])
            last_x = x

    for i, week in enumerate(weeks):
        for day in week["contributionDays"]:
            x, y = cell_xy(i, day)
            level = LEVELS.index(day["contributionLevel"])
            fill = scale[level - 1] if level else t["chip"]
            s.raw(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="4" fill="{fill}"/>')

    d, length, dur = flight["d"], flight["length"], flight["dur"]
    motion = f'calcMode="linear" keyTimes="{flight["key_times"]}" dur="{dur:.2f}s" repeatCount="indefinite"'

    s.raw('<g clip-path="url(#c)">')
    # Traînée : un trait en pointillés dont le seul tiret visible suit l'avion. Deux épaisseurs pour le fondu.
    for trail, width, opacity in [(190, 1.5, 0.22), (90, 2.5, 0.4)]:
        offsets = ";".join(f"{trail - o:.1f}" for o in flight["key_offsets"])
        s.raw(
            f'<path d="{d}" fill="none" stroke="{t["ink"]}" stroke-width="{width}" stroke-linecap="round" opacity="{opacity}" stroke-dasharray="{trail} {length + 2 * trail:.0f}" stroke-dashoffset="{trail}">'
            f'<animate attributeName="stroke-dashoffset" values="{offsets}" {motion}/></path>'
        )
    # À chaque destination, un anneau rouge s'allume au passage de l'avion.
    for (x, y), f in flight["passes"]:
        before, after = max(0.0001, f - 0.004), min(0.998, f + 0.07)
        times = f"0;{before:.4f};{f:.4f};{after:.4f};1"
        s.raw(
            f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="{t["red"]}" stroke-width="2.5" opacity="0">'
            f'<animate attributeName="opacity" values="0;0;1;0;0" keyTimes="{times}" dur="{dur:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="r" values="9;9;9;24;24" keyTimes="{times}" dur="{dur:.2f}s" repeatCount="indefinite"/></circle>'
        )
    # Contour couleur de carte : l'avion reste lisible au-dessus des cases rouges.
    s.raw(
        f'<path d="{plane_path(PLANE)}" fill="{t["ink"]}" stroke="{t["card"]}" stroke-width="2" paint-order="stroke" stroke-linejoin="round">'
        f'<animateMotion path="{d}" rotate="auto" keyPoints="{flight["key_points"]}" {motion}/></path></g>'
    )
    return s.render()


def main() -> None:
    calendar = fetch()
    if not calendar["weeks"] or not calendar["totalContributions"]:
        raise SystemExit("Données vides : fichiers conservés.")
    # Nouveau trajet à chaque génération, identique dans les deux thèmes.
    step = CELL + GAP
    flight = plan_flight(calendar["weeks"], 1200, TOP + 7 * step + 34, random.Random())
    for theme in THEMES:
        (OUT / f"contributions-{theme}.svg").write_text(render(calendar, theme, flight), encoding="utf-8")
    print(f"{calendar['totalContributions']} contributions, {len(calendar['weeks'])} semaines")


if __name__ == "__main__":
    main()
