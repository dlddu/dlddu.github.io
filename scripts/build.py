#!/usr/bin/env python3
"""dlddu 레포 목록을 GitHub API로 모아 _site/index.html 을 만든다.

수집 규칙
- 서비스: 레포 About 의 Website(homepage) 값이 있는 레포
- GitHub Pages: has_pages 가 켜진 레포 (이 레포 자신은 제외)
- 제외: archived, fork, topic `hub-hide` 가 붙은 레포

토큰
- REPO_LIST_TOKEN 이 있으면 그 토큰으로 private 레포까지 조회한다
  (fine-grained PAT: All repositories, Metadata read + Pages read).
- 없으면 GITHUB_TOKEN 으로 public 레포만 조회한다.

로컬 테스트: python3 scripts/build.py --from-json fixtures.json
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

OWNER = os.environ.get("HUB_OWNER", "dlddu")
SELF_REPO = f"{OWNER}.github.io"
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
        return f"https://{OWNER}.github.io/{repo['name']}/"


def norm(url):
    return (url or "").strip().rstrip("/").lower().removeprefix("https://").removeprefix("http://")


def collect(repos, token):
    services, pages = [], []
    for r in sorted(repos, key=lambda r: r["name"].lower()):
        if r.get("archived") or r.get("fork") or r["name"] == SELF_REPO:
            continue
        if HIDE_TOPIC in (r.get("topics") or []):
            continue
        base = {
            "name": r["name"],
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
            if not home.startswith(("http://", "https://")):
                home = "https://" + home
            services.append({**base, "url": home})
    return services, pages


def card(item):
    e = html.escape
    host = norm(item["url"])
    badge = '<span class="badge">private</span>' if item["private"] else ""
    desc = f'<p class="desc">{e(item["description"])}</p>' if item["description"] else ""
    return f"""      <li class="card">
        <a class="main" href="{e(item['url'])}">
          <span class="name">{e(item['name'])}{badge}</span>
          <span class="host">{e(host)}</span>
        </a>
        {desc}
        <a class="repo" href="{e(item['repo_url'])}">GitHub 레포 →</a>
      </li>"""


def section(title, hint, items):
    body = (
        "\n".join(card(i) for i in items)
        if items
        else f'      <li class="empty">{html.escape(hint)}</li>'
    )
    return f"""  <section>
    <h2>{html.escape(title)} <span class="count">{len(items)}</span></h2>
    <ul class="grid">
{body}
    </ul>
  </section>"""


def render(services, pages, note):
    tpl = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    now = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    sections = "\n".join(
        [
            section("운영 중인 서비스", "레포 About의 Website 칸에 서비스 주소를 넣으면 여기에 나타납니다.", services),
            section("GitHub Pages", "GitHub Pages가 켜진 레포가 아직 없습니다.", pages),
        ]
    )
    return (
        tpl.replace("{{OWNER}}", html.escape(OWNER))
        .replace("{{SECTIONS}}", sections)
        .replace("{{UPDATED}}", now)
        .replace("{{NOTE}}", html.escape(note))
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="API 대신 레포 목록 JSON 파일을 사용 (로컬 테스트용)")
    ap.add_argument("--out", default=str(ROOT / "_site"))
    args = ap.parse_args()

    list_token = os.environ.get("REPO_LIST_TOKEN") or ""
    token = list_token or os.environ.get("GITHUB_TOKEN") or ""

    if args.from_json:
        repos = json.loads(pathlib.Path(args.from_json).read_text(encoding="utf-8"))
        note = "로컬 테스트 데이터"
    else:
        repos = list_repos(token, private_ok=bool(list_token))
        note = "private 레포 포함" if list_token else "public 레포만 표시 중"

    services, pages = collect(repos, token)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(services, pages, note), encoding="utf-8")
    (out / "data.json").write_text(
        json.dumps({"services": services, "pages": pages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"services={len(services)} pages={len(pages)} ({note}) -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
