#!/usr/bin/env python3
"""dlddu 레포 목록을 GitHub API와 hub.yml 로 모아 _site/index.html 을 만든다.

자동 수집 (GitHub API)
- 서비스: 레포 About 의 Website(homepage) 값이 있는 레포
- GitHub Pages: has_pages 가 켜진 레포 (이 레포 자신은 제외)
- 제외: archived, fork, topic `hub-hide` 가 붙은 레포

수동 목록 (hub.yml)
- services / pages / repos 세 목록. 같은 이름이 자동 수집에도 있으면 hub.yml 값이 우선한다.
- private 레포처럼 API로 안 보이는 것, Pages 가 없지만 자주 쓰는 레포를 여기에 적는다.

토큰
- REPO_LIST_TOKEN 이 있으면 그 토큰으로 private 레포까지 조회한다
  (fine-grained PAT: All repositories, Metadata read + Pages read).
- 없으면 GITHUB_TOKEN 으로 public 레포만 조회한다.

로컬 테스트: python3 scripts/build.py --from-json fixtures/sample-repos.json
"""

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import yaml

OWNER = os.environ.get("HUB_OWNER", "dlddu")
SELF_REPO = f"{OWNER}.github.io"
# 사용자 사이트에 커스텀 도메인을 붙였으면 프로젝트 Pages 도 그 아래로 간다.
PAGES_BASE = os.environ.get("HUB_PAGES_BASE", f"https://{OWNER}.github.io").rstrip("/")
HIDE_TOPIC = "hub-hide"
API = "https://api.github.com"
ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))


def gh_get(path, token):
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def list_repos(token, private_ok):
    path = (
        "/user/repos?affiliation=owner&visibility=all&per_page=100"
        if private_ok
        else f"/users/{OWNER}/repos?type=owner&per_page=100"
    )
    repos, page = [], 1
    while True:
        batch = gh_get(f"{path}&page={page}", token)
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def pages_url(repo, token):
    """커스텀 도메인을 반영한 Pages 주소. 조회가 안 되면 기본 주소로 대체."""
    try:
        return gh_get(f"/repos/{repo['full_name']}/pages", token)["html_url"]
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
        return f"{PAGES_BASE}/{repo['name']}/"


def norm(url):
    return (url or "").strip().rstrip("/").lower().removeprefix("https://").removeprefix("http://")


def with_scheme(url):
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else "https://" + url


def collect(repos, token):
    services, pages = [], []
    for r in sorted(repos, key=lambda r: r["name"].lower()):
        if r.get("archived") or r.get("fork") or r["name"] == SELF_REPO:
            continue
        if HIDE_TOPIC in (r.get("topics") or []):
            continue
        base = {
            "name": r["name"],
            "repo": r["name"],
            "description": r.get("description") or "",
            "repo_url": r["html_url"],
            "private": bool(r.get("private")),
        }
        page = None
        if r.get("has_pages"):
            page = r.get("pages_url_resolved") or pages_url(r, token)
            pages.append({**base, "url": page})
        home = (r.get("homepage") or "").strip()
        # Website 칸에 Pages 주소를 적어둔 경우는 서비스로 중복 집계하지 않는다.
        if home and norm(home) != norm(page):
            services.append({**base, "url": with_scheme(home)})
    return services, pages


def load_manual(path):
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        sys.exit(f"{path.name}: 최상위는 services/pages/repos 를 키로 가진 맵이어야 합니다")
    return data


def manual_item(entry, kind, by_name):
    """hub.yml 항목 하나를 카드 데이터로. API로 본 레포면 설명·private 를 채워 준다."""
    if isinstance(entry, str):
        entry = {"repo": entry}
    repo = entry.get("repo")
    name = entry.get("name") or repo
    if not name:
        sys.exit(f"hub.yml {kind}: name 또는 repo 가 필요합니다 — {entry}")
    known = by_name.get(repo or "", {})
    repo_url = entry.get("repo_url") or known.get("html_url") or (
        f"https://github.com/{OWNER}/{repo}" if repo else ""
    )
    if kind == "repos":
        url = repo_url
    elif kind == "pages":
        url = entry.get("url") or f"{PAGES_BASE}/{repo}/"
    else:
        if not entry.get("url"):
            sys.exit(f"hub.yml services: url 이 필요합니다 — {entry}")
        url = entry["url"]
    return {
        "name": name,
        "repo": repo,
        "description": entry.get("description") or known.get("description") or "",
        "repo_url": repo_url,
        "private": bool(entry.get("private", known.get("private", False))),
        "url": with_scheme(url),
    }


def merge(auto, manual):
    """같은 이름은 hub.yml 이 이긴다. 순서: 자동 수집(이름순) 뒤에 수동 추가분."""
    names = {m["name"] for m in manual}
    return [a for a in auto if a["name"] not in names] + manual


