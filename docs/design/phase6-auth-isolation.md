# Phase 6 — 인증과 사용자별 데이터 격리 (1단계 설계안)

> 상태: **구현됨** (`feat/multi-user-auth`, 1~6단계). 기준 커밋: `ff6bea0`, 스키마 `user_version=2` → `3`.
> 배포는 [deploy/ugreen/RELEASE-v3.md](../../deploy/ugreen/RELEASE-v3.md) 체크리스트를 따릅니다. 구현하면서 달라진 점은 문서 끝의 "구현 메모"에 있습니다.
> 목표: AI 기능 없이도 지인 약 10명이 **외부 인터넷(HTTPS reverse proxy)** 으로 각자의 기록만 보고 쓸 수 있는 상태.

## 0. 확정된 결정

| 항목 | 결정 | 1단계 설계에 미치는 영향 |
|---|---|---|
| 규모·노출 | ~10명, 외부 인터넷 노출 | 세션 보안, CSRF, 공개 도메인 + HTTPS 필수 |
| 인증 | Google 로그인(OAuth) + **초대 링크로 계정 연결** | 공개 가입 없음. 초대 없이 로그인한 Google 계정은 거부 |
| AI 비용 | 지인 각자 API 키 등록 | 1단계 범위 밖. 단 `users`에 키 저장 컬럼을 미리 두지 않음(3단계에서 암호화 저장 설계) |
| 우선 AI 기능 | 자연어 기록 입력 | 3단계. 1단계의 `owned` 조회·저장 함수가 그대로 재사용됨 |
| AI 전송 동의 | 가입 시 일괄 동의 | 가입 화면에서 받되, **AI 전송 동의는 별도 체크박스로 분리**하고 철회 가능하게 기록(§6) |
| 기존 데이터 | 본인 Google 계정에 귀속 | `FITLOG_OWNER_EMAIL` 로 지정, 첫 로그인 시 바인딩 |

설계 원칙 유지: api → services → models 분리, 서비스는 HTTP 비의존(`user_id: int` 인자), DB CHECK/UNIQUE/FK로 격리 보강, UTC-naive 저장, 명시적 버전 마이그레이션 + 사전 백업, 외부 CDN/추적 없음(로그인 화면도 로컬 정적 파일, Google 로고는 로컬 SVG).

---

## 1. 인증 설계 (Google OAuth + 초대)

### 1.1 흐름

```
[관리자] python -m app.admin invite --note "민수"   → 1회용 링크 /invite/<token> (7일 만료)
[지인]   /invite/<token> 열기 → 이용 안내·동의 화면(§6) → "Google로 계속"
         → GET /auth/google/start?invite=<token>
         → Google 동의 화면 → GET /auth/google/callback?code&state
         → 서버: state·PKCE·nonce 검증, ID token 검증, sub로 사용자 생성·초대 소모
         → 세션 쿠키 발급 → / 로 이동
[재방문] /login → "Google로 로그인" → callback에서 google_sub 로 기존 사용자 조회
         → 없으면 403 "초대받은 계정이 아닙니다" (계정 자동 생성 없음)
```

- **Authorization Code + PKCE(S256)**, `state`, `nonce` 사용. scope는 `openid email profile` 만. Google API 접근 토큰은 저장하지 않음(로그인 확인 후 폐기).
- 사용자 식별은 **`sub`(불변 ID)** 기준. 이메일은 표시·초대 힌트 용도이며 `email_verified=true` 일 때만 받음.
- ID token 검증: `google-auth`의 `google.oauth2.id_token.verify_oauth2_token` 으로 서명·`aud`·`iss`·만료 확인 + `nonce` 비교. 토큰 교환은 `google-auth`의 `requests` transport. (당시 `google-auth`는 gspread 의존성으로 설치돼 있었고, Google Sheets 연동 제거 후에는 로그인용으로 `google-auth`·`requests`를 직접 의존성에 둡니다.)
- redirect URI는 요청 헤더로 만들지 않고 `FITLOG_PUBLIC_URL` 환경변수로 고정(`{PUBLIC_URL}/auth/google/callback`). Host 헤더 조작에 의한 오픈 리다이렉트 방지.
- 로그인 후 이동 경로(`next`)는 같은 origin의 상대 경로만 허용.

