# FitLog

개인 운동·식단·체중·수면을 기록할 모바일 우선 PWA입니다.
FastAPI가 REST API와 HTML/CSS/JavaScript를 함께 제공하고 SQLAlchemy로 SQLite에 접근합니다.
프론트엔드 프레임워크 없이 **단일 컨테이너 + SQLite**로 운영합니다.

현재 **Phase 1**: 기본 DB 모델 6개, DB 연결을 확인하는 헬스 체크,
반응형 초기 대시보드, manifest와 정적 UI 캐시를 구현했습니다.
화면은 실제 데이터가 없는 빈 상태이며, 기록·통계·설정 메뉴는 준비 중입니다.
CRUD, 데이터 집계, Google 인증과 importer 실행은 이후 단계입니다.

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

- 초기 화면: http://localhost:8080 (다른 기기는 http://NAS_IP:8080)
- 헬스 체크: http://localhost:8080/api/health
- OpenAPI: http://localhost:8080/docs

```sh
curl http://localhost:8080/api/health
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
│   ├── models.py               # 기본 테이블 6개
│   ├── schemas.py              # API 응답 스키마
│   ├── api/health.py           # GET /api/health
│   ├── services/importer.py    # 향후 importer 경계 문서
│   └── static/
│       ├── index.html
│       ├── css/app.css
│       ├── js/app.js
│       ├── icons/              # SVG 및 192/512 PNG
│       ├── manifest.json
│       └── service-worker.js
├── tests/test_phase1.py
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
후속 API의 입력 스키마·서비스에서 timezone 검증과 변환을 처리해야 합니다.
수면 duration은 Phase 3 서비스에서 시작·종료 시각으로 계산해 일관성을 보장합니다.
`updated_at`은 SQLAlchemy UPDATE 시 갱신됩니다.

`create_all()`은 최초 생성만 담당하며 기존 테이블을 변경하지 않습니다.
**기존 스키마를 처음 변경하기 전에 Alembic 등 버전별 마이그레이션을 도입**하고,
현재 스키마 baseline 및 기존 DB 업그레이드를 백업과 함께 검증해야 합니다.
RPE/RIR, 세트 시간·거리 등의 확장은 그 마이그레이션으로 추가합니다.

## 개발 방법

Python 3.13 기준, 프로젝트 루트에서:

```sh
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
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
잘못된 수치 거부, nullable 영양·분할 수면, 정적 파일과 PWA 자산을 검증합니다.
Docker 실행 후에는 curl과 모바일/PC 화면을 확인하고, 컨테이너를 재생성한 뒤 DB 유지도 확인하세요.

## PWA와 보안

manifest는 FitLog, standalone 표시, 192/512 PNG 아이콘을 제공합니다.
service worker는 정적 UI만 캐시하며 `/api/*`는 캐시하지 않습니다.
오프라인에서 저장된 초기 화면을 열 수 있지만 기록 저장·동기화는 지원하지 않습니다.
정적 파일 변경 시 service worker의 캐시 버전도 올리세요.

**PWA 설치와 service worker에는 HTTPS 또는 localhost가 필요합니다.**
`http://NAS_IP:8080`에서는 일반 웹페이지로 사용할 수 있지만 PWA 설치는 제한됩니다.
모바일 설치는 NAS reverse proxy에서 HTTPS 설정 후 브라우저의 홈 화면 추가 기능을 사용합니다.
설치 UI는 OS와 브라우저에 따라 다릅니다. 앱은 인증서를 관리하지 않습니다.

현재 로그인/API token은 없습니다. 8080 포트는 신뢰할 수 있는 내부 네트워크에서 사용하세요.
외부 공개 전 reverse proxy 접근 제한이나 인증을 추가해야 합니다.
인증은 추후 API router 공통 dependency로 추가하고 개인 API 응답은 캐시하지 않는 정책을 유지합니다.

## 향후 로드맵

- **Phase 1 (현재)**: 단일 컨테이너, SQLite 기반, 헬스 체크, 초기 대시보드, PWA shell.
- **Phase 2**: 운동·종목·세트 CRUD, 입력 검증·서비스 계층, 운동 목록/상세 UI.
- **Phase 3**: 식단·체중·수면 API/UI, 수면 시간 계산, 목표 설정 설계.
- **Phase 4**: 운동 횟수·세트 수·최고 중량·볼륨, 체중·수면 추이와 차트.
- **Phase 5**: Google Sheets/CSV/XLSX importer, 중복 방지 및 동기화 정책.
- 필요 시: 인증/API token, 업로드 검증, 마이그레이션과 백업 자동화.
