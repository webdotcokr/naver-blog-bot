# naver-blog-bot

네이버 검색 결과(블로그 탭 / 카페 탭)의 광고 제외 상위 3개 글을 수집하는 도구.
- **블로그**: 제목, 본문, 이미지 수, 작성일
- **카페**: 제목, 본문, 작성자, 작성일, 게시판 이름, **댓글(대댓글 포함) 전체**

## 셋업

```bash
git clone <repo>
cd naver-blog-bot

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium

# Ubuntu/Debian 서버에서 첫 설치 시 시스템 라이브러리도 필요
sudo .venv/bin/playwright install-deps chromium
```

Python 3.11+ 필요.

## 단일 키워드 실행

### 블로그

```bash
.venv/bin/python run.py "기업 홈페이지 제작"
```
결과: `output/YYYY-MM-DD/{키워드}/{rank}.json`

### 카페

```bash
.venv/bin/python run_cafe.py "기업 홈페이지 제작"
```
결과: `output/YYYY-MM-DD/cafe/{키워드}/{rank}.json`

## 일일 배치 (위에서부터 3개씩)

키워드는 **Google Sheets 또는 `keywords.csv`** 에서 관리합니다.
- `.env`에 `GOOGLE_SHEET_ID`가 설정돼 있으면 시트의 `keywords` 탭을 우선 사용
- 없으면 `keywords.csv` fallback

```bash
.venv/bin/python daily.py        # 기본 3개
.venv/bin/python daily.py 5      # 5개
```

각 키워드에 대해 **블로그 + 카페** 스크래퍼가 모두 실행됩니다 (한쪽 실패해도 다른 쪽은 진행).

### CSV 형식
```csv
keyword,added_at,note,processed_at,result_path
기업 홈페이지 제작,2026-05-11,핵심,,
B2B 홈페이지,2026-05-11,,,
```
- `processed_at` 가 비어있는 키워드를 위에서부터 N개 처리합니다.
- 새 키워드를 추가하려면 csv 맨 아래에 한 줄 추가하면 됩니다.
- CSV 모드에서만 `status.md`가 자동 갱신됩니다.

## Google Sheets 연동 (선택)

키워드 관리·결과 적재를 구글 시트로 하려면 `.env`에 다음 두 줄을 추가:

```bash
GOOGLE_SHEET_ID=<your spreadsheet id>
GOOGLE_CREDENTIALS_PATH=./credentials.json
```

- GCP 서비스 계정 JSON 키를 `credentials.json` 이름으로 프로젝트 루트에 배치
- 시트는 두 개 탭이 필요: `keywords`, `results`
- `keywords` 탭 헤더 (직접 만들기): `keyword | added_at | note | processed_at | result_path`
- `results` 탭 헤더 (첫 실행 시 자동 생성):
  `collected_at | type | keyword | rank | title | url | writer | posted_at | image_count | comment_count | accessible | local_path`

`GOOGLE_SHEET_ID`가 비어있거나 `.env` 자체가 없으면 자동으로 CSV + 로컬 JSON 모드로 fallback.

### 비밀파일 주의
- `credentials.json`, `.env` 는 `.gitignore`에 포함되어 깃에 올라가지 않습니다.
- 절대 다른 사람과 공유하지 마세요 — 시트 + GCP 프로젝트 접근 권한이 들어 있습니다.

## 진행 상태 확인

```bash
.venv/bin/python status.py
cat status.md
```

## cron 등록 (서버 운영용)

서버 timezone이 UTC인 경우 `CRON_TZ`로 한국 시간 처리:

```cron
CRON_TZ=Asia/Seoul
0 8 * * 1-5 cd /opt/naver-blog-bot && .venv/bin/python daily.py >> logs/cron.log 2>&1
```

평일 한국 시간 08:00에 자동 실행됩니다.

## 파일 구조