### 1.2 관리자(본인) 부트스트랩

- v3 마이그레이션이 `users` 에 `role='admin'`, `email=FITLOG_OWNER_EMAIL`, `google_sub=NULL` 인 소유자 행을 만들고 기존 기록 전부를 이 행에 귀속.
- **바인딩 규칙(1회성)**: `google_sub IS NULL AND role='admin'` 인 행이 있고, 로그인한 Google 계정의 검증된 이메일이 정확히 일치할 때만 `sub` 를 기록. 그 이후에는 `sub` 로만 로그인. 이메일 일치로 계정을 연결하는 경로는 이 하나뿐.

### 1.3 세션

| 항목 | 값 |
|---|---|
| 저장 | 서버 측 `auth_sessions` 테이블. 쿠키에는 32바이트 랜덤 토큰, DB에는 **SHA-256 해시만** |
| 쿠키 | `__Host-fitlog_session`, `HttpOnly; Secure; SameSite=Lax; Path=/` (localhost 개발 시에만 `Secure` 생략 옵션) |
| 만료 | 유휴 30일(슬라이딩, 갱신은 하루 1회만 쓰기) / 절대 90일 |
| 로그아웃 | `POST /auth/logout` → 행 삭제 |
| 강제 종료 | 관리자 CLI `app.admin disable <email>` → `status='disabled'` + 해당 사용자 세션 전부 삭제 |
| 정리 | 만료 세션·OAuth 시도·초대는 로그인/초대 처리 시 함께 삭제(Excel 미리보기 TTL 정리와 같은 방식, 별도 스케줄러 없음) |

### 1.4 CSRF·노출 보호

현재 `sec-fetch-site` 검사가 Excel·Sync 라우터에만 있음 → **공통 미들웨어로 일반화**:

- `/api/*` 의 비안전 메서드(POST/PUT/DELETE)는 `Sec-Fetch-Site: cross-site` 거부, `Origin` 이 있으면 `FITLOG_PUBLIC_URL` origin 과 일치해야 함.
- `SameSite=Lax` 로 타 사이트 POST에 쿠키가 실리지 않음 (이중 방어).
- 보안 헤더 추가: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, 정적 페이지에 `Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'` (외부 CDN 미사용 원칙과 일치. 인라인 스크립트가 있으면 먼저 분리).
- uvicorn `--proxy-headers --forwarded-allow-ips=<proxy IP>` 로 HTTPS 판단. 앱은 HTTP 리다이렉트를 하지 않고 proxy가 담당.
- 로그인·초대 엔드포인트 rate limit: 프로세스 내 IP별 고정 윈도(예: 분당 20회). 워커 1개라 메모리 카운터로 충분.

### 1.5 인가 규칙

| 대상 | 규칙 |
|---|---|
| `/api/health`, `/login`, `/invite/*`, `/auth/*`, `/static/*`, `/manifest.json`, `/service-worker.js` | 공개 |
| HTML 셸(`/`, `/workouts`, …) | 공개 유지(데이터 없음). JS가 `/api/me` 401을 받으면 `/login` 으로 이동 |
| 기록·통계·Excel·원본 보관 API | 로그인 필수, **자기 데이터만** |
| ~~`POST /api/sync/google`, `GET /api/sync/status`~~ | admin 전용이었으나 Google Sheets 연동 제거로 삭제됨 |
| 타인 리소스 ID 접근 | **404** (존재 여부를 노출하지 않음) |

---

## 2. 스키마 (v3)

