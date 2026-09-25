# FitLog

개인 운동·식단·체중·수면을 기록할 모바일 우선 PWA입니다.
FastAPI가 REST API와 HTML/CSS/JavaScript를 함께 제공하고 SQLAlchemy로 SQLite에 접근합니다.
프론트엔드 프레임워크 없이 **단일 컨테이너 + SQLite**로 운영합니다.

현재 **Phase 5**: 기록·통계·차트와 Google Sheets 수동 동기화, 기존 Excel 기록 이관을 제공합니다.
통계는 기존 SQLite 데이터를 읽어 계산하며 별도 집계 DB를 만들지 않습니다.
설정 화면, 사진 업로드, importer는 이후 단계입니다.

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

- 초기 화면: http://localhost:51881 (다른 기기는 http://NAS_IP:51881)
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
│   ├── main.py                 # 앱 수명주기, 정적 파일 제공
│   ├── database.py             # SQLite 초기화와 세션
│   ├── models.py               # 기록 6개 + sync/원본 보존 테이블
│   ├── schemas.py              # 입력 검증 및 API 응답 스키마
│   ├── statistics_schemas.py   # 통계 응답 스키마
│   ├── config.py               # 단백질 목표 환경 설정
│   ├── api/                   # health.py, workouts.py, records.py, statistics.py
│   ├── services/              # 운동·생활 기록·대시보드·통계 및 importer 경계
│   └── static/
│       ├── index.html
│       ├── workouts.html
│       ├── records.html
│       ├── statistics.html
│       ├── css/                # 공통·운동·생활 기록·통계 스타일
│       ├── js/                 # 화면 로직 및 charts.js SVG 렌더러
│       ├── icons/              # SVG 및 192/512 PNG
│       ├── manifest.json
│       └── service-worker.js
├── tests/                     # Phase 1~4 통합 테스트
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
향후 CSV/XLSX/Google Sheets adapter는 데이터를 입력 스키마로 정규화하고,
REST API와 동일한 서비스를 호출합니다. 현재 importer 파일은 이 경계만 문서화합니다.

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
`http://NAS_IP:51881`에서는 일반 웹페이지로 사용할 수 있지만 PWA 설치는 제한됩니다.
모바일 설치는 NAS reverse proxy에서 HTTPS 설정 후 브라우저의 홈 화면 추가 기능을 사용합니다.
설치 UI는 OS와 브라우저에 따라 다릅니다. 앱은 인증서를 관리하지 않습니다.

현재 로그인/API token은 없습니다. 51881 포트는 신뢰할 수 있는 내부 네트워크에서 사용하세요.
외부 공개 전 reverse proxy 접근 제한이나 인증을 추가해야 합니다.
인증은 추후 API router 공통 dependency로 추가하고 개인 API 응답은 캐시하지 않는 정책을 유지합니다.

## 향후 로드맵

- **Phase 1 (완료)**: 단일 컨테이너, SQLite 기반, 헬스 체크, 초기 대시보드, PWA shell.
- **Phase 2 (완료)**: 운동·종목·세트 CRUD, 입력 검증·서비스 계층, 운동 목록/상세 UI.
- **Phase 3 (완료)**: 식단·체중·수면 CRUD/UI, 수면 시간 계산, 실제 홈 요약과 환경변수 기반 단백질 목표.
- **Phase 4 (완료)**: 운동 횟수·세트 수·최고 중량·볼륨, 체중·수면 추이와 차트.
- **Phase 5 (현재, 완료)**: Google Sheets 단방향 수동 import, 중복 방지, 상태 UI, 원본 Excel 이관/보존.
- 필요 시: 인증/API token, 업로드 검증, 마이그레이션과 백업 자동화.

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
향후 importer에서도 수면 저장은 새 세션으로 호출하고 클라이언트가 계산한 duration은 전달하지 마세요.

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


## Phase 5 — Google Sheets 수동 동기화