def group_by_repo(services, pages, repos):
    """같은 레포의 서비스·Pages·레포 링크를 카드 하나로 묶는다."""
    groups = {}

    def slot(item):
        key = item["repo"] or f"service:{item['name']}"
        g = groups.setdefault(
            key,
            {"title": None, "repo": item["repo"], "repo_url": "", "description": "",
             "private": False, "services": [], "pages": []},
        )
        g["repo_url"] = g["repo_url"] or item["repo_url"]
        g["description"] = g["description"] or item["description"]
        g["private"] = g["private"] or item["private"]
        return g

    for s in services:
        g = slot(s)
        g["services"].append(s["url"])
        # 서비스 이름(econ-monitor 등)이 레포 이름보다 알아보기 쉬우니 제목으로 쓴다.
        g["title"] = g["title"] or s["name"]
    for p in pages:
        slot(p)["pages"].append(p["url"])
    for r in repos:
        slot(r)
    for g in groups.values():
        g["title"] = g["title"] or g["repo"]

    # 서비스가 있는 것 → Pages 만 있는 것 → 레포만 있는 것, 각각 이름순.
    rank = lambda g: (0 if g["services"] else 1 if g["pages"] else 2, g["title"].lower())
    return sorted(groups.values(), key=rank)


def link_row(label, url, cls):
    e = html.escape
    text = norm(url).removeprefix("github.com/")
    return (
        f'<a class="link {cls}" href="{e(url)}"><span class="kind">{label}</span>'
        f'<span class="host" title="{e(url)}">{e(text)}</span></a>'
    )


def card(g):
    e = html.escape
    badge = '<span class="badge">private</span>' if g["private"] else ""
    sub = (
        f'<span class="sub">{e(g["repo"])}</span>'
        if g["repo"] and g["repo"] != g["title"]
        else ""
    )
    desc = f'<p class="desc">{e(g["description"])}</p>' if g["description"] else ""
    links = [link_row("서비스", u, "svc") for u in g["services"]]
    links += [link_row("Pages", u, "pages") for u in g["pages"]]
    if g["repo_url"]:
        links.append(link_row("레포", g["repo_url"], "repo"))
    body = "\n          ".join(links)
    return f"""      <li class="card">
        <div class="head"><span class="name">{e(g['title'])}{badge}</span>{sub}</div>
        {desc}
        <div class="links">
          {body}
        </div>
      </li>"""


def render(groups, counts, note):
    tpl = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    summary = f"서비스 {counts['services']} · Pages {counts['pages']} · 레포 {len(groups)}"
    items = "\n".join(card(g) for g in groups) or '      <li class="empty">아직 목록이 비어 있습니다.</li>'
    sections = f"""  <section>
    <h2>프로젝트 <span class="count">{html.escape(summary)}</span></h2>
    <ul class="grid">
{items}
    </ul>
  </section>"""
    return (
        tpl.replace("{{OWNER}}", html.escape(OWNER))
        .replace("{{SECTIONS}}", sections)
        .replace("{{UPDATED}}", now)
        .replace("{{NOTE}}", html.escape(note))
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="API 대신 레포 목록 JSON 파일을 사용 (로컬 테스트용)")
    ap.add_argument("--manual", default=str(ROOT / "hub.yml"), help="수동 목록 파일")
    ap.add_argument("--out", default=str(ROOT / "_site"))
    args = ap.parse_args()

    list_token = os.environ.get("REPO_LIST_TOKEN") or ""
    token = list_token or os.environ.get("GITHUB_TOKEN") or ""

    if args.from_json:
        repos = json.loads(pathlib.Path(args.from_json).read_text(encoding="utf-8"))
        note = "로컬 테스트 데이터"
    else:
        repos = list_repos(token, private_ok=bool(list_token))
        note = "private 레포 포함" if list_token else "public 레포 + hub.yml"

    by_name = {r["name"]: r for r in repos}
    auto_services, auto_pages = collect(repos, token)
    manual = load_manual(pathlib.Path(args.manual))
    m = {k: [manual_item(e, k, by_name) for e in (manual.get(k) or [])] for k in ("services", "pages", "repos")}

    services = merge(auto_services, m["services"])
    pages = merge(auto_pages, m["pages"])
    fav = m["repos"]

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    groups = group_by_repo(services, pages, fav)
    counts = {"services": len(services), "pages": len(pages)}
    (out / "index.html").write_text(render(groups, counts, note), encoding="utf-8")
    (out / "data.json").write_text(
        json.dumps(
            {"groups": groups, "services": services, "pages": pages, "repos": fav},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(
        f"services={len(services)} pages={len(pages)} repos={len(fav)} ({note}) -> {out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