### 2.1 신규 테이블

```sql
users(
  id INTEGER PK,
  google_sub VARCHAR(255) UNIQUE NULL,           -- 소유자 부트스트랩 전까지만 NULL
  email VARCHAR(320) NOT NULL,
  display_name VARCHAR(100),
  role VARCHAR(10) NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  status VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at DATETIME NOT NULL, last_login_at DATETIME,
  CHECK (google_sub IS NOT NULL OR role = 'admin')
)
auth_sessions(
  id INTEGER PK, token_hash CHAR(64) UNIQUE NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at, last_seen_at, expires_at DATETIME NOT NULL,
  CHECK (expires_at > created_at)
)
oauth_attempts(                                   -- 10분 TTL
  state_hash CHAR(64) PK, code_verifier VARCHAR(128) NOT NULL, nonce VARCHAR(64) NOT NULL,
  invite_id INTEGER REFERENCES invites(id) ON DELETE CASCADE, next_path VARCHAR(200),
  created_at DATETIME NOT NULL
)
invites(
  id INTEGER PK, token_hash CHAR(64) UNIQUE NOT NULL,
  created_by INTEGER NOT NULL REFERENCES users(id),
  note VARCHAR(100), created_at, expires_at DATETIME NOT NULL,
  used_at DATETIME, used_by INTEGER REFERENCES users(id),
  CHECK ((used_at IS NULL) = (used_by IS NULL))
)
consents(
  id INTEGER PK, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('service','ai_transfer')),
  version VARCHAR(20) NOT NULL, granted_at DATETIME NOT NULL, withdrawn_at DATETIME,
  CHECK (withdrawn_at IS NULL OR withdrawn_at >= granted_at)
)
```

모든 시각은 기존 규칙대로 UTC-naive.

### 2.2 기존 테이블 변경

| 테이블 | 변경 | 제약 |
|---|---|---|
| `exercises` | `+ user_id NOT NULL FK` | `name` 전역 UNIQUE → **`UNIQUE(user_id, name)`**, `UNIQUE(id, user_id)` (복합 FK 대상) |
| `workouts` | `+ user_id NOT NULL FK` | `UNIQUE(id, user_id)`, 인덱스 `(user_id, workout_date)` |
| `workout_sets` | `+ user_id NOT NULL` | **복합 FK** `(workout_id, user_id) → workouts(id, user_id)` CASCADE, `(exercise_id, user_id) → exercises(id, user_id)` RESTRICT → 다른 사람의 운동·종목에 세트를 붙이는 것을 **DB가 거부** |
| `meals` | `+ user_id` | 인덱스 `(user_id, eaten_at)` |
| `body_metrics` | `+ user_id` | 인덱스 `(user_id, measured_at)` |
| `sleep_records` | `+ user_id` | 인덱스 `(user_id, sleep_start)`, `(user_id, sleep_end)` |
| 위 5개 sync 테이블 | `uq_{t}_source_external` | `(source, external_id)` → **`(user_id, source, external_id)`** |
| `sync_state` | `+ user_id NOT NULL UNIQUE` | 기존 `id=1` 행을 소유자에게 귀속. 2단계에서 사용자별 행으로 확장 |
| `import_archives` | `+ user_id` | `sha256` UNIQUE → `UNIQUE(user_id, sha256)` |
| `excel_previews` | `+ user_id` | 대기 20건 제한을 사용자별로. 토큰 조회 시 `user_id` 함께 검사 |

`user_id` 는 모두 `REFERENCES users(id) ON DELETE RESTRICT` (사용자 삭제는 §6.4의 명시적 삭제 절차로만).

`meals.image_path` 는 현재 업로드 API가 없어 사용되지 않음. 업로드를 추가할 때는 `data/uploads/<user_id>/` 에 저장하고 `/static` 이 아닌 인증된 엔드포인트로만 제공해야 함 — 이 문서에 제약으로 기록만 해 둠.