```
naver-blog-bot/
├── scraper.py            # 블로그 수집기 (Playwright)
├── cafe_scraper.py       # 카페 수집기 (Playwright)
├── sheets_client.py      # Google Sheets 인증/read/append
├── run.py                # 블로그 단일 키워드 실행
├── run_cafe.py           # 카페 단일 키워드 실행
├── daily.py              # 매일 N개 자동 처리 (블로그+카페 동시, cron이 호출)
├── status.py             # status.md 생성
├── keywords.csv          # 키워드 마스터 (사용자가 관리)
├── status.md             # 자동 생성, 진행 상황
├── requirements.txt
├── output/               # 수집 결과 (gitignore)
│   └── YYYY-MM-DD/
│       ├── {키워드}/          # 블로그 결과
│       │   ├── 1.json
│       │   ├── 2.json
│       │   └── 3.json
│       └── cafe/
│           └── {키워드}/      # 카페 결과
│               ├── 1.json
│               ├── 2.json
│               └── 3.json
└── logs/                 # cron 로그 (gitignore)
```

## JSON 스키마

### 블로그
```json
{
  "rank": 1,
  "url": "https://blog.naver.com/{id}/{logNo}",
  "blog_id": "...",
  "log_no": "...",
  "title": "...",
  "body": "...",
  "image_count": 12,
  "posted_at": "2026-03-30T08:52:00+09:00",
  "collected_at": "2026-05-11T20:13:14+09:00"
}
```

### 카페
```json
{
  "rank": 1,
  "url": "https://cafe.naver.com/{cafe}/{articleId}?art=...",
  "cafe_url_id": "move79",
  "article_id": "6060390",
  "board_name": "30대 대화방",
  "title": "홈페이지제작 업체 비교하신다면",
  "writer": "망망고고구구",
  "body": "...",
  "posted_at": "2026-05-14T15:14:00+09:00",
  "comments": [
    {
      "nickname": "리이2리",
      "content": "요즘 홈페이지제작 업체 진짜 많아서...",
      "posted_at": "2026-05-14T17:56:00+09:00",
      "is_reply": false
    }
  ],
  "accessible": true,
  "error": null,
  "collected_at": "2026-05-14T23:28:00+09:00"
}
```

비공개·회원전용 글은 `accessible: false`로 저장되고 `error` 필드에 사유가 남습니다.

## 운영 메모

### 블로그
- 광고 식별: 검색 결과 카드의 부모 컨테이너 텍스트에 "광고" 포함 여부로 판별.
- 블로그탭 URL: `https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query=...`
- 본문 추출: `PostView.naver?blogId=X&logNo=Y` 직접 진입 → `.se-main-container` (구버전은 `#postViewArea` fallback).
- 작성일자: `.se_publishDate` 셀렉터, `YYYY. M. D. H:MM` 형식을 KST ISO로 변환.
- 같은 블로그에서 여러 글이 상위에 동시 노출되는 경우가 흔하며, 의도된 동작입니다.

### 카페
- 카페탭 URL: `https://search.naver.com/search.naver?ssc=tab.cafe.all&query=...`
- 검색 결과 글 URL 패턴: `https://cafe.naver.com/{cafe_url_id}/{article_id}?art=...&q=...&tc=naver_search`
- 글 페이지는 본문이 `name="cafe_main"` iframe 안에 있어, 해당 프레임 로드를 기다린 뒤 추출.
- 제목/게시판: `.ArticleTitle .title_text` / `.ArticleTitle .link_board`
- 본문: `.se-main-container` (실패 시 `.article_viewer`, `.article_container` fallback)
- 댓글: `li.CommentItem` (작성자 `.comment_nickname`, 내용 `.comment_text_view`, 날짜 `.comment_info_date`)
- 대댓글: `.ReplyBox` 하위 또는 클래스명에 `Reply` 포함 시 `is_reply: true`로 표시.
- 댓글 더보기: `.CommentBox .button_more` / `.more_area` 안의 버튼을 끝까지 클릭하여 전체 댓글 펼침.
- 비공개·회원전용 카페 글은 `cafe_main` iframe이 로드되지 않거나 본문이 빈 상태로 잡혀 `accessible: false`로 표시.
