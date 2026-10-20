"""Gera docs/assets/contributors.svg com os avatares de quem contribuiu com o repositório.

Junta duas fontes da API do GitHub:
- a lista de contribuidores (autores de commits no branch principal);
- os coautores declarados nos commits ("Co-Authored-By: Nome <email>"), que a lista
  do GitHub não conta. E-mails noreply do GitHub viram o login; outros e-mails são
  buscados na API de commits.

Contas do tipo Bot ficam de fora. Uso:
    GITHUB_TOKEN=... python scripts/contributors.py [owner/repo]
"""
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REPOSITORY", "data-hackers-br/state-of-data-brazil")
OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "contributors.svg"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
SIZE, CELL, GAP, PER_ROW, LABEL = 64, 100, 8, 10, 18  # avatar, largura da coluna (cabe o login), espaço

# E-mails de coautoria que não são do GitHub, com a conta correspondente. A busca da API
# serve de alternativa, mas tem limite de requisições e às vezes volta vazia.
KNOWN_EMAILS = {"noreply@anthropic.com": "claude"}


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "state-of-data-contributors",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def paged(path):
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        items = api(f"{path}{sep}per_page=100&page={page}")
        if not items:
            return
        yield from items
        page += 1


def login_for_email(email, cache={}):
    """Login do GitHub ligado a um e-mail de coautor, ou None."""
    m = re.match(r"^(?:\d+\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$", email)
    if m:
        return m.group(1)
    if email.lower() in KNOWN_EMAILS:
        return KNOWN_EMAILS[email.lower()]
    if email not in cache:
        q = urllib.parse.quote(f"author-email:{email}")
        try:
            items = api(f"search/commits?q={q}&per_page=1").get("items", [])
            cache[email] = (items[0].get("author") or {}).get("login") if items else None
        except Exception:
            cache[email] = None
    return cache[email]


def collect():
    people = {}  # login -> {"commits": n, "avatar": url, "type": t}
    for c in paged(f"repos/{REPO}/contributors"):
        people[c["login"]] = {"commits": c["contributions"], "avatar": c["avatar_url"], "type": c.get("type", "User")}
    for commit in paged(f"repos/{REPO}/commits"):
        message = commit["commit"]["message"]
        for email in re.findall(r"(?im)^co-authored-by:.*<([^>]+)>", message):
            login = login_for_email(email.strip())
            if not login:
                continue
            if login not in people:
                user = api(f"users/{login}")
                people[login] = {"commits": 0, "avatar": user["avatar_url"], "type": user.get("type", "User")}
            people[login]["commits"] += 1
    people = {k: v for k, v in people.items() if v["type"] != "Bot"}
    return sorted(people.items(), key=lambda kv: (-kv[1]["commits"], kv[0].lower()))


def avatar_data(url):
    sep = "&" if "?" in url else "?"
    with urllib.request.urlopen(f"{url}{sep}s={SIZE * 2}", timeout=30) as r:
        mime = r.headers.get_content_type() or "image/png"
        return f"data:{mime};base64,{base64.b64encode(r.read()).decode()}"


def render(people):
    cols = min(PER_ROW, max(1, len(people)))
    rows = (len(people) + cols - 1) // cols
    cell_w, cell_h = CELL + GAP, SIZE + LABEL + GAP
    w, h = cols * cell_w - GAP, rows * cell_h - GAP
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
             "<style>text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:11px;fill:#8b949e}</style>"]
    for i, (login, p) in enumerate(people):
        cx, y = (i % cols) * cell_w + CELL / 2, (i // cols) * cell_h
        x = cx - SIZE / 2
        label = login if len(login) <= 16 else login[:15] + "…"
        cid = f"c{i}"
        parts.append(f'<a xlink:href="https://github.com/{login}" target="_blank"><title>{login} ({p["commits"]} commits)</title>'
                     f'<clipPath id="{cid}"><circle cx="{x + SIZE / 2}" cy="{y + SIZE / 2}" r="{SIZE / 2}"/></clipPath>'
                     f'<image x="{x}" y="{y}" width="{SIZE}" height="{SIZE}" clip-path="url(#{cid})" xlink:href="{avatar_data(p["avatar"])}"/>'
                     f'<text x="{cx}" y="{y + SIZE + 13}" text-anchor="middle">{label}</text></a>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    people = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    svg = render(people)
    changed = not OUT.exists() or OUT.read_text(encoding="utf-8") != svg
    OUT.write_text(svg, encoding="utf-8")
    print(", ".join(f"{login} ({p['commits']})" for login, p in people), "->", "atualizado" if changed else "sem mudança")