---

## 3. 코드 변경

### 3.1 새 모듈

| 파일 | 역할 |
|---|---|
| `app/auth/google.py` | 인증 URL 생성, 코드 교환, ID token 검증. DB 접근 없음(기존 `google_sheets.py` 와 같은 경계) |
| `app/services/accounts.py` | 사용자·초대·세션·동의 처리(HTTP 비의존) |
| `app/api/auth.py` | `/auth/google/start`, `/auth/google/callback`, `/auth/logout`, `/api/me`, `/invite/{token}` |
| `app/api/deps.py` | `CurrentUser = Annotated[User, Depends(current_user)]`, `AdminUser` |
| `app/admin.py` | CLI: `invite`, `list-users`, `disable`, `delete-user` (NAS에서 `docker compose exec`) |
| `app/static/login.html`, `invite.html`, `js/auth.js` | 로그인·초대·동의 화면 (로컬 정적 파일만) |

### 3.2 기존 모듈

- **라우터**: `APIRouter(dependencies=[...])` 로 인증을 강제하고, 핸들러에서 `user: CurrentUser` 를 받아 서비스에 `user.id` 를 전달.
- **서비스 공통**: `persistence.py` 에 `owned(session, model, user_id, record_id)` 를 추가하고 `session.get(model, id)` 직접 사용을 모두 대체. 없거나 타인 소유면 `RecordNotFound`.
- `records.py`, `workouts.py`: 모든 select에 `model.user_id == user_id`. 새 행 생성 시 `user_id` 설정. `save_set` 의 `get_exercise` 도 소유 검사. **수면 겹침 검사는 같은 사용자 범위로 한정.**
- `statistics.py`, `dashboard.py`: 쿼리 8개 전부에 사용자 조건 추가.
- `sync_service.py`: `apply_rows(session, rows, user_id)`. external_id 조회·Exercise 조회·수면 최종 검증 모두 사용자 범위. `state_record` 는 `user_id` 기준. `RUN_LOCK` 은 1단계에서 admin만 쓰므로 유지(2단계에서 사용자별 lock).
- `excel_import.py`: `fingerprint` 를 **사용자 범위 데이터만 해시**하도록 변경(다른 사용자가 저장해도 내 미리보기가 무효화되지 않음). `compare`, `commit_preview`, `discard_preview`, `history` 모두 `user_id`.
- `korean_sheets.py`, `legacy_xlsx.py --apply`: `user_id` 인자 필수. CLI는 `--user-email` 옵션.
- `api/sync.py` archives 조회·다운로드: `user_id` 조건.
- `main.py`: 공통 CSRF·보안 헤더 미들웨어, `auth` 라우터 등록, 401/403 핸들러.
- 프론트엔드: 공통 `fetch` 래퍼(현재 각 JS에 개별 구현)에서 401이면 `/login?next=` 로 이동. 설정 화면에 계정 정보·로그아웃·동의 상태, admin일 때만 동기화 섹션 표시. `service-worker.js` 의 캐시 이름 버전 올림(`/api/`·`/auth/` 는 계속 캐시하지 않음).
- `config.PROTEIN_GOAL_GRAMS`: 1단계에서는 전역 환경변수로 유지. 사용자별 목표는 후속 작업.

### 3.3 환경변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `FITLOG_PUBLIC_URL` | 로그인 사용 시 | 예: `https://fitlog.example.com` (Google은 IP 주소·비HTTPS redirect URI를 허용하지 않으므로 **도메인 필요**) |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | 로그인 사용 시 | Google Cloud 콘솔의 "웹 애플리케이션" 클라이언트. secret은 `config/` 파일 경로로도 받을 수 있게 함(`_FILE` 접미사) |
| `FITLOG_OWNER_EMAIL` | 기존 데이터가 있는 DB를 v3로 올릴 때 | 없으면 마이그레이션이 **시작을 거부**(fail closed) |

