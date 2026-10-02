# UGREEN DXP4800 Plus: 기존 GUI 컨테이너에서 자동 업데이트로 전환

이 구성은 `/volume1/docker/fitlog/data`, `/volume1/docker/fitlog/config`, NAS/컨테이너 포트 `51881`, 실행 사용자 `10001:10001`을 유지합니다. 기존 GUI의 PUID/UID/USER_ID/GID/GROUP_ID/PGID 환경변수는 이미지가 처리하지 않으므로 복사하지 않습니다. Python/PATH 등 이미지 기본 환경변수도 복사하지 않습니다. 바뀐 내부 포트에 맞춰 상태 검사도 51881을 사용합니다.

## 1. 파일 배치

NAS SSH에서 실행합니다. 기존 data/config를 삭제하거나 PC의 DB로 덮어쓰지 마세요.

```bash
mkdir -p /volume1/docker/fitlog/automation
cd /volume1/docker/fitlog/automation
curl -fSLo compose.yml https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/compose.yml
curl -fSLo update.sh https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/update.sh
curl -fSLo .env.example https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/.env.example
test -f .env || cp .env.example .env
```

`.env`에 현재 사용 중인 Spreadsheet ID를 넣습니다. 인증 키는 기존 config/google-service-account.json을 그대로 사용합니다.

```text
GOOGLE_SPREADSHEET_ID=현재_문서_ID
FITLOG_IMAGE_TAG=latest
```

먼저 Compose 지원 여부와 설정을 확인하고 이미지를 받습니다. 이 단계는 기존 컨테이너를 중단하지 않습니다.

```bash
sudo docker compose version
sudo docker compose --env-file .env -f compose.yml config --quiet
sudo docker compose --env-file .env -f compose.yml pull
```

Compose의 `up --wait --wait-timeout` 지원이 필요합니다. `sudo docker compose up --help`로 확인하세요.

## 2. 기존 DB 백업과 전환 (최초 한 번)

기존 컨테이너가 정상 실행 중일 때 백업합니다. 아래는 SQLite backup API를 사용하므로 WAL의 기록도 포함됩니다.

```bash
sudo docker exec ghcr.io_ruymin_fitlog-1 python -c "import sqlite3; from pathlib import Path; from datetime import datetime; p=Path('/app/data/backups'); p.mkdir(exist_ok=True); s=sqlite3.connect('/app/data/fitlog.db'); d=sqlite3.connect(str(p/('before-compose-'+datetime.now().strftime('%Y%m%dT%H%M%S')+'.db'))); s.backup(d); d.close(); s.close(); print('Backup complete')"
```

백업 성공을 확인한 후 아래 명령을 실행합니다. 전환 중 잠시 접속이 끊깁니다. 기존 컨테이너는 삭제하지 않고, 재부팅 시 함께 시작되지 않도록 자동 재시작을 해제합니다.

```bash
sudo docker update --restart=no ghcr.io_ruymin_fitlog-1
sudo docker stop ghcr.io_ruymin_fitlog-1
sudo docker compose --env-file .env -f compose.yml up -d --wait --wait-timeout 120
sudo docker compose --env-file .env -f compose.yml ps
curl -f http://localhost:51881/api/health
sudo bash /volume1/docker/fitlog/automation/update.sh
```

마지막 명령이 `Image unchanged; container left running.`이면 정상입니다. 웹에서 기록과 Google 연결 상태도 확인하세요. 실패 시 예약 실행을 등록하지 말고 `sudo docker compose --env-file .env -f compose.yml logs --tail 100 fitlog`로 원인을 확인하세요. 새 버전이 DB 스키마를 바꿨을 수 있으므로 이전 컨테이너를 무조건 다시 시작하지 마세요.

## 3. 15분마다 확인

먼저 `command -v crontab`으로 NAS에서 cron을 지원하는지 확인하세요. 지원하면 **root의 기존 예약 작업을 보존하면서** 아래 줄을 추가합니다.

```bash
sudo crontab -e
```

추가할 줄:

```cron
*/15 * * * * /bin/bash /volume1/docker/fitlog/automation/update.sh >/dev/null 2>&1
```

`sudo crontab -l`로 등록을 확인합니다. NAS의 작업 스케줄러를 사용하는 경우에도 root 권한, 15분 주기, 위 `/bin/bash .../update.sh` 명령으로 등록하면 됩니다. NAS 운영체제 업데이트 후 예약 작업이 유지되는지도 확인하세요. cron이 없으면 별도 설치부터 하지 말고 NAS에서 제공하는 예약 실행 기능을 확인하세요.

자동 업데이트를 중지하려면 해당 예약 줄만 삭제하세요. GitHub Actions는 이미지를 게시하고, NAS는 다음 예약 시각에 확인합니다. GitHub에 NAS SSH 키나 Google 인증 키를 등록할 필요가 없습니다.

## 동작과 실패 처리

- 파일 잠금으로 중복 실행을 막습니다.
- 현재 컨테이너가 healthy 상태일 때만 진행합니다.
- 다운로드 실패 또는 이미지가 같으면 기존 컨테이너를 교체하지 않습니다.
- 새 이미지가 있으면 SQLite 백업과 integrity_check를 완료하고 이전 이미지를 `fitlog-rollback:<시각>` 태그로 남깁니다.
- 컨테이너 교체 후 최대 120초 동안 healthcheck 성공을 기다립니다.
- 실패 또는 교체 중 중단 시 `.update-failed`를 남겨 다음 예약 실행을 차단합니다. 자동 DB 복원/다운그레이드는 하지 않습니다.
- 정상 복구를 확인한 뒤에만 `sudo rm /volume1/docker/fitlog/automation/.update-failed`로 차단을 해제하세요.
- 로그는 `automation/logs/update-YYYY-MM-DD.log`, 백업은 `data/backups/before-auto-update-*.db`입니다. 외부 알림 기능은 없습니다. NAS 스케줄러의 실패 알림을 지원하면 활용하세요.
- 로그·백업·이전 이미지의 자동 삭제는 하지 않습니다. 디스크 용량을 확인하고 보관 기간을 정해 수동 정리하세요.
- 백업 이후 컨테이너 교체까지 입력된 기록은 현재 DB에는 유지되지만 그 백업에는 없을 수 있습니다. 복원 전 현재 DB도 별도로 보존하세요.
- `.env`나 Compose 파일만 수정했을 때는 스크립트 대신 Compose `up -d --wait`로 직접 반영하세요. 예약 스크립트는 이미지 변경만 확인합니다.
