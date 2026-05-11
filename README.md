# naver-blog-bot

네이버 블로그 탭의 광고 제외 상위 3개 글을 수집하는 도구.
키워드 1개당 `{rank}.json` 3개를 생성합니다 (제목, 본문, 이미지 수, 작성일, 수집일).

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

```bash
.venv/bin/python run.py "기업 홈페이지 제작"
```

결과: `output/YYYY-MM-DD/{키워드}/{rank}.json`

## 일일 배치 (csv 위에서부터 3개씩)

키워드는 `keywords.csv`에서 관리합니다.

```csv
keyword,added_at,note,processed_at,result_path
기업 홈페이지 제작,2026-05-11,핵심,,
B2B 홈페이지,2026-05-11,,,
```

- `processed_at` 가 비어있는 키워드를 위에서부터 N개 처리합니다 (기본 3개).
- 새 키워드를 추가하려면 csv 맨 아래에 한 줄 추가하면 됩니다.

```bash
.venv/bin/python daily.py        # 기본 3개
.venv/bin/python daily.py 5      # 5개
```

처리 후 `status.md`가 자동 갱신됩니다.

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
├── scraper.py            # Playwright 수집기
├── run.py                # 단일 키워드 실행 (수동)
├── daily.py              # 매일 N개 자동 처리 (cron이 호출)
├── status.py             # status.md 생성
├── keywords.csv          # 키워드 마스터 (사용자가 관리)
├── status.md             # 자동 생성, 진행 상황
├── requirements.txt
├── output/               # 수집 결과 (gitignore)
│   └── YYYY-MM-DD/
│       └── {키워드}/
│           ├── 1.json
│           ├── 2.json
│           └── 3.json
└── logs/                 # cron 로그 (gitignore)
```

## JSON 스키마

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

## 운영 메모

- 광고 식별: 검색 결과 카드의 부모 컨테이너 텍스트에 "광고" 포함 여부로 판별.
- 블로그탭 URL: `https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query=...`
- 본문 추출: `PostView.naver?blogId=X&logNo=Y` 직접 진입 → `.se-main-container` (구버전은 `#postViewArea` fallback).
- 작성일자: `.se_publishDate` 셀렉터, `YYYY. M. D. H:MM` 형식을 KST ISO로 변환.
- 같은 블로그에서 여러 글이 상위에 동시 노출되는 경우가 흔하며, 의도된 동작입니다.