OAuth 변수가 없으면 앱은 **시작은 하되** 로그인이 비활성화되고 데이터 API는 전부 401을 반환. 데이터를 열어 둔 채로 동작하는 경우는 없음 (CI 스모크·로컬 첫 실행을 깨지 않기 위함).

Google OAuth 동의 화면: `openid email profile` 만 쓰면 민감 범위가 아님. "테스트" 모드는 테스트 사용자 등록(최대 100명)이 필요하고, "프로덕션" 게시는 기본 범위만 쓰면 검증 부담이 작음 — 게시 시점에 Google 콘솔 안내를 확인할 것.

---

## 4. 마이그레이션 계획 (v2 → v3)

### 4.1 구조 변경

현재 `migrate()` 는 "v2이면 return" 구조. 이를 **버전 사다리**로 바꿈:

```python
STEPS = {2: migrate_v2, 3: migrate_v3}   # 각 단계는 독립 트랜잭션, 성공 시 user_version 갱신
```

새 DB(테이블 없음)는 `create_all` 로 최신 스키마를 만든 뒤 `user_version=3` 만 기록 (기존 동작과 동일).

### 4.2 v3 절차

SQLite는 기존 컬럼에 NOT NULL FK나 UNIQUE 변경을 `ALTER` 로 걸 수 없으므로 공식 권장 방식인 **"새 테이블 생성 → 복사 → 교체"** 를 사용함.

1. **사전 검사**: `user_version == 2`. 기록 테이블에 데이터가 있으면 `FITLOG_OWNER_EMAIL` 필수.
2. **백업**: `backups/before-v3-<UTC>.db` (기존 `before-sync-*` 와 같은 `sqlite3.backup`), `PRAGMA integrity_check` 확인.
3. `PRAGMA foreign_keys=OFF` (트랜잭션 밖에서만 적용됨) → `BEGIN IMMEDIATE`.
4. `users` 등 신규 테이블 생성, 소유자 행 삽입 → `owner_id`.
5. 부모 → 자식 순서로 테이블 재생성: `exercises → workouts → workout_sets → meals → body_metrics → sleep_records → sync_state → import_archives → excel_previews`
   - `CREATE TABLE <t>__v3 (...)` — DDL은 **migration 파일에 명시적으로 작성**(모델에서 자동 생성하지 않음).
   - `INSERT INTO <t>__v3 (..., user_id) SELECT ..., :owner_id FROM <t>` (id 유지).
   - `DROP TABLE <t>` → `ALTER TABLE <t>__v3 RENAME TO <t>` → 인덱스 재생성.
6. 검증: 테이블별 행 수 일치, `PRAGMA foreign_key_check` 결과 없음, `PRAGMA integrity_check = ok`. 하나라도 실패하면 rollback.
7. `PRAGMA user_version=3` → COMMIT → `foreign_keys=ON`.
8. 기존 "DB가 앱보다 새 버전" 검사가 `> 3` 으로 바뀌므로, 구 이미지로 롤백하면 v3 DB에서 **시작을 거부** → 롤백은 백업 파일 복원으로만 수행.

### 4.3 NAS 배포 절차 (이번 릴리스는 수동)

`update.sh` 의 예약 자동 업데이트는 새 이미지가 health 실패 시 멈추기만 하고 자동 복구하지 않음. v3 릴리스는 새 환경변수가 필요하므로:

1. **main 병합 전에** NAS 크론의 자동 업데이트를 일시 중지.
2. 도메인·reverse proxy HTTPS 확인 → Google OAuth 클라이언트 생성(redirect URI 등록) → `.env` 에 §3.3 변수 추가.
3. 수동 백업 → 새 이미지 pull → `compose up` → 로그에서 마이그레이션 완료와 행 수 확인.
4. 본인 Google 로그인 → 기존 기록이 보이는지 확인 → `app.admin invite` 로 지인 초대.
5. 자동 업데이트 재개. `deploy/ugreen/.env.example` 과 README의 NAS 절차 갱신.

