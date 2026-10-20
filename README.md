# FitLog

개인 운동·식단·체중·수면을 기록할 모바일 우선 PWA입니다.
FastAPI가 REST API와 HTML/CSS/JavaScript를 함께 제공하고 SQLAlchemy로 SQLite에 접근합니다.
프론트엔드 프레임워크 없이 **단일 컨테이너 + SQLite**로 운영합니다.

현재 **Phase 6**: 기록·통계·차트, Excel 업로드 비교·선택 저장과 원본 보존, AI 기록 도우미(문장·사진으로 기록 초안 생성)에 더해
초대받은 지인 여러 명이 Google 계정으로 로그인해 **각자의 기록만** 사용합니다([로그인과 초대](#로그인과-초대)).
통계는 기존 SQLite 데이터를 읽어 계산하며 별도 집계 DB를 만들지 않습니다.

## 통계 사용 방법

하단 ‘통계’ 또는 `/statistics`에서 조회합니다.
7일/30일/90일/1년(최근 365일) 버튼 또는 시작·종료 날짜로 기간을 선택할 수 있습니다.
기본값은 오늘을 포함한 최근 30일이며 최대 366일까지 조회합니다.

- 기본은 **완료 세트만** 집계합니다. ‘미완료 세트 포함’을 선택하고 ‘조회’하면 전체 세트를 계산합니다.
- 운동 횟수, 집계 세트 수, 총 볼륨, 기록일 평균 수면을 요약합니다.
- 주간 세트 수, 일별 운동 볼륨, 체중, 수면 차트를 표시합니다.
- 볼륨 차트에서 전체 또는 개별 종목을 선택할 수 있습니다.
- 종목별 최고 중량·세트 수·볼륨·미입력 세트 수를 표로 표시합니다.
- 차트를 누르거나 포커스 후 좌우 방향키/Home/End로 값을 확인합니다.
  각 차트의 ‘숫자로 보기’에서 동일한 데이터를 표로 읽을 수 있습니다.
- 차트는 로컬 SVG로 그립니다. 외부 차트 라이브러리·CDN·추적 서비스는 사용하지 않습니다.

## 식단·신체·수면 사용 방법

홈의 빠른 기록 또는 요약 카드에서 식단, 체중·신체, 수면으로 이동합니다.
생활 기록 화면의 탭으로 세 종류를 전환할 수 있습니다.

- **식단**: 식사 시각, 구분(아침/점심/저녁/간식/기타), 이름을 입력합니다.
  열량·단백질·탄수화물·지방은 선택 항목입니다. 빈 값은 미입력, 0은 실제 0입니다.
- **체중·신체**: 측정 시각과 체중(kg), 체지방률(%), 골격근량(kg) 중 하나 이상을 입력합니다.
- **수면**: 잠든 시각과 일어난 시각을 날짜까지 입력합니다. 시간을 자동 계산하고
  주 수면/낮잠을 구분합니다. 분할 수면은 별도 기록으로 저장합니다.
- 각 기록은 수정·삭제할 수 있고 날짜 범위로 조회할 수 있습니다. 목록은 최신순이며
  ‘더 보기’로 이전 기록을 조회합니다. 삭제 전 확인을 요청합니다.
- 오프라인 저장은 지원하지 않습니다. 저장 실패 시 입력을 유지합니다.
  통신 시간 초과 시 서버에 저장됐을 수도 있으므로 재입력 전 목록을 새로고침하세요.

## 운동 기록 사용 방법

1. 홈의 ‘오늘의 운동 기록하기’ 또는 하단 ‘운동’을 엽니다.
2. ‘종목 관리’에서 Squat 등의 종목을 등록합니다. 종목 기본 데이터는 자동 삽입하지 않습니다.
3. ‘+ 운동 기록’에서 날짜·제목과 선택적인 부위·시각·메모를 저장합니다.
4. 상세의 ‘+ 세트 추가’에서 종목·세트 번호·중량·횟수·완료 여부를 기록합니다.
5. 각 세트의 완료 표시/취소, 수정·삭제 및 운동 수정·삭제를 사용할 수 있습니다.

중량과 횟수는 모르면 비워둘 수 있고, 0도 기록할 수 있습니다.
날짜 범위로 목록을 조회하고 ‘더 보기’로 이전 기록을 불러옵니다.
운동 삭제 시 소속 세트도 삭제됩니다. 사용 중인 종목은 삭제할 수 없습니다.
종목명을 수정하면 해당 종목을 참조하는 기존 세트에도 새 이름이 표시됩니다.
오프라인에서는 입력을 저장할 수 없으며, 실패 시 입력값을 유지하고 오류를 표시합니다.

## 설치 및 Docker 실행

Docker Engine과 Docker Compose v2가 필요합니다. NAS에서는 프로젝트를 NAS 로컬 디스크에 둡니다.

Compose 기본 실행 사용자는 **UID/GID 1000:1000**인 비root 사용자입니다.
NAS 계정이 다르면 프로젝트 루트의 `.env`에 해당 값을 지정하세요
(Linux/NAS SSH에서 `id -u`, `id -g`로 확인):

```dotenv
FITLOG_UID=1000
FITLOG_GID=1000
```

`data/`와 `data/uploads/`에 이 계정의 읽기·쓰기 권한을 부여하세요.
기존 폴더를 포함해 NAS ACL이 쓰기를 허용해야 합니다.
Dockerfile 단독 실행은 UID/GID 10001:10001을 사용하므로 그에 맞춰 권한을 설정합니다.

프로젝트 루트에서:

```sh
docker compose up -d --build
docker compose ps
docker compose logs -f fitlog
```

- 초기 화면: http://localhost:51881 (다른 기기는 `FITLOG_PUBLIC_URL`의 HTTPS 주소. 로그인 쿠키가 Secure이므로 `http://NAS_IP:51881`로는 로그인할 수 없습니다)
- 헬스 체크: http://localhost:51881/api/health
- OpenAPI: http://localhost:51881/docs

```sh
curl http://localhost:51881/api/health
# {"status":"ok","app":"FitLog"}
```

DB 연결 실패 시 헬스 체크는 503 JSON을 반환합니다.
최초 DB 생성에 실패하면 서버가 시작되지 않으므로 로그와 데이터 폴더 권한을 확인하세요.

중지 및 업데이트:

```sh
docker compose down
docker compose up -d --build
```

## 디렉터리 구조

```text
fitlog/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── app/
│   ├── main.py                 # 앱 수명주기, 보안 헤더·CSRF 정책, 정적 파일 제공
│   ├── database.py             # SQLite 초기화와 세션
│   ├── migrations.py           # 버전별 명시적 migration(v3: 사용자별 소유)
│   ├── models.py               # 사용자·세션·초대·동의 + 사용자별 기록/sync/원본 보존 테이블
│   ├── schemas.py              # 입력 검증 및 API 응답 스키마
│   ├── statistics_schemas.py   # 통계 응답 스키마
│   ├── config.py               # 단백질 목표, 공개 주소, 쿠키 설정
│   ├── admin.py                # 운영자 CLI: 초대·계정 관리
│   ├── auth/google.py          # Google 로그인(OIDC+PKCE), DB 접근 없음
│   ├── api/                   # auth, deps(current_user), records, workouts, statistics, sync, excel, health
│   ├── services/              # 계정·기록·대시보드·통계, Sheets/Excel 가져오기 (모두 user_id 범위)
│   └── static/
│       ├── index.html
│       ├── login.html, invite.html
│       ├── workouts.html
│       ├── records.html
│       ├── statistics.html
│       ├── settings.html
│       ├── css/                # 공통·운동·생활 기록·통계 스타일
│       ├── js/                 # 화면 로직 및 charts.js SVG 렌더러
│       ├── icons/              # SVG 및 192/512 PNG
│       ├── manifest.json
│       └── service-worker.js
├── tests/                     # 통합 테스트(사용자 격리·인증·migration 포함), fixtures/schema_v2.sql
└── data/
    ├── fitlog.db               # 실행 시 생성, Git 제외
    └── uploads/               # 파일 영속 저장, Git 제외
```

## DB 저장 위치와 운영

| 용도 | 컨테이너 | 호스트 |
| --- | --- | --- |
| DB | `/app/data/fitlog.db` | `./data/fitlog.db` |
| 파일 | `/app/data/uploads/` | `./data/uploads/` |

Compose가 `./data:/app/data`를 bind mount하므로 컨테이너 삭제·재생성 후에도 데이터가 유지됩니다.
DB 파일과 uploads 폴더는 앱 시작 시 생성합니다. 실제 데이터는 Docker 이미지와 Git에 포함하지 않습니다.
`FITLOG_DATA_DIR` 환경변수로 저장 디렉터리를 지정하며, Compose에서는 `/app/data`입니다.
로컬 Python 실행의 기본값은 프로젝트의 `data/`입니다.

- 외래키 검사, 30초 busy timeout, WAL 모드를 사용합니다. Uvicorn worker는 하나입니다.
- **실시간 DB를 SMB/NFS 공유에 놓지 마세요.** NAS Docker에서는 NAS 로컬 디스크를 bind mount합니다.
  Windows 매핑 드라이브에서 개발할 때는 DB만 PC 로컬 폴더로 지정하세요.
- 백업은 컨테이너를 정상 중지한 뒤 `data/` 전체를 복사하세요.
  가동 중 DB 파일만 복사하면 WAL에 있는 최신 변경이 누락될 수 있습니다.
- DB와 uploads는 웹 정적 경로로 공개하지 않습니다.

### 모델 및 마이그레이션

`workouts`, `exercises`, `workout_sets`, `meals`, `body_metrics`, `sleep_records`를 생성합니다.
운동 삭제 시 세트는 함께 삭제되고, 사용 중인 운동 종목 삭제는 제한됩니다.
같은 운동 세션·종목의 세트 번호는 고유합니다.
영양 정보는 nullable이며 수면은 여러 행으로 분할 수면과 낮잠을 표현합니다.
음수 수치, 잘못된 시간 순서와 수면 유형 등에는 DB 제약조건을 둡니다.

운동일은 현지 날짜로 저장합니다. 시각은 **UTC로 변환 후 timezone 없는 datetime**으로 저장하는 규칙입니다.
운동 API는 timezone 없는 시각을 거부하고 UTC로 변환합니다. 응답 시각에는 +00:00을 붙입니다.
브라우저의 datetime-local 입력은 기기 현지 시각에서 UTC로 변환합니다.
수면 duration은 서비스에서 UTC 시작·종료 시각의 실제 경과 시간으로 계산합니다.
분 미만은 버리고 최소 1분 이상이어야 합니다. duration_minutes를 직접 입력하면 422입니다.
`updated_at`은 SQLAlchemy UPDATE 시 갱신됩니다.

`create_all()`은 최초 생성만 담당하며 기존 테이블을 변경하지 않습니다.
Phase 5부터 `app/migrations.py`가 SQLite schema version과 기존 DB 자동 백업을 관리합니다.
RPE/RIR 및 동기화 필드는 이 명시적 migration으로 추가됩니다. 이후 변경도 버전별 migration으로 적용합니다.

## 개발 방법

Python 3.13 기준, 프로젝트 루트에서:

```sh
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 51881
```

NAS 공유 폴더에서 Windows로 개발할 때는 서버 실행 전에 DB를 로컬로 지정합니다:

```powershell
$env:FITLOG_DATA_DIR = "$env:LOCALAPPDATA\FitLog\data"
```

API 라우트는 `app/api/`, 스키마는 `app/schemas.py`, 비즈니스 로직은 `app/services/`에 추가합니다.
비공개 라우트는 `CurrentUser`(관리자 전용은 `AdminUser`)를 받고, 서비스에는 `user.id`를 첫 인자로 넘깁니다.
서비스는 모든 조회에 `user_id` 조건을 걸고 다른 사용자의 행은 404로 처리합니다(`persistence.owned`).
새 라우터에 인증을 빠뜨리면 `tests/test_isolation.py`의 가드 테스트가 실패합니다.

가져오기 경로는 모두 같은 원칙으로 구현되어 있습니다. 원본 행을 검증 스키마로 정규화한 뒤 한 트랜잭션에서 사용자 범위로 반영합니다.
`sync_service.py`(전송-중립 행 검증·반영), `excel_import.py`(웹 업로드 비교·선택 저장),
`legacy_xlsx.py`(CLI 일괄 이관, `--user-email` 필수)입니다.

### 테스트

```sh
python -m unittest discover -s tests -v
```

테스트는 임시 로컬 DB를 사용하며 실제 `data/`를 건드리지 않습니다.
헬스 체크·장애 응답, SQLite 설정, 새 연결에서 데이터 유지, 외래키·삭제 전파,
잘못된 수치 거부, nullable 영양·분할 수면, 정적 파일과 PWA 자산, 운동 CRUD·페이지네이션·시간대·중복/충돌 처리를 검증합니다.
Docker 실행 후에는 curl과 모바일/PC 화면을 확인하고, 컨테이너를 재생성한 뒤 DB 유지도 확인하세요.

## PWA와 보안

manifest는 FitLog, standalone 표시, 192/512 PNG 아이콘을 제공합니다.
service worker는 정적 UI만 캐시하며 `/api/*`는 캐시하지 않습니다.
오프라인에서 저장된 초기 화면을 열 수 있지만 기록 저장·동기화는 지원하지 않습니다.
정적 파일 변경 시 service worker의 캐시 버전도 올리세요.
업데이트 후 이전 화면이 보이면 열려 있는 FitLog 탭/PWA를 모두 닫고 다시 실행하세요.

**PWA 설치와 service worker에는 HTTPS 또는 localhost가 필요합니다.**
`http://NAS_IP:51881`에서는 로그인할 수 없습니다(Secure 쿠키, Origin 검사). UGREEN NAS 구성은 [Tailscale Funnel](deploy/ugreen/FUNNEL.md)로 HTTPS 주소를 만들고 51881은 NAS 내부(`127.0.0.1`)에만 엽니다.
모바일 설치는 그 HTTPS 주소에서 브라우저의 홈 화면 추가 기능을 사용합니다.
설치 UI는 OS와 브라우저에 따라 다릅니다. 앱은 인증서를 관리하지 않습니다.

개인 API는 로그인 세션이 필요합니다(`app/api/deps.py`의 `current_user`). 설계: [docs/design/phase6-auth-isolation.md](docs/design/phase6-auth-isolation.md).
화면에서는 `app.js`가 모든 페이지의 API 응답을 확인하여 401이면 `/login?next=<현재 경로>`로 보내고, 로그인 후 원래 화면으로 돌아옵니다. 설정 화면에서 계정·로그아웃·동의 내역을 확인하고 AI 외부 전송 동의를 철회하거나 다시 할 수 있습니다(`/api/me/consents`).
세션은 서버 측 `auth_sessions`에 토큰 해시만 저장하고, 쿠키는 `__Host-fitlog_session`(HttpOnly·Secure·SameSite=Lax)입니다. 유휴 30일, 최대 90일 후 만료됩니다.
다른 Origin·사이트에서 보낸 POST/PUT/DELETE는 403으로 거부하고, 모든 응답에 CSP·nosniff·frame 차단 헤더를 붙입니다. 개인 API 응답은 캐시하지 않습니다.
CSP는 인라인 script/style과 외부 리소스를 허용하지 않으므로 화면 코드는 CSS 클래스와 로컬 파일만 사용하세요.
로그인은 Google 계정(OpenID Connect, PKCE·state·nonce)과 1회용 초대 링크로만 합니다. 공개 가입은 없습니다. 아래 [로그인과 초대](#로그인과-초대)를 참고하세요.
로컬 HTTP 개발에서 Secure 쿠키를 쓸 수 없다면 `FITLOG_INSECURE_COOKIES=1`을 설정합니다(운영 금지).

## 로그인과 초대

**준비 (최초 1회)**

1. 외부에서 접속할 HTTPS 주소를 준비합니다. UGREEN NAS는 [Tailscale Funnel 가이드](deploy/ugreen/FUNNEL.md)로 `https://fitlog.<tailnet>.ts.net`을 만듭니다(직접 소유한 도메인과 reverse proxy도 가능). Google은 IP 주소나 HTTPS가 아닌 redirect 주소를 허용하지 않습니다.
2. Google Cloud 콘솔 → API 및 서비스 → OAuth 동의 화면에서 범위를 `openid`, `email`, `profile`만 추가합니다.
3. 사용자 인증 정보 → OAuth 클라이언트 ID → "웹 애플리케이션"을 만들고, 승인된 리디렉션 URI에 `https://<공개 주소>/auth/google/callback`을 등록합니다. `ts.net` 주소는 도메인 소유 확인이 안 되므로 동의 화면을 "테스트"로 두고 사용자 이메일을 테스트 사용자로 등록합니다.
4. 클라이언트 보안 비밀번호를 `config/google-oauth-client-secret` 파일 한 줄로 저장합니다(Git·이미지에서 제외됨).
5. `.env`에 `FITLOG_PUBLIC_URL`, `FITLOG_OWNER_EMAIL`(본인 Google 이메일), `GOOGLE_OAUTH_CLIENT_ID`를 설정하고 재시작합니다.
6. `/login`에서 본인 Google 계정으로 로그인합니다. 첫 로그인 때만 이메일이 일치하는 관리자 계정에 연결되고, 이후에는 Google 계정 식별자(`sub`)로만 확인합니다.

**지인 초대와 계정 관리** (컨테이너 안에서 실행)

```bash
docker compose exec fitlog python -m app.admin invite --note "민수"
```

출력된 링크는 7일 동안 한 번만 쓸 수 있습니다(`--days 1-30`). 링크를 가진 사람은 누구나 가입할 수 있으므로 개인 메시지로만 보내세요.
링크를 연 사람은 서비스 이용 동의(필수)와 AI 외부 전송 동의(선택)를 각각 확인한 뒤 Google 계정으로 가입합니다. 동의 항목·고지 버전·시각은 `consents`에 기록됩니다.

```bash
docker compose exec fitlog python -m app.admin users
docker compose exec fitlog python -m app.admin disable friend@example.com
docker compose exec fitlog python -m app.admin delete-user friend@example.com --yes
```

`disable`은 즉시 모든 세션을 끝냅니다. `delete-user`는 그 사용자의 모든 기록을 한 트랜잭션에서 삭제하지만, 그 전에 만든 백업 파일에는 남습니다. 관리자 화면이나 다른 사용자의 기록을 열람하는 명령은 의도적으로 두지 않았습니다.

로그인 오류는 `/login?error=<코드>`로만 표시하며 Google 원문 응답·토큰은 화면이나 로그에 남기지 않습니다. 로그인 요청은 IP별 분당 20회로 제한합니다.

## 문장으로 기록하기 (AI)

홈 화면에 하루 일을 자유롭게 적으면 AI가 식단·체중·수면·운동 **초안**을 만들고, 확인·수정한 뒤 **저장을 눌러야만** 기록됩니다.
체중·신체·수면·세트·중량·횟수는 문장에 있는 값만 쓰고, 없으면 빈칸으로 둡니다. **식단의 열량·단백질·탄수화물·지방**은 문장에 없으면 음식과 적힌 양을 기준으로 AI가 추정하며, 초안에 "영양 정보 AI 추정" 표시가 붙고 저장되는 메모에도 "열량·영양소 AI 추정"이 남습니다(값은 저장 전에 수정 가능, "간식"처럼 모호하면 빈칸). 저장은 선택한 초안 전체를 한 트랜잭션으로 처리하며, 하나라도 검증에 실패하면 아무것도 저장하지 않습니다.

- **공용 운영자 키:** 관리자가 설정 → AI 기록 도우미에 Anthropic API 키 하나를 등록하면 모든 사용자가 그 키로 사용합니다. 요금은 운영자 계정에 청구됩니다. 멤버는 키 등록·삭제를 할 수 없고 키 일부도 볼 수 없습니다. 키는 `FITLOG_SECRET_KEY`로 암호화해 `ai_credentials`에 한 행만 저장하고(새 키가 기존 키를 대체), 화면·API로 다시 내보내지 않습니다. 저장할 때 모델 조회로 키만 확인하며 기록 데이터는 보내지 않습니다. 키를 등록한 관리자가 비활성화되면 키도 쓰지 않습니다.
- **동의:** 설정에서 "AI 외부 전송"에 동의한 사용자만 쓸 수 있습니다(`accounts.has_ai_consent`). 고지 버전은 종류별(`accounts.CONSENT_VERSIONS`)이라, AI 고지(2026-10-20, 공용 키로 변경)가 바뀌어도 서비스 이용 동의는 유지되고 AI 동의만 다시 받습니다.
- **사진:** 음식이나 영양성분표 사진을 최대 3장 함께 보낼 수 있습니다(사진만 보내도 됨). AI가 음식 종류·양을 보고 영양을 추정하거나 성분표 값을 읽습니다. 사진은 휴대폰에서 긴 변 1568px JPEG로 다시 인코딩해(위치 등 EXIF 제거) 보내며, 서버는 형식(JPEG/PNG/WebP 헤더)과 크기(장당 5MB)만 확인하고 **저장하지 않습니다**.
- **보내는 데이터:** 입력한 문장과 첨부한 사진, 현재 시각·시간대, 본인 운동 종목 이름 목록뿐입니다.
- **한도:** 사용자별 하루 `FITLOG_AI_DAILY_LIMIT`회(기본 50). 실패한 시도도 셉니다. 운영자가 비용을 부담하므로 사용 인원에 맞게 조정하세요.
- **모델:** `FITLOG_AI_MODEL`(기본 `claude-opus-5-5`, effort `low`, 구조화 출력). 정책상 거절되면 서버 측 대체 모델로 다시 시도합니다(`fallbacks: "default"`). 더 저렴하게 쓰려면 `claude-haiku-5-5`로 바꿀 수 있습니다.
- **코드:** `app/services/claude_records.py`(Claude 호출, DB 접근 없음), `app/services/assistant.py`(키·한도·초안 검증·저장), `app/api/assistant.py`, `app/static/js/assistant.js`.

서버 설정: `.env`에 `FITLOG_SECRET_KEY`(32자 이상)를 넣습니다. 없으면 기능만 비활성화되고 나머지는 그대로 동작합니다. 이 값을 바꾸면 저장된 키를 읽을 수 없어 각자 다시 등록해야 합니다.

## 향후 로드맵

- **Phase 1 (완료)**: 단일 컨테이너, SQLite 기반, 헬스 체크, 초기 대시보드, PWA shell.
- **Phase 2 (완료)**: 운동·종목·세트 CRUD, 입력 검증·서비스 계층, 운동 목록/상세 UI.
- **Phase 3 (완료)**: 식단·체중·수면 CRUD/UI, 수면 시간 계산, 실제 홈 요약과 환경변수 기반 단백질 목표.
- **Phase 4 (완료)**: 운동 횟수·세트 수·최고 중량·볼륨, 체중·수면 추이와 차트.
- **Phase 5 (완료)**: Excel 업로드 비교·선택 저장, 중복 방지, 상태 UI, 원본 Excel 이관/보존. (초기 Google Sheets 수동 동기화는 AI 도입 후 제거)
- **Phase 6 (현재)**: Google 로그인·초대 링크, 사용자별 데이터 격리(schema v3), 세션·CSRF·CSP, 동의 기록, AI 기록 도우미(문장·사진). 설계: [docs/design/phase6-auth-isolation.md](docs/design/phase6-auth-isolation.md).
- 다음 후보: 임의 양식 Excel을 AI로 매핑해 가져오기, 질의응답·리포트.

## Phase 2 REST API

모든 응답은 JSON입니다. 생성은 201, 조회/수정/삭제는 200이며 삭제 응답은
행 본문 대신 `{"status":"deleted"}`입니다. 잘못된 입력은 422, 없는 기록은 404,
중복 이름/세트 번호 또는 사용 중인 종목 삭제는 409, DB 사용 불가는 503입니다.
API 응답에는 `Cache-Control: no-store`를 적용합니다.

| 경로 | 메서드 |
| --- | --- |
| `/api/exercises` | GET, POST |
| `/api/exercises/{id}` | GET, PUT, DELETE |
| `/api/workouts` | GET, POST |
| `/api/workouts/{id}` | GET, PUT, DELETE |
| `/api/workouts/{id}/sets` | GET, POST |
| `/api/workouts/{id}/sets/{set_id}` | GET, PUT, DELETE |

목록 응답은 JSON 배열입니다. 운동·종목 목록은 `limit`(1~100, 기본 50), `offset`(기본 0)을 지원합니다.
운동 목록은 `date_from`, `date_to`(YYYY-MM-DD, 양끝 포함)로 필터링하며 날짜 내림차순,
같은 날짜는 ID 내림차순입니다. 운동 응답은 세트와 각 세트의 종목 정보를 포함합니다.
세트 목록은 종목 ID·세트 번호순입니다.

PUT은 입력 필드 전체 교체입니다. 필수 필드는 다시 보내야 하고 생략한 선택 필드는 기본값으로 초기화됩니다.
운동 PUT은 세트를 변경하지 않습니다. 세트 추가/수정/삭제는 운동의 updated_at도 갱신합니다.
동시 편집은 마지막 저장 우선이며, 서로 다른 기기에서 같은 기록을 편집한 뒤 새로고침으로 확인하세요.
종목명은 앞뒤 공백을 제거한 뒤 고유해야 합니다(대소문자는 구분).
세트 번호는 같은 운동 세션·종목 내에서 고유합니다. 삭제 후 번호를 자동 재정렬하지 않습니다.

운동 생성 예:

```json
{
  "workout_date": "2026-09-25",
  "title": "하체 운동",
  "body_part": "하체",
  "started_at": "2026-09-25T18:00:00+09:00",
  "memo": "첫 기록"
}
```

세트 생성 예(먼저 종목을 생성하고 반환된 ID 사용):

```json
{
  "exercise_id": 1,
  "set_number": 1,
  "weight": 60,
  "reps": 8,
  "completed": true
}
```

Phase 2는 테이블·컬럼을 바꾸지 않고 Phase 1 DB를 그대로 사용합니다.
관계 로딩과 정렬만 ORM에 추가했으며 스키마 마이그레이션은 아직 필요하지 않습니다.
API 상세 스키마는 `/docs`에서 확인할 수 있습니다.

## Phase 3 REST API

| 경로 | 메서드 |
| --- | --- |
| `/api/meals` | GET, POST |
| `/api/meals/{id}` | GET, PUT, DELETE |
| `/api/body-metrics` | GET, POST |
| `/api/body-metrics/{id}` | GET, PUT, DELETE |
| `/api/sleep` | GET, POST |
| `/api/sleep/{id}` | GET, PUT, DELETE |
| `/api/dashboard` | GET |

생성은 201, 조회/수정/삭제는 200 JSON입니다. 잘못된 값은 422, 없는 ID는 404,
수면 시간 중복은 409입니다. PUT은 입력 필드 전체 교체로 선택 필드를 생략하면 null/기본값이 됩니다.
목록은 JSON 배열이며 `limit`(1~100, 기본 50), `offset`(기본 0)을 지원합니다.
`from_at`(포함), `to_at`(미포함)은 timezone이 있는 ISO 8601 시각입니다.
예: `2026-09-24T15:00:00Z`. URL에 +09:00을 쓰면 +를 %2B로 인코딩하세요.
식단은 eaten_at, 신체는 measured_at, 수면은 sleep_end 기준으로 조회·정렬합니다.
화면 날짜 필터는 기기 시간대의 시작일 00:00부터 종료일 다음날 00:00까지로 변환합니다.

모든 입력 시각은 timezone이 필수이며 UTC로 변환해 DB에 저장합니다.
응답 시각에는 +00:00이 붙습니다. API는 알 수 없는 입력 필드와 비유한 수치(NaN/Infinity)를 거부합니다.
`meals.image_path`는 응답에만 포함되고 사진 업로드/경로 입력은 아직 지원하지 않습니다.

식단 입력 예:

```json
{"eaten_at":"2026-09-25T12:00:00+09:00","meal_type":"lunch","name":"닭가슴살 샐러드","protein":35,"calories":null}
```

신체 입력 예:

```json
{"measured_at":"2026-09-25T08:00:00+09:00","weight":78.4,"body_fat":18.2}
```

수면 입력 예:

```json
{"sleep_start":"2026-09-24T23:30:00+09:00","sleep_end":"2026-09-25T06:12:00+09:00","sleep_type":"main"}
```

수면은 시작·종료 간격이 겹치는 기록을 거부합니다. 앞 기록의 종료와 다음 기록의 시작이 같은 것은 허용합니다.
동시 요청의 중복 검사를 위해 수면 저장 서비스는 새 전용 세션에서 SQLite BEGIN IMMEDIATE를 사용합니다.
가져오기 코드에서도 수면 저장은 새 세션으로 호출하고 클라이언트가 계산한 duration은 전달하지 마세요.

### 홈 요약 기준

`GET /api/dashboard?date=2026-09-25&timezone=Asia/Seoul`

- timezone은 IANA 이름이며 기본값은 Asia/Seoul, date를 생략하면 해당 시간대의 오늘입니다.
  브라우저는 기기의 시간대를 보냅니다. 일 경계는 서머타임을 반영합니다.
- 운동: workout_date가 해당 날짜인 세션 수와 전체/완료 세트 수.
- 체중: 해당 날짜 끝 이전의 가장 최근 **체중이 입력된** 측정값과 측정 시각.
  오늘 측정이 없더라도 과거 측정값을 표시하며 화면에 측정 날짜를 표시합니다.
- 단백질: 오늘 식사 중 알려진 값만 합산합니다. 모든 값이 미입력이거나 식단이 없으면 null입니다.
  `meals_count`, `protein_known_count`를 함께 제공하며 UI에서 누락 건수를 안내합니다.
- 수면: **오늘 종료된 기록의 전체 시간** 합계입니다. 자정 이후 구간만 잘라 합산하지 않습니다.
  주 수면과 낮잠을 모두 포함하며 기록이 없으면 null입니다.

단백질 목표는 예시 기본값 150g이며 개인별 권장 섭취량을 계산하는 기능은 아닙니다.
프로젝트 `.env`에서 `FITLOG_PROTEIN_GOAL_G=120`처럼 설정하고 `docker compose up -d`로 적용합니다.
허용 범위는 0 초과~1000g입니다. 설정 UI는 추후 추가합니다.
`tzdata`는 Windows와 컨테이너에서 IANA 시간대 계산을 일관되게 지원하기 위한 의존성입니다.

Phase 3도 기존 6개 테이블을 그대로 사용하며 컬럼 변경·마이그레이션은 없습니다.
통합 테스트는 CRUD, 미입력/0 구분, 자정·시간대·서머타임 경계, 수면 중복과 동시 저장,
운동 기능 회귀를 임시 DB에서 검증합니다. 운영 데이터에는 테스트 기록을 삽입하지 않습니다.

## Phase 4 통계 API와 집계 기준

`GET /api/statistics?date_from=2026-09-01&date_to=2026-09-30&timezone=Asia/Seoul&completed_only=true`

- `date_from`, `date_to`: YYYY-MM-DD, 양 끝 포함. 종료일 기본값은 지정 시간대의 오늘,
  시작일 기본값은 종료일 29일 전입니다. 1~366일만 허용합니다.
- `timezone`: IANA 이름, 기본 Asia/Seoul. 브라우저는 기기 시간대를 사용합니다.
- `completed_only`: 기본 true. false이면 미완료 세트도 포함합니다.
- 응답은 `summary`, `daily`, `weekly`, `exercises`와 적용된 조회 조건을 포함하는 JSON입니다.
  예외는 잘못된 날짜·시간대·기간에 422, DB 사용 불가에 503이며 응답은 캐시하지 않습니다.

### 운동과 볼륨

운동 횟수는 workout_date가 기간 내인 모든 세션 수입니다. 같은 날 여러 번 운동하면 각각 셉니다.
세트가 없거나 완료 세트가 없는 운동도 운동 횟수에 포함합니다.
세트 수·최고 중량·볼륨은 completed_only 조건을 동일하게 적용합니다.
최고 중량은 해당 기간 내 입력된 중량의 최댓값이며 추정 1RM이 아닙니다.

볼륨은 **중량(kg) × 횟수**를 합산하며 단위는 kg·회입니다.
중량 또는 횟수가 null인 세트는 볼륨에서 제외하고, `known_volume_sets`로 계산 가능한 세트 수를 제공합니다.
모든 값이 미입력이면 볼륨은 null이며 실제 0kg/0회는 0으로 계산합니다.
전체·종목별 볼륨 추이는 날짜별 합계이고 같은 날 여러 세션은 합칩니다.
종목별 `daily_volume`에는 해당 종목의 집계 세트가 있는 날짜만 포함합니다.
화면에서는 전체 날짜 축에 맞추고, 값 없는 날을 선으로 이어 추정하지 않습니다.

주간은 월요일~일요일입니다. 첫 주·마지막 주도 선택 기간 밖의 기록을 섞지 않습니다.
`week_start`는 그 주 월요일, `period_start`/`period_end`는 실제 포함된 날짜 범위입니다.
기록 없는 주의 운동·세트 수는 0입니다.

### 체중과 수면

체중은 기기 시간대 기준 날짜별 마지막 **체중이 입력된** 측정값을 사용합니다.
동일 시각에 여러 행이면 ID가 큰 기록을 선택합니다. 신체 기록에 체중이 없으면 제외합니다.
체중 변화는 기간 내 첫 측정일과 마지막 측정일 값의 차이이고, 측정일이 2일 미만이면 null입니다.
기간 이전의 체중을 가져와 채우지 않으며 기록 없는 날짜는 null로 표시합니다.
체중 차트 세로축은 관측 범위에 맞춰 조정하고 단위와 축 범위를 표시합니다.

수면은 Phase 3 홈과 동일하게 **수면이 종료된 현지 날짜에 전체 지속 시간**을 합산합니다.
주 수면과 낮잠을 모두 포함하며, 기록 없는 날짜는 null입니다.
평균 수면은 수면 기록이 있는 날짜만 분모로 사용하고 `sleep_days`를 함께 제공합니다.
일 경계는 IANA 시간대와 서머타임을 반영합니다.

`daily` 배열은 기간의 모든 날짜를 포함합니다. 누락된 체중·수면·볼륨을 0으로 바꾸지 마세요.
차트 아래 표도 동일한 수치를 사용하며 표시할 때만 소수점을 반올림합니다.
통계 서비스는 읽기 전용이며 스키마 변경·마이그레이션 없이 기존 DB에 적용됩니다.


## 데이터 스키마와 이관

기록 조회의 기준은 SQLite입니다. 기존 기록은 설정 화면의 Excel 업로드(아래)와 초기 이관 CLI로 가져옵니다.

### 코드와 SQLite 구조

- `app/sync_schemas.py`: 가져오기 공통 행 계약/컬럼. 표준 데이터 타입과 입력 검증.
- `app/services/sync_service.py`: 검증, ID 매칭, insert/update/skip, 전체 rollback. 전송-중립 로직으로 Excel 비교 저장과 CLI 이관이 함께 씁니다.
- `app/migrations.py`: 기존 DB 자동 백업 후 명시적 버전별 migration(v3는 소유자 컬럼을 위해 테이블 재생성). 스키마 버전은 SQLite `PRAGMA user_version=3`(v3: 사용자별 소유 `user_id`).
- `app/static/settings.html`, `css/settings.css`, `js/settings.js`: 설정·가져오기 화면.
- `app/services/legacy_xlsx.py`: 제공된 7개 시트 형식의 공통 Excel 변환기와 초기 이관 CLI. 일반적인 모든 Excel 구조를 자동 추측하지 않습니다.

workouts/workout_sets/meals/body_metrics/sleep_records에 nullable `external_id`, `source_updated_at`, 기본 local인 `source`를 추가합니다.
각 테이블에 `(source, external_id)` 고유 인덱스를 만들며 외부 ID 없는 기존 로컬 기록은 보존합니다.
workout_sets에는 nullable rpe/rir, meals에는 별도 image_url을 추가합니다. 기존 image_path는 그대로 유지합니다.
`import_archives`는 원본 파일 바이트·셀 데이터·이관 보고서를 저장합니다.
시간은 기존 방식인 UTC-naive DB 저장, API 출력 시 UTC offset, UI에서 로컬 시간으로 표시합니다. Excel의 시각 없는 측정 날짜는 메모에 가정한 정렬 시각을 명시합니다.

기존 DB는 스키마 버전을 올리기 전마다 `data/backups/before-v{대상 버전}-*.db`로 SQLite backup API를 이용해 백업합니다. 파일 복사로 WAL을 누락하지 않습니다.
새 스키마에서는 이전 이미지로 단순 롤백하지 말고, 앱을 멈춘 뒤 해당 백업을 별도 안전한 위치에 복원하여 사용하세요.
운영 중 수동 SQLite 접근은 호스트와 컨테이너가 동시에 쓰지 않도록 하며, 아래 이관은 실행 컨테이너 안에서 수행합니다.

### 첨부 Excel 이관과 보존

원본은 수정하지 않습니다. 준비 단계는 운영 DB에 쓰지 않고 5개 CSV와 plan/report를 생성합니다.
기존 로컬 기록은 유지하며, 첨부 기록에는 고정 외부 ID를 부여합니다. 동일 원본 SHA-256 재이관은 건너뜁니다.

```powershell
# Excel 변환 의존성(openpyxl)은 웹 업로드 지원을 위해 서버에도 포함
python -m pip install -r requirements-import.txt
python -m app.services.legacy_xlsx --prepare 'C:\Users\unlim\Desktop\운동_식사_통합기록.xlsx' --output data/imports/legacy-20260926
# 생성된 report.json / CSV 검토 후, 운영 DB와 동일 컨테이너 환경에서 원자적 반영
docker compose exec fitlog python -m app.services.legacy_xlsx --apply /app/data/imports/legacy-20260926/plan.json --user-email <기록을 받을 사용자 이메일>
```

이관 결과: 실제 웨이트 36행 → 7개 세션/97세트, 러닝·걷기 5회, 야외 활동 1회, 식단 40건, 인바디 2건. 일일 메모 한 행은 기존 날짜의 등 운동에 합쳐 중복 세션을 피했습니다. 수면은 원본에 없습니다.
전체 7개 시트의 169개 비어 있지 않은 행과 원본 XLSX 파일을 보존합니다. 보존한 원본은 중복 이관 방지와 비교 기준으로만 쓰며 앱 화면에서 열람·다운로드하지 않습니다.
루틴/대시보드/입력 예시는 실제 기록 집계에서 제외합니다. 2개 드롭세트와 자세 교정 1개, 중량 미상 코어/맨몸 4세트는 단일 kg×회 값을 만들지 않아 볼륨 집계에서 제외되지만 원문은 보존합니다.
당류/포화지방/나트륨/콜레스테롤/섭취량, 인바디 추가 수치, 러닝 심박/페이스/거리/시간, RIR 범위는 메모와 원본에서 확인할 수 있습니다. 별도 통계 지표로 구조화하지는 않았습니다.
이 파일과 변환 결과는 개인 건강 데이터이므로 `data/` 아래에만 두고 Git에는 넣지 않습니다.


## Excel 업로드 → 비교 → 선택 저장 (v0.6)

[설정](http://localhost:51881/settings) 상단의 **Excel 기록 가져오기**에서 사용합니다.

1. 기존 `운동_식사_통합기록.xlsx`와 같은 7개 시트·컬럼 순서를 유지한 파일을 선택합니다.
2. **기존 기록과 비교**를 누릅니다. 이 단계에서는 운동·식단 등의 기록을 변경하지 않습니다.
3. 신규·변경·동일·확인 필요 건수를 확인합니다. 각 항목을 펼치면 기존 값과 파일 값, 같은 날의 기존 후보를 볼 수 있습니다.
4. 저장할 신규·변경 항목의 **이 기록 저장**을 선택합니다. 기본 선택은 없습니다. 필요하면 전체 선택 버튼을 사용합니다.
5. **선택한 기록 저장**을 누릅니다. 선택하지 않은 데이터와 파일에서 빠진 기존 기록은 그대로 유지합니다. 선택이 없으면 원본 파일만 보관합니다.
6. **최근 Excel 저장 이력**에서 실제 저장한 값의 이전/이후 내용을 확인합니다.

### 매칭 기준과 제한

- 운동: 운동 날짜 + 제목(루틴/세션).
- 세트: 연결된 운동 + 정확한 운동 종목명 + 세트 번호.
- 식단: 식사 시각(UTC로 정규화) + 음식 이름.
- 신체: 측정 시각(UTC로 정규화).
- 이 Excel 양식에 없는 RPE·사진 URL은 기존 값이 있으면 유지합니다.
- 행 번호는 매칭에 사용하지 않습니다. 원본 위치만 달라진 메모는 동일하게 처리합니다.
- 식별 기준이 같은 파일 행이나 DB 후보가 여러 개면 **확인 필요**로 표시하고 해당 항목은 저장할 수 없습니다. 연결된 운동이 모호하면 그 세트도 제외합니다. 원본 중복을 수정하거나 기존 기록을 정리한 뒤 다시 비교하세요.
- 날짜·시각·이름 자체를 바꾸면 새 기록으로 인식될 수 있습니다. 같은 날 후보를 함께 표시하지만 자동으로 합치지 않습니다. 이 경우 해당 신규 항목을 선택하지 말고 기존 기록을 앱에서 수정한 뒤 다시 비교하거나, 별도 기록임을 확인한 경우에만 신규 저장하세요.
- 새 운동의 세트를 선택하면 해당 운동도 함께 선택됩니다. 서버에서도 부모 운동 선택 여부를 검사합니다.
- 현재는 기존 통합기록 양식만 지원합니다. 임의의 Excel 컬럼, 매크로, 암호화 파일, 기록 시트의 수식은 지원하지 않습니다. 수식은 계산하지 않으므로 값으로 붙여 넣어 업로드하세요.

### 저장·업로드 안전성

미리보기는 1시간 동안 유효합니다. 비교 이후 운동·식단·신체·수면·종목 중 하나라도 바뀌면 저장을 거부하고 재비교를 요청합니다.
모든 선택 항목과 원본 보존·변경 이력을 하나의 SQLite 트랜잭션으로 저장합니다. 오류 발생 시 전체 rollback입니다.
동일 저장 요청을 반복해도 한 번만 반영합니다. 이미 저장한 비교에 다른 선택을 보내면 거부합니다.
기록을 변경하는 날짜/수치에 대한 기존 입력 검증을 재사용합니다.

업로드는 .xlsx 최대 5MB, 압축 해제 총 20MB, ZIP 항목 1,000개, 시트당 5,000행/50열, 전체 셀 범위 200,000칸, 변환 기록 5,000개로 제한합니다.
`openpyxl`과 `defusedxml`로 읽으며 파일 내 수식·외부 링크를 실행하지 않습니다. XML 방어 근거: [openpyxl 공식 보안 안내](https://openpyxl.readthedocs.io/en/stable/#security).
비교 초안은 비공개 SQLite `excel_previews`에 저장합니다. 취소하면 제거하고, 만료 초안은 다음 업로드 때 정리합니다. 대기 초안은 최대 20개입니다.
저장된 원본은 `import_archives`, 이전/이후 값과 처리 결과는 `excel_previews`에 보존합니다. 이력 화면/API는 최근 10회를 보여줍니다.
스키마 v2 업그레이드는 기존 DB를 자동 백업한 뒤 새 테이블을 생성합니다.

### API와 코드

- `POST /api/sync/excel/preview?filename=records.xlsx`: XLSX 바이너리 본문, Content-Type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. token/건수/비교 항목 반환.
- `POST /api/sync/excel/{token}/commit`: JSON `{"selected":["0","2"]}`. 선택 키는 해당 미리보기 응답의 key만 사용합니다.
- `DELETE /api/sync/excel/{token}`: 미저장 비교 취소.
- `GET /api/sync/excel/history`: 최근 10개 저장 이력과 변경 전/후 값.

`app/services/excel_import.py`가 비교·선택 저장·동시 변경 검사, `app/api/excel.py`가 업로드 제한/API, `app/static/js/excel-import.js`가 검토 UI를 담당합니다.
배포는 `docker compose up -d --build`로 합니다.

## GitHub Actions와 NAS 이미지 배포

`.github/workflows/ci.yml`이 PR과 main push의 Python 테스트를 실행합니다. main에서 테스트가 통과하면 Linux amd64 이미지를 만들고, 인증 정보와 기존 DB가 없는 임시 컨테이너로 health 응답과 비공개 API의 401 응답을 확인한 뒤 GHCR에 게시합니다. UGREEN DXP4800 Plus는 이 amd64 이미지를 사용합니다.

- 이미지: `ghcr.io/ruymin/fitlog:latest`
- 고정 버전: `ghcr.io/ruymin/fitlog:sha-<전체 40자리 커밋 SHA>`
- Actions 화면: https://github.com/RuyMin/fitlog/actions
- 개인 Google 인증 키, .env, SQLite, 업로드 파일은 빌드 이미지에 포함하지 않습니다.
- GitHub가 제공하는 `GITHUB_TOKEN`의 `packages: write` 권한으로 게시합니다. 별도 Docker Hub 계정이나 NAS 접속용 secret은 필요 없습니다.
- Actions는 NAS를 재시작하지 않습니다. NAS 업데이트는 아래 명령으로 직접 실행합니다.

### 최초 1회 GHCR 공개 설정

첫 이미지 게시 후 GitHub의 사용자 프로필 → Packages → fitlog → Package settings → Change visibility에서 **Public**으로 변경합니다. 저장소가 공개여도 새 패키지는 기본적으로 비공개일 수 있습니다. 공개 전환 후 NAS에서는 GitHub 토큰 없이 pull할 수 있습니다.

### NAS 최초 설치 (빈 DB)

NAS Docker 앱을 설치하고 NAS의 **로컬 디스크**에 배포 폴더를 만드세요. SMB/NFS 경로를 SQLite 저장 위치로 사용하지 마세요. 배포 폴더에는 저장소의 `compose.nas.yml`, `.env.example`만 받아도 됩니다. 기존 PC의 `data/` 또는 백업 DB를 복사하지 마세요.

```bash
mkdir -p data/uploads config
cp .env.example .env
id -u
id -g
```

출력된 NAS 사용자 UID/GID를 `.env`의 `FITLOG_UID`, `FITLOG_GID`에 입력하세요. `data/`는 해당 사용자가 쓰기 가능하고 `config/`의 키는 읽기 가능해야 합니다. NAS의 파일 권한 관리 또는 해당 사용자로 폴더 생성하여 맞추세요. `FITLOG_PORT` 기본값은 51881입니다.

Google 로그인용 OAuth 클라이언트 보안 비밀번호는 `config/google-oauth-client-secret` 파일에 한 줄로 저장하고 `.env`에 `GOOGLE_OAUTH_CLIENT_ID`를 입력하세요. 키 파일은 해당 사용자만 읽을 수 있도록 관리하세요.

```bash
docker compose -f compose.nas.yml pull
docker compose -f compose.nas.yml up -d
docker compose -f compose.nas.yml ps
curl -f http://localhost:51881/api/health
```

`FITLOG_PUBLIC_URL`의 HTTPS 주소에서 관리자 계정으로 로그인합니다. 최초 DB는 `/app/data/fitlog.db`에 자동 생성되며 실제 저장 위치는 NAS 배포 폴더의 `data/fitlog.db`입니다. 앱 업데이트와 무관하게 같은 data/config mount를 유지하세요.

### 업데이트와 이전 이미지 선택

업데이트 전 SQLite 백업을 권장합니다. 실행 중인 `.db` 파일만 복사하면 WAL 변경분이 빠질 수 있으므로 SQLite backup 기능을 사용하세요.

```bash
docker compose -f compose.nas.yml exec -T fitlog python -c "import sqlite3; from datetime import datetime; p='/app/data/backup-'+datetime.now().strftime('%Y%m%dT%H%M%S')+'.db'; s=sqlite3.connect('/app/data/fitlog.db'); d=sqlite3.connect(p); s.backup(d); d.close(); s.close(); print(p)"
docker compose -f compose.nas.yml pull
docker compose -f compose.nas.yml up -d
```

버전을 고정하거나 이전 이미지를 선택하려면 `.env`의 `FITLOG_IMAGE_TAG`를 `sha-<전체 커밋 SHA>`로 바꾸고 동일한 pull/up 명령을 실행하세요. DB 스키마가 변경된 버전에서 되돌릴 때는 이전 이미지와 DB의 호환성을 먼저 확인하고 필요하면 백업 복원 절차를 사용해야 합니다. 이미지 변경만으로 DB 마이그레이션이 되돌아가지는 않습니다.

UGREEN NAS에서 GUI로 만든 기존 컨테이너를 자동 업데이트 방식으로 전환하려면 [전용 전환 가이드](deploy/ugreen/README.md)를 사용하세요. `/volume1/docker/fitlog` 경로와 컨테이너 내부 51881 포트를 사용하는 현재 설치에 맞춰져 있으며, 최초 전환 후 예약 실행으로 이미지 변경 확인·SQLite 백업·컨테이너 교체·기동 검증을 수행합니다.