기록 조회의 기준은 계속 SQLite입니다. Google은 수동 동기화 시에만 호출합니다.
`/settings`에서 연결 상태, 최근 성공/실패, 종류별 추가/수정/유지 건수를 확인하고 **지금 동기화**를 실행합니다.

### 인증과 라이브러리

서비스 계정 JSON 키를 사용합니다. 브라우저 OAuth 로그인은 없습니다.
`gspread==6.2.1`을 선택했습니다. Spreadsheet ID로 열기와 여러 탭 일괄 읽기를 간결하게 구현할 수 있고 Google SDK 전체가 필요하지 않습니다.
google-auth는 gspread의 의존성입니다. 인증 갱신과 API 요청에는 타임아웃을 적용하며 자동 무한 재시도는 없습니다.
현재 권한(scope)은 `spreadsheets.readonly` 하나입니다. Drive 목록 탐색이나 Google 쓰기는 하지 않습니다.
서비스 계정을 대상 문서에 공유해야 합니다. 현재 import에는 **뷰어**로 충분하며, 향후 export용으로 **편집자**를 부여해도 이번 앱은 읽기만 합니다.

공식 문서: [gspread 서비스 계정 인증](https://docs.gspread.org/en/latest/oauth2.html), [Google 서비스 계정 생성](https://cloud.google.com/iam/docs/service-accounts-create), [JSON 키 생성](https://cloud.google.com/iam/docs/keys-create-delete).

### Google Cloud부터 연결까지

1. Google Cloud Console에서 프로젝트를 만들거나 선택합니다.
2. API 및 서비스 → 라이브러리에서 **Google Sheets API**를 활성화합니다. 현재 기능에는 Google Drive API 활성화가 필요하지 않습니다.
3. IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기. 이름 예: fitlog-sync. 프로젝트 관리자 같은 광범위한 IAM 역할은 필요하지 않습니다.
4. 생성한 계정 → 키 → 키 추가 → 새 키 만들기 → JSON. 조직 정책이 키 생성을 막으면 관리자의 정책 절차를 따릅니다.
5. 받은 JSON을 NAS/PC 프로젝트의 `config/google-service-account.json`에 저장합니다. JSON 내용은 코드/채팅/로그에 붙여 넣지 않습니다. 컨테이너 UID가 읽을 수 있게 호스트 파일 권한을 설정합니다.
6. Google Sheets에서 Spreadsheet 하나를 만들고 [템플릿 가이드](docs/google-sheets-template.md)의 5개 탭을 준비합니다. 첨부 기록을 이어 쓰려면 `data/imports/legacy-20260926/`의 CSV 5개를 사용하세요. 예제 CSV와 혼합하지 않습니다.
7. Spreadsheet의 **공유** 버튼 → JSON의 `client_email`에 해당하는 서비스 계정 이메일(예: fitlog-sync@PROJECT_ID.iam.gserviceaccount.com)을 추가합니다. 보기 권한 또는 요청하신 편집 권한을 부여합니다. 일반 공개 링크로 바꿀 필요는 없습니다.
8. URL `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`의 `{SPREADSHEET_ID}` 부분만 복사합니다.
9. `.env.example`을 `.env`로 복사하고 `GOOGLE_SPREADSHEET_ID`를 입력합니다. credential 경로는 **컨테이너 안 경로**입니다.
10. 프로젝트 폴더에서 `docker compose up -d --build`를 실행합니다. 환경변수 변경은 단순 restart 대신 compose up으로 컨테이너를 재생성합니다.
11. [설정](http://localhost:51881/settings)에서 지금 동기화를 실행하거나 아래 API를 호출합니다.

```powershell
cd F:\Projects\fitlog
Copy-Item .env.example .env  # 처음 한 번만; 기존 .env를 덮어쓰지 마세요
# .env 편집 및 JSON 파일 배치 후
docker compose up -d --build
Invoke-RestMethod http://localhost:51881/api/sync/status
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body '{}' http://localhost:51881/api/sync/google
```

```bash
curl -X POST -H 'Content-Type: application/json' -d '{}' http://localhost:51881/api/sync/google
```

### 환경변수

| 변수 | 기본값 |
|---|---|
| GOOGLE_SERVICE_ACCOUNT_FILE | /app/config/google-service-account.json |
| GOOGLE_SPREADSHEET_ID | 빈 값 |
| GOOGLE_WORKSHEET_WORKOUTS | workouts |
| GOOGLE_WORKSHEET_WORKOUT_SETS | workout_sets |
| GOOGLE_WORKSHEET_MEALS | meals |
| GOOGLE_WORKSHEET_BODY_METRICS | body_metrics |
| GOOGLE_WORKSHEET_SLEEP | sleep |

Compose는 `./config:/app/config:ro`로 디렉터리를 읽기 전용 마운트합니다. 파일 자체를 필수 bind하지 않으므로 JSON이 없어도 앱은 정상 시작하며 Sync만 Not configured입니다.
Docker secret을 쓰면 secret 마운트를 추가하고 GOOGLE_SERVICE_ACCOUNT_FILE을 `/run/secrets/google-service-account.json`으로 설정해도 됩니다.
`.env`, credential JSON, `*.key.json`은 Git 제외, config 전체와 환경 파일은 Docker 빌드 컨텍스트에서도 제외합니다. 키는 이미지에 포함하지 않습니다.
Sync API도 기존 앱과 같이 로그인 없이 동작합니다. 개인 LAN/VPN에서 사용하고 외부 접근 시 NAS reverse proxy 인증/HTTPS와 접근 제한을 적용하세요.
JSON 키/토큰/Google 원문 예외를 UI/로그로 출력하지 않으며 DB 오류도 안전한 메시지로 치환합니다.

### 코드와 SQLite 변경

- `app/services/google_sheets.py`: 서비스 계정 인증, 타임아웃, 5개 탭 일괄 읽기, 안전한 Google 오류 변환. DB 접근 없음.
- `app/sync_schemas.py`: 외부 행 계약/컬럼. 표준 데이터 타입과 입력 검증.
- `app/services/sync_service.py`: 검증, ID 매칭, insert/update/skip, 전체 rollback, 결과와 최근 상태. 독립 함수 `sync_google_sheets()`는 향후 scheduler에서도 재사용할 수 있습니다.
- `app/api/sync.py`: GET `/api/sync/status`, POST `/api/sync/google`, 원본 자료 목록/조회/다운로드.
- `app/migrations.py`: 기존 DB 자동 백업 후 명시적 additive migration. 스키마 버전은 SQLite `PRAGMA user_version=1`.
- `app/static/settings.html`, `css/settings.css`, `js/settings.js`: 관리 화면.
- `app/services/legacy_xlsx.py`: 제공된 7개 시트 형식의 1회성 Excel 변환/이관 도구. 일반적인 모든 Excel 구조를 자동 추측하지 않습니다.

workouts/workout_sets/meals/body_metrics/sleep_records에 nullable `external_id`, `source_updated_at`, 기본 local인 `source`를 추가합니다.
각 테이블에 `(source, external_id)` 고유 인덱스를 만들며 외부 ID 없는 기존 로컬 기록은 보존합니다.
workout_sets에는 nullable rpe/rir, meals에는 별도 image_url을 추가합니다. 기존 image_path는 그대로 유지합니다.
`sync_state`는 연결 문서와 최근 결과/오류, `import_archives`는 원본 파일 바이트·셀 데이터·이관 보고서를 저장합니다.
시간은 기존 방식인 UTC-naive DB 저장, API 출력 시 UTC offset, UI에서 로컬 시간으로 표시합니다. Excel의 시각 없는 측정 날짜는 메모에 가정한 정렬 시각을 명시합니다.

기존 DB는 최초 업그레이드 전에 `data/backups/before-sync-*.db`로 SQLite backup API를 이용해 백업합니다. 파일 복사로 WAL을 누락하지 않습니다.
새 스키마에서는 이전 이미지로 단순 롤백하지 말고, 앱을 멈춘 뒤 해당 백업을 별도 안전한 위치에 복원하여 사용하세요.
운영 중 수동 SQLite 접근은 호스트와 컨테이너가 동시에 쓰지 않도록 하며, 아래 이관은 실행 컨테이너 안에서 수행합니다.

### 첨부 Excel 이관과 보존

원본은 수정하지 않습니다. 준비 단계는 운영 DB에 쓰지 않고 5개 CSV와 plan/report를 생성합니다.
기존 로컬 기록은 유지하며, 첨부 기록에는 고정 외부 ID를 부여합니다. 동일 원본 SHA-256 재이관은 건너뜁니다.
CSV를 Google Sheets에 올릴 때 이 ID를 유지하면 최초 Google sync도 중복 insert하지 않습니다.

```powershell
# 로컬 변환 전용 의존성(openpyxl); 서버 Docker 이미지에는 필요하지 않음
python -m pip install -r requirements-import.txt
python -m app.services.legacy_xlsx --prepare 'C:\Users\unlim\Desktop\운동_식사_통합기록.xlsx' --output data/imports/legacy-20260926
# 생성된 report.json / CSV 검토 후, 운영 DB와 동일 컨테이너 환경에서 원자적 반영
docker compose exec fitlog python -m app.services.legacy_xlsx --apply /app/data/imports/legacy-20260926/plan.json
```

이관 결과: 실제 웨이트 36행 → 7개 세션/97세트, 러닝·걷기 5회, 야외 활동 1회, 식단 40건, 인바디 2건. 일일 메모 한 행은 기존 날짜의 등 운동에 합쳐 중복 세션을 피했습니다. 수면은 원본에 없습니다.
전체 7개 시트의 169개 비어 있지 않은 행과 원본 XLSX 파일을 보존합니다. 설정 화면에서 원본 전체 내용과 Excel 다운로드를 제공합니다.
루틴/대시보드/입력 예시는 실제 기록 집계에서 제외합니다. 2개 드롭세트와 자세 교정 1개, 중량 미상 코어/맨몸 4세트는 단일 kg×회 값을 만들지 않아 볼륨 집계에서 제외되지만 원문은 보존합니다.
당류/포화지방/나트륨/콜레스테롤/섭취량, 인바디 추가 수치, 러닝 심박/페이스/거리/시간, RIR 범위는 메모와 원본에서 확인할 수 있습니다. 별도 통계 지표로 구조화하지는 않았습니다.
이 파일과 변환 결과는 개인 건강 데이터이므로 `data/` 아래에만 두고 Git에는 넣지 않습니다.

### 검증 및 다음 단계

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

테스트는 임시 SQLite와 모의 Google transport를 사용합니다. 미설정 실행, 잘못된 ID/권한/timeout, 정상 insert, 반복 skip, 최신 update, 오래된 버전 무시, 원자적 rollback, 중복 ID, 시간대/수면 충돌, 로컬 데이터 보존, migration 백업을 검증합니다.
실제 Google 인증/공유 권한의 최종 연결 검증은 사용자 JSON 키와 실제 Spreadsheet 설정 후 해야 합니다. 모의 테스트를 실계정 연결 성공으로 간주하지 않습니다.

Phase 1–5 기본 구현 완료. 이번 범위에는 Google export, 자동 주기 sync, OAuth, Drive 파일 탐색, 여러 Spreadsheet·사용자가 없습니다.
후속 작업 후보는 인증/API token, 로컬 편집 충돌 정책, 양방향 export, 자동 sync, 러닝 및 확장 영양정보 전용 모델/통계입니다.
