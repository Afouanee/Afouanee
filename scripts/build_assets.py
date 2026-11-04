"""Génère les visuels SVG du README (versions claire et sombre).

    python scripts/build_assets.py

Les polices du portfolio (Plus Jakarta Sans, JetBrains Mono, licence OFL) sont réduites aux seuls caractères
utilisés puis intégrées dans chaque SVG : le rendu est identique sur toutes les machines,
sans dépendre d'un service externe. Les textes sont mesurés avec les métriques réelles
des polices pour les retours à la ligne.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(__file__).resolve().parent / "fonts"
AVATAR = Path(__file__).resolve().parent / "avatar.png"  # favicon du portfolio
OUT = ROOT / "assets"

THEMES = {
    "light": dict(
        bg="#FFFFFF", panel="#FAFAFA", card="#FFFFFF", border="#E5E5EA", text="#1D1D1F", muted="#6E6E73",
        faint="#AEAEB2", chip="#F2F2F4", chip_text="#3A3A3C", line="#D1D1D6", dot="#E5E5EA",
        mono_bg="#1D1D1F", mono_text="#F5F5F7", mono_muted="#8E8E93", mono_bar="#2C2C2E",
        tile="#F2F2F4", red="#E11D2A", ink="#1D1D1F",
    ),
    "dark": dict(
        bg="#0D1117", panel="#11161D", card="#161B22", border="#30363D", text="#F5F5F7", muted="#A1A1A6",
        faint="#6E6E73", chip="#21262D", chip_text="#E5E5EA", line="#30363D", dot="#21262D",
        mono_bg="#0B0E13", mono_text="#E5E5EA", mono_muted="#6E7681", mono_bar="#161B22",
        tile="#F5F5F7", red="#ED4456", ink="#F5F5F7",
    ),
}


# --------------------------------------------------------------------------- polices
@dataclass(eq=False)
class Font:
    family: str
    weight: int
    path: Path
    variable_wght: int | None = None
    _tt: TTFont | None = field(default=None, repr=False)

    def tt(self) -> TTFont:
        if self._tt is None:
            font = TTFont(self.path)
            if self.variable_wght:
                font = instancer.instantiateVariableFont(font, {"wght": self.variable_wght})
            self._tt = font
        return self._tt

    def width(self, text: str, size: float, spacing: float = 0) -> float:
        tt = self.tt()
        cmap, hmtx, upm = tt.getBestCmap(), tt["hmtx"], tt["head"].unitsPerEm
        total = sum(hmtx[cmap.get(ord(ch), cmap.get(0x3F))][0] for ch in text)
        return total * size / upm + spacing * max(0, len(text) - 1)


SANS = {w: Font("Plus Jakarta Sans", w, FONTS / "PlusJakartaSans.ttf", variable_wght=w) for w in (400, 500, 600, 700)}
MONO = Font("JetBrains Mono", 500, FONTS / "JetBrainsMono.ttf", variable_wght=500)


class Svg:
    """Accumule les éléments et les caractères utilisés par police, puis intègre les polices réduites."""

    def __init__(self, width: int, height: int, title: str):
        self.w, self.h, self.title = width, height, title
        self.parts: list[str] = []
        self.used: dict[Font, set[str]] = {}

    def text(self, x, y, s, font: Font, size, fill, anchor="start", spacing=0, extra="") -> None:
        self.used.setdefault(font, set()).update(s)
        attrs = f'font-family="{font.family}" font-weight="{font.weight}" font-size="{size}"'
        if spacing:
            attrs += f' letter-spacing="{spacing}"'
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" {attrs} fill="{fill}" text-anchor="{anchor}"{extra}>{escape(s)}</text>')

    def raw(self, s: str) -> None:
        self.parts.append(s)

    def render(self) -> str:
        faces = []
        for font, chars in self.used.items():
            options = subset.Options()
            options.flavor = "woff2"
            options.layout_features = ["kern", "liga", "calt"]
            options.name_IDs = []
            sub = subset.Subsetter(options)
            sub.populate(text="".join(sorted(chars | {" "})))
            tt = TTFont(io.BytesIO(_ttf_bytes(font)))
            sub.subset(tt)
            buf = io.BytesIO()
            tt.flavor = "woff2"
            tt.save(buf)
            data = base64.b64encode(buf.getvalue()).decode()
            faces.append(f"@font-face{{font-family:'{font.family}';font-weight:{font.weight};src:url(data:font/woff2;base64,{data}) format('woff2')}}")
        style = "".join(faces) + "text{font-kerning:normal}"
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img">'
            f"<title>{escape(self.title)}</title><style>{style}</style>" + "".join(self.parts) + "</svg>\n"
        )


def _ttf_bytes(font: Font) -> bytes:
    buf = io.BytesIO()
    font.tt().save(buf)
    return buf.getvalue()


def wrap(text: str, font: Font, size: float, max_width: float) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.width(candidate, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def chip_row(svg: Svg, t: dict, x: float, y: float, labels: list[str], max_width: float, size=13.0, gap=8.0, height=28.0) -> float:
    """Pastilles en police mono, avec retour à la ligne. Renvoie l'ordonnée sous la dernière ligne."""
    cx, cy = x, y
    for label in labels:
        w = MONO.width(label, size) + 24
        if cx > x and cx + w > x + max_width:
            cx, cy = x, cy + height + gap
        svg.raw(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{height}" rx="{height / 2}" fill="{t["chip"]}"/>')
        svg.text(cx + 12, cy + height / 2 + size * 0.36, label, MONO, size, t["chip_text"])
        cx += w + gap
    return cy + height


# --------------------------------------------------------------------------- en-tête
def avatar_data_uri(size: int = 288) -> str:
    """Memoji recadré sur son contenu, posé en bas du carré pour qu'il dépasse de la vignette."""
    source = Image.open(AVATAR).convert("RGBA")
    subject = source.crop(source.getchannel("A").getbbox())
    height = round(size * 0.9)
    subject = subject.resize((round(subject.width * height / subject.height), height), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(subject, ((size - subject.width) // 2, size - height))
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


TERMINAL = [
    ("$ whoami", True),
    ("ingénieur ESIEE Paris, 2026", False),
    ("$ cat focus.txt", True),
    ("IA en production, full stack", False),
    ("$ cat regle.txt", True),
    ("mesurer avant d’affirmer", False),
]


def header(theme: str) -> str:
    t = THEMES[theme]
    W, H = 1200, 420
    s = Svg(W, H, "Afouane Mouhamad, ingénieur informatique Full Stack & IA, en recherche active")
    s.raw(
        f'<defs><pattern id="g" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.6" fill="{t["dot"]}"/></pattern>'
        f'<linearGradient id="fade" x1="0" x2="1"><stop offset="0.35" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>'
        f'<mask id="m"><rect width="{W}" height="{H}" fill="url(#fade)"/></mask>'
        f'<clipPath id="frame"><rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="28"/></clipPath></defs>'
    )
    s.raw(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="28" fill="{t["panel"]}" stroke="{t["border"]}" stroke-width="2"/>')
    s.raw(f'<g clip-path="url(#frame)"><rect width="{W}" height="{H}" fill="url(#g)" mask="url(#m)"/></g>')

    # Vignette claire dans les deux thèmes : la casquette noire du memoji resterait invisible sur fond sombre.
    s.raw(
        '<defs><clipPath id="tile"><rect x="64" y="52" width="104" height="104" rx="28"/></clipPath></defs>'
        f'<rect x="64" y="52" width="104" height="104" rx="28" fill="{t["tile"]}"/>'
        f'<image x="64" y="52" width="104" height="104" href="{avatar_data_uri()}" clip-path="url(#tile)"/>'
    )
    s.text(192, 98, "PORTFOLIO", MONO, 16, t["muted"], spacing=3)
    s.text(192, 126, "afouanee.dev", MONO, 18, t["text"])

    # Terminal dimensionné sur sa plus longue ligne ; le nom s'adapte pour garder 48 px de marge.
    tw = MONO.width(max((line for line, _ in TERMINAL), key=len), 17) + 56
    tx, ty, th = W - 64 - tw, 60, 306
    name_size = min(66.0, 66.0 * (tx - 48 - 62) / SANS[700].width("Afouane Mouhamad", 66, -1.5))
    name_size = round(name_size, 1)
    s.text(62, 246, "Afouane", SANS[700], name_size, t["text"], spacing=-1.5)
    s.text(62 + SANS[700].width("Afouane ", name_size, -1.5) - 1.5, 246, "Mouhamad", SANS[700], name_size, t["red"], spacing=-1.5)
    s.text(64, 292, "Ingénieur informatique · Full Stack & IA", SANS[500], 29, t["muted"])

    status = "En recherche active · Paris · disponible immédiatement"
    pill_w = MONO.width(status, 17) + 64
    s.raw(f'<rect x="64" y="322" width="{pill_w:.1f}" height="44" rx="22" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="1.5"/>')
    s.raw(
        f'<circle cx="88" cy="344" r="5" fill="{t["red"]}"><animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>'
        f'<circle cx="88" cy="344" r="5" fill="none" stroke="{t["red"]}" stroke-width="1.5"><animate attributeName="r" values="5;11" dur="2s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values=".6;0" dur="2s" repeatCount="indefinite"/></circle>'
    )
    s.text(106, 350, status, MONO, 17, t["text"])

    # Terminal : les lignes s'écrivent l'une après l'autre (SMIL, compatible avec les images GitHub).
    s.raw(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="18" fill="{t["mono_bg"]}" stroke="{t["border"]}" stroke-width="1.5"/>')
    s.raw(f'<path d="M{tx} {ty + 18}a18 18 0 0 1 18-18h{tw - 36}a18 18 0 0 1 18 18v22h-{tw}z" fill="{t["mono_bar"]}"/>')
    for i in range(3):
        s.raw(f'<circle cx="{tx + 24 + i * 18}" cy="{ty + 20}" r="5.5" fill="{t["mono_muted"]}" opacity="{0.9 - i * 0.25:.2f}"/>')
    s.text(tx + tw / 2, ty + 25, "~/afouane", MONO, 12.5, t["mono_muted"], anchor="middle")

    size, char = 17, MONO.width("a", 17)
    begin = 0.4
    defs = []
    for i, (line, is_cmd) in enumerate(TERMINAL):
        y = ty + 72 + i * 34
        n = len(line)
        widths = ";".join(f"{k * char + 2:.1f}" for k in range(n + 1))
        dur = n * (0.045 if is_cmd else 0.022)
        defs.append(
            f'<clipPath id="l{i}"><rect x="{tx + 24}" y="{y - 20}" height="28" width="0">'
            f'<animate attributeName="width" values="{widths}" calcMode="discrete" begin="{begin:.2f}s" dur="{dur:.2f}s" fill="freeze"/></rect></clipPath>'
        )
        color = t["mono_text"] if is_cmd else t["mono_muted"]
        s.raw(f'<g clip-path="url(#l{i})">')
        if is_cmd:
            s.text(tx + 24, y, "$", MONO, size, t["red"])
            s.text(tx + 24 + char * 2, y, line[2:], MONO, size, color)
        else:
            s.text(tx + 24, y, line, MONO, size, color)
        s.raw("</g>")
        begin += dur + (0.35 if is_cmd else 0.15)
    y = ty + 72 + len(TERMINAL) * 34
    s.raw("<defs>" + "".join(defs) + "</defs>")
    s.raw(f'<g opacity="0"><animate attributeName="opacity" values="0;1" begin="{begin:.2f}s" dur="0.01s" fill="freeze"/>')
    s.text(tx + 24, y, "$", MONO, size, t["red"])
    s.raw(
        f'<rect x="{tx + 24 + char * 2:.1f}" y="{y - 15}" width="{char:.1f}" height="19" fill="{t["red"]}">'
        f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1.1s" repeatCount="indefinite"/></rect></g>'
    )
    return s.render()


# --------------------------------------------------------------------------- cartes projet
CARDS = {
    "shway": dict(
        label="EN COURS · 2026", link="shway.fr ↗", live=True, title="Shway", side="left",
        subtitle="Automatisation métier pour les PME",
        body="Comprendre un processus, le simplifier, puis automatiser seulement ce qui le mérite. L’IA propose, une personne décide.",
        chips=["FastAPI", "Next.js 16", "PostgreSQL", "n8n", "Mistral"],
    ),
    "radar": dict(
        label="APPRENTISSAGE · 2026", link="Afouanee/radar ↗", title="Radar", side="right",
        subtitle="Agent LLM construit pour monter en compétence",
        body="Recherche vectorielle, agent LangGraph, scores justifiés critère par critère. Déploiement bloqué si l’évaluation chute.",
        chips=["TypeScript", "LangGraph", "MCP", "pgvector", "Cloud Run"],
    ),
    "cafe-creme": dict(
        label="STAGE · LONDRES · 2026", link="afouanee.dev ↗", title="Café Crème", side="left",
        subtitle="IA en production, plateformes full stack",
        body="Assistant RAG sur 1 588 appels clients, copilote de vente, chatbot en production, EdTech de 19 modules, app mobile.",
        chips=["TypeScript", "Mistral", "RAG", "Next.js", "React Native"],
    ),
    "gate": dict(
        label="PROJET PERSONNEL · 2026", link="Afouanee/Gate ↗", title="Gate", side="right",
        subtitle="Arbres généalogiques collaboratifs",
        body="Graphe interactif React Flow, relations familiales complexes, abonnements Stripe, application bilingue installable.",
        chips=["Next.js", "Prisma", "PostgreSQL", "Stripe", "React Flow"],
    ),
}


def card(key: str, theme: str) -> str:
    """Deux cartes par ligne, collées sans espace dans le README : la gouttière est dessinée ici,
    pour que leurs bords extérieurs s'alignent exactement sur ceux de l'en-tête."""
    t, c = THEMES[theme], CARDS[key]
    W, H, P, GUTTER, ROW_GAP = 600, 366, 32, 12, 16
    left = GUTTER if c["side"] == "right" else 0
    x0, inner = left + P, W - GUTTER - 2 * P
    s = Svg(W, H, f"{c['title']} : {c['subtitle']}")
    s.raw(f'<rect x="{left + 1}" y="1" width="{W - GUTTER - 2}" height="{H - ROW_GAP - 2}" rx="22" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="2"/>')
    lx = x0
    if c.get("live"):
        s.raw(f'<circle cx="{x0 + 5}" cy="44" r="5" fill="{t["red"]}"><animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>')
        lx += 18
    s.text(lx, 49, c["label"], MONO, 14, t["muted"], spacing=1.2)
    s.text(x0 + inner, 49, c["link"], MONO, 14, t["muted"], anchor="end")
    s.raw(f'<rect x="{x0}" y="74" width="4" height="34" rx="2" fill="{t["red"]}"/>')
    s.text(x0 + 14, 105, c["title"], SANS[700], 40, t["text"], spacing=-0.8)
    s.text(x0, 143, c["subtitle"], SANS[500], 20, t["muted"])
    for i, line in enumerate(wrap(c["body"], SANS[400], 19, inner)[:3]):
        s.text(x0, 186 + i * 28, line, SANS[400], 19, t["text"])
    chip_row(s, t, x0, H - ROW_GAP - P - 30, c["chips"], inner, size=14.5, height=30)
    return s.render()


# --------------------------------------------------------------------------- parcours
# Ordre strictement chronologique (date de début), études et expériences mêlées.
TIMELINE = [
    ("upec", "sept. 2021 → sept. 2023 · école", "IUT Créteil-Vitry", "BUT GEII, systèmes embarqués"),
    ("siemens", "sept. 2022 → août 2023 · pro", "Siemens", "Technicien systèmes incendie, alternance"),
    ("realisium", "sept. 2023 → août 2024 · pro", "Realisium", "Assistant chef de projet IT, alternance"),
    ("esiee", "sept. 2023 → sept. 2026 · école", "ESIEE Paris", "Diplôme d’ingénieur informatique"),
    ("enedis", "sept. 2024 → sept. 2026 · pro", "Enedis", "Appui au pilotage SI, alternance"),
    ("cafecreme", "mai 2026 → juil. 2026 · pro", "Café Crème", "Full Stack & IA, stage à Londres"),
]


def logo_uri(name: str) -> str:
    data = (Path(__file__).resolve().parent / "logos" / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def timeline(theme: str) -> str:
    """Une seule ligne continue qui serpente : gauche vers droite, demi-tour, droite vers gauche, demi-tour, etc.
    Plaque blanche dans les deux thèmes : les logos sont conçus pour fond clair."""
    t = THEMES[theme]
    W, TOP_Y, ROW, PER_ROW = 1200, 44, 128, 2
    left, right = 92.0, 1108.0
    columns = [left, 640.0]
    plate_w, plate_h = 150, 66
    rows = len(TIMELINE) // PER_ROW
    H = int(TOP_Y + (rows - 1) * ROW + 22 + plate_h + 34)
    s = Svg(W, H, "Parcours : BUT GEII, Siemens, Realisium, Enedis, Café Crème, diplôme d'ingénieur ESIEE Paris")
    s.raw(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="22" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="2"/>')

    radius = ROW / 2
    d = f"M{left} {TOP_Y}"
    for r in range(rows):
        y = TOP_Y + r * ROW
        if r == rows - 1:
            # Dernière ligne : on s'arrête sur la dernière étape.
            end = columns[-1] if r % 2 == 0 else columns[0]
            d += f"H{end}"
        elif r % 2 == 0:
            d += f"H{right}A{radius} {radius} 0 0 1 {right} {y + ROW}"
        else:
            d += f"H{left}A{radius} {radius} 0 0 0 {left} {y + ROW}"
    s.raw(f'<path d="{d}" fill="none" stroke="{t["line"]}" stroke-width="3" stroke-linecap="round"/>')

    for i, (logo, dates, org, role) in enumerate(TIMELINE):
        r, pos = divmod(i, PER_ROW)
        x = columns[pos if r % 2 == 0 else PER_ROW - 1 - pos]
        y = TOP_Y + r * ROW
        if logo == "esiee":  # le diplôme reste marqué, à sa place dans la chronologie
            s.raw(f'<circle cx="{x}" cy="{y}" r="13" fill="{t["card"]}" stroke="{t["red"]}" stroke-width="1.5" opacity=".6"/><circle cx="{x}" cy="{y}" r="8" fill="{t["red"]}"/>')
        else:
            s.raw(f'<circle cx="{x}" cy="{y}" r="8" fill="{t["card"]}" stroke="{t["ink"]}" stroke-width="2.5"/>')
        py = y + 22
        s.raw(f'<rect x="{x}" y="{py}" width="{plate_w}" height="{plate_h}" rx="14" fill="#FFFFFF" stroke="{t["border"]}" stroke-width="1.5"/>')
        s.raw(f'<image x="{x + 14}" y="{py + 10}" width="{plate_w - 28}" height="{plate_h - 20}" href="{logo_uri(logo)}"/>')
        tx = x + plate_w + 18
        s.text(tx, py + 14, dates, MONO, 14.5, t["muted"])
        s.text(tx, py + 41, org, SANS[700], 22, t["text"])
        s.text(tx, py + 65, role, SANS[500], 15.5, t["muted"])
    return s.render()


# --------------------------------------------------------------------------- stack
STACK = [
    ("IA & LLM", ["RAG", "Agents", "LangGraph", "MCP", "pgvector", "RAGAS", "LLM-as-judge", "Mistral"], 1),
    ("Full stack", ["TypeScript", "React", "Next.js", "Node.js", "React Native", "PostgreSQL", "Prisma"], 1),
    ("Ops & données", ["Python", "pytest", "Docker", "CI/CD", "Cloud Run", "n8n", "Neo4j"], 1),
]
CERTIFICATIONS = [
    ("Certifications", ["Neo4j Certified Professional", "Neo4j Graph Data Science", "Using Neo4j with Python", "TOEIC 855/990", "Certificat Voltaire"], 2),
    ("Langues", ["Français", "Tamoul", "Anglais B2"], 1),
]


def chip_panel(theme: str, columns: list, title: str) -> str:
    """Panneau de pastilles en colonnes ; le dernier nombre de chaque colonne est sa largeur relative."""
    t = THEMES[theme]
    W, P, gap, size, height = 1200, 36, 32, 17, 38
    unit = (W - 2 * P - (len(columns) - 1) * gap) / sum(c[2] for c in columns)
    widths = [unit * c[2] for c in columns]
    probe = Svg(W, 10, "")
    bottom = max(chip_row(probe, t, 0, 0, c[1], w, size=size, height=height, gap=10) for c, w in zip(columns, widths))
    H = int(86 + bottom + P)
    s = Svg(W, H, title)
    s.raw(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="22" fill="{t["card"]}" stroke="{t["border"]}" stroke-width="2"/>')
    x = P
    for (name, chips, _), w in zip(columns, widths):
        s.raw(f'<rect x="{x:.1f}" y="44" width="4" height="22" rx="2" fill="{t["red"]}"/>')
        s.text(x + 14, 63, name, SANS[600], 23, t["text"])
        chip_row(s, t, x, 86, chips, w, size=size, height=height, gap=10)
        x += w + gap
    return s.render()


def stack(theme: str) -> str:
    return chip_panel(theme, STACK, "Stack : IA et LLM, full stack TypeScript, ops et données")


def certifications(theme: str) -> str:
    return chip_panel(theme, CERTIFICATIONS, "Certifications Neo4j, TOEIC 855/990, certificat Voltaire. Langues : français, tamoul, anglais B2")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        files = {f"header-{theme}.svg": header(theme), f"timeline-{theme}.svg": timeline(theme), f"stack-{theme}.svg": stack(theme), f"certifications-{theme}.svg": certifications(theme)}
        files.update({f"card-{key}-{theme}.svg": card(key, theme) for key in CARDS})
        for name, content in files.items():
            (OUT / name).write_text(content, encoding="utf-8")
            print(f"{name:28} {len(content) / 1024:6.1f} Ko")


if __name__ == "__main__":
    main()