### 4.4 CI 영향

`.github/workflows/ci.yml` 의 스모크 검사는 "`/api/health` 200 + 비공개 API 401"을 확인합니다. (초기에는 `/api/sync/status`를 썼으나 Google Sheets 연동 제거 후 `/api/me`로 변경.)

---

## 5. 테스트

### 5.1 기존 테스트가 깨지는 지점

| 파일 | 원인 | 대응 |
|---|---|---|
| `test_phase1.py` | API 호출이 401, `/` 페이지 검사 일부 | 인증 클라이언트 사용. 공개 경로 목록 검사는 유지 |
| `test_phase2.py` (호출 약 50건) | 401. `setUp` 이 모든 테이블을 비워 `users` 도 삭제됨 | 공통 픽스처가 비운 뒤 사용자 재생성 |
| `test_phase3.py` (약 32건) | 401. 수면 겹침 검사 범위 변경 | 픽스처 교체 |
| `test_phase4.py` | 401. 통계 범위 | 픽스처 교체 |
| `test_phase5.py` | 401, sync는 admin 전용, `apply_rows` 시그니처, `(source, external_id)` 인덱스 이름·범위, v2 마이그레이션 백업 테스트 | admin 클라이언트, user_id 인자, 마이그레이션 테스트를 v3 기준으로 갱신 |
| `test_excel_import.py` | 401, `SessionLocal` 로 `Meal` 등을 직접 조회·수정(사용자 미지정), `ImportArchive` sha256 UNIQUE | 직접 생성 시 `user_id` 설정 |
| `test_korean_sheets.py` | `sync_google_sheets`, `apply_rows` 직접 호출 | `user_id` 인자 |
| `test_nas_update.py` | 영향 없음 | — |

공통 대응: `tests/support.py` 에 `make_user(role)` 와 `login(client, user)` (세션 행을 직접 만들고 쿠키를 설정 — 테스트에서는 Google 호출 없음)를 추가하고, `AuthedClient` 헬퍼로 기존 호출 코드는 거의 그대로 유지.

### 5.2 새로 필요한 테스트

**인증**
- 모든 라우트를 순회하며 비공개 경로는 쿠키 없이 401 (공개 목록 외에는 인증이 필수인지 확인하는 **가드 테스트** — 새 라우터를 추가할 때 인증 누락을 방지).
- OAuth: `state` 불일치·재사용·만료, `nonce` 불일치, `email_verified=false`, `aud` 불일치 → 거부 (Google transport는 기존 Sheets 테스트처럼 모의 객체 사용).
- 초대: 만료·재사용·없는 토큰 거부, 초대 없이 처음 보는 `sub` 로 로그인하면 403이고 사용자가 생성되지 않음.
- 소유자 바인딩: 이메일 일치 시 1회만, 이미 `sub` 가 있으면 이메일 일치로 다른 계정이 연결되지 않음.
- 세션: 만료·로그아웃·`disabled` 사용자 즉시 401, 쿠키 속성(`HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-`).
- CSRF: cross-site `Sec-Fetch-Site`, 다른 `Origin` 으로 보낸 POST/PUT/DELETE 거부.
- `next` 오픈 리다이렉트 거부(`//evil.com`, `https://...`).

