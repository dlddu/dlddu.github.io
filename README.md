# dlddu.github.io

운영 중인 서비스와 각 레포의 GitHub Pages를 한곳에 모아 보여주는 페이지입니다.
목록은 GitHub Actions가 GitHub API로 자동 생성합니다. 손으로 고칠 파일은 없습니다.

## 목록에 올리는 방법

| 목록 | 레포에서 할 일 |
| --- | --- |
| 운영 중인 서비스 | 레포 About(⚙️) → **Website** 칸에 서비스 주소 입력 |
| GitHub Pages | 레포 Settings → Pages 켜기 |
| 숨기기 | 레포에 topic `hub-hide` 추가 |

archived 레포와 fork는 자동으로 빠집니다. Website 칸에 그 레포의 Pages 주소를 적은 경우는 서비스로 중복 집계하지 않습니다.

## 갱신 시점

- 이 레포 `main`에 push할 때
- 매일 06:17 KST
- Actions 탭에서 수동 실행 (`workflow_dispatch`)
- 다른 레포에서 즉시 갱신: `gh api repos/dlddu/dlddu.github.io/dispatches -f event_type=refresh-hub`

## private 레포 포함하기

기본 `GITHUB_TOKEN`으로는 public 레포만 보입니다. private 레포까지 넣으려면
fine-grained PAT(Repository access: All repositories, 권한: Metadata read + Pages read)를 만들어
이 레포 Secrets에 `REPO_LIST_TOKEN`으로 등록하세요.

> 레포가 private이어도 이 페이지는 공개 사이트입니다. 서비스 주소 공개가 곤란한 레포에는 `hub-hide`를 붙이세요.

## 로컬 미리보기

```bash
python3 scripts/build.py --from-json fixtures/sample-repos.json
open _site/index.html
```

## 커스텀 도메인

Settings → Pages → Custom domain에 도메인을 넣으면 됩니다.
이 레포에 도메인을 붙이면 별도 도메인이 없는 다른 레포의 Pages도 `도메인/<레포명>` 아래로 옮겨집니다.