**격리 (A, B 두 사용자)**
- 리소스별로 B가 A의 ID에 GET/PUT/DELETE → 404, A의 데이터는 그대로.
- 목록·대시보드·통계에 다른 사용자 데이터가 포함되지 않음.
- B가 A의 `exercise_id` 로 세트 생성 → 404. 서비스를 우회해 직접 INSERT 해도 **복합 FK가 거부**.
- 종목 이름: A와 B가 같은 "Squat" 생성 가능, 같은 사용자 안에서는 409.
- 수면: A와 B의 시간이 겹쳐도 각각 저장 가능.
- Excel: B의 미리보기 토큰을 A가 commit/discard 할 수 없음. B가 기록을 저장해도 A의 미리보기 fingerprint는 유효. 같은 파일(sha256)을 A·B 각각 보관 가능.
- Sync: member는 403, admin 동기화 결과는 admin 소유로만 저장.
- `external_id` 가 같아도 사용자가 다르면 충돌하지 않음.

**마이그레이션**
- v2 픽스처 DB(현재 스키마 + 샘플 데이터 + sync 행 + archive + 미리보기) → v3: 행 수·id 보존, 모두 소유자 귀속, `foreign_key_check` 비어 있음, 백업 파일 생성.
- 기존 데이터가 있는데 `FITLOG_OWNER_EMAIL` 이 없으면 시작 거부, DB 변경 없음.
- 중간 실패(예: 강제 예외 주입) 시 rollback 되어 v2 그대로.
- **스키마 동등성**: 마이그레이션한 DB와 `create_all` 로 만든 새 DB의 테이블·컬럼·인덱스·제약이 일치 (명시적 DDL과 모델이 어긋나는 것을 방지).
- v3보다 새 버전 DB면 시작 거부.

---

## 6. 민감정보 처리와 고지

### 6.1 이 앱이 다루는 정보

체중·체지방·골격근, 수면, 식단(사진 포함 가능), 운동 기록 = **건강 관련 정보**. 개인정보보호법상 건강 정보는 민감정보(제23조)로 분류되며, 원칙적으로 다른 동의와 **구분된 별도 동의**가 필요함. 지인 간 비영리 사용이라도 같은 기준으로 설계하는 것을 권장 (법 적용 여부는 이 문서에서 판단하지 않음).

### 6.2 가입 시 동의 화면 (초대 링크 첫 화면)

"가입 시 일괄 동의" 결정에 따라 **한 화면에서** 받되, 항목을 묶지 않고 분리:

1. **[필수] 서비스 이용 및 건강 기록 저장** — 수집 항목, 목적(본인 기록·통계), 저장 위치(운영자 NAS, 국내), 운영자 접근 가능성(관리자는 DB 파일 접근이 가능함을 명시), 보관 기간(탈퇴 시까지), 백업 보관 기간, 삭제 요청 방법.
2. **[선택] AI 기능 사용 시 외부 전송** — 체크하지 않아도 가입 가능. 미동의 시 AI 기능 비활성.
   - 전송 대상: Anthropic(미국) — **국외 이전** 사실을 명시
   - 전송 항목: 사용자가 입력한 문장, 초안 생성에 필요한 종목명 등 최소 컨텍스트(3단계 설계 시 확정 후 고지문 갱신)
   - 사용자 본인 API 키로 호출되므로 해당 데이터에는 **사용자와 Anthropic 간 약관이 적용**됨
   - 보관·학습 정책은 Anthropic 공식 문서 링크로 안내(고지문 작성 시점에 최신 정책 확인)
   - 철회 방법: 설정 화면에서 언제든 철회 가능, 철회 즉시 전송 중단

동의는 `consents` 에 `kind`, `version`, `granted_at` 으로 기록. 고지문을 개정하면 `version` 을 올리고 재동의를 요청.

### 6.3 기술적 보호 조치

- 전송 구간: HTTPS(reverse proxy), `Secure` 쿠키.
- 저장: NAS 로컬 디스크 SQLite. 저장 시 암호화는 NAS 볼륨 암호화로 처리(앱 수준 컬럼 암호화는 1단계 범위 밖). 백업 파일(`data/backups/`)도 같은 민감도로 취급하고 보관 개수·기간을 정함.
- 로그: 요청 본문·기록 값·토큰·이메일을 로그에 남기지 않음 (기존 sync 오류 처리처럼 원문 비노출 원칙 유지).
- 최소 권한: 관리자도 UI로 타인 기록을 조회하는 기능을 두지 않음.
- 세션·초대 토큰은 해시만 저장.

### 6.4 사용자 데이터 삭제

`app.admin delete-user <email>`: 해당 사용자의 기록·세션·동의·archive·미리보기를 한 트랜잭션에서 삭제. 다만 기존 **백업 파일에는 남는다**는 점을 고지문에 명시하고, 백업 보관 기간이 지나면 자연 소멸하도록 운영. (자기 데이터 내보내기는 후속 작업 후보.)

---

## 7. 작업 순서 (1단계 내부)

1. 마이그레이션 사다리 + v3 DDL + 마이그레이션 테스트 (인증 없이도 단독 검증 가능)
2. 서비스 레이어 `user_id` 전파 + 격리 테스트 (테스트 픽스처로 사용자 주입)
3. 세션·`CurrentUser` 의존성·CSRF 미들웨어 + 가드 테스트
4. Google OAuth·초대·동의 + 모의 OAuth 테스트
5. 프론트엔드 로그인·초대·설정 화면, service worker 버전
6. CI 스모크, README(importer 서술 수정 포함), NAS 문서, `.env.example`
7. NAS 수동 배포(§4.3)

각 단계는 기존 테스트 전체 통과를 유지한 상태로 커밋.

## 8. 후속 단계와의 연결

- **2단계(사용자별 Sheets)**: `sync_state.user_id` 를 이미 갖추었으므로 Spreadsheet ID를 사용자 설정으로 옮기고, 각 사용자가 자기 시트를 서비스 계정에 공유하는 방식으로 진행. `RUN_LOCK` 은 사용자별로 변경.
- **3단계(자연어 기록)**: 사용자별 API 키 암호화 저장(서버 비밀키로 암호화한 값을 `user_secrets` 에 저장), `ai_transfer` 동의 확인, 초안 → 미리보기 → 확정 흐름은 `excel_previews` 패턴(사용자 범위 fingerprint 포함)을 재사용.

## 9. 아직 열려 있는 항목

- 공개 도메인과 reverse proxy 구성(UGREEN 기본 proxy / Caddy / Cloudflare Tunnel 등) — OAuth redirect URI에 필요.
- 백업 파일 보관 기간·개수.
- 고지문 문안 확정(§6.2 항목 기준).

## 구현 메모 (설계와 달라진 점)

- `auth_sessions`, `invites`, `oauth_attempts`, `consents`는 기존 sync 테이블처럼 `create_all`로 만듭니다. v3 migration은 `users` 생성과 기존 테이블의 재구성만 담당합니다. 테이블 정의 동등성은 `tests/test_migration_v3.py`가 검사합니다.
- OAuth `state`를 브라우저에 묶는 짧은 수명의 `__Host-fitlog_oauth` 쿠키를 추가했습니다(로그인 CSRF 방지). 콜백 URL만 가진 다른 브라우저는 로그인할 수 없습니다.
- 토큰 교환은 google-auth의 requests transport를 사용합니다. httpx는 런타임 의존성으로 옮기지 않았습니다.
- CSRF 검사는 `cross-site`뿐 아니라 `same-site` 요청도 거부합니다(같은 상위 도메인의 다른 서브도메인 차단).
- 새 설치에서는 시작 시 `FITLOG_OWNER_EMAIL`로 미연결 관리자 행을 만듭니다(`accounts.ensure_owner`).
- 설정 화면의 AI 외부 전송 동의는 초대 화면과 같은 고지 버전으로 다시 동의하거나 철회할 수 있습니다. 이전 버전에 대한 동의는 현재 동의로 보지 않습니다(`accounts.has_ai_consent`).
- 사용하지 않던 `app/services/importer.py`(설명만 있던 파일)를 삭제했습니다.
