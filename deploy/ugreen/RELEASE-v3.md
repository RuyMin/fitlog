# v3 수동 배포 체크리스트: 로그인과 사용자별 기록

DB 스키마 v2 → v3, 그리고 Google 로그인·초대가 처음 들어가는 릴리스(`feat/multi-user-auth` 병합 후 첫 이미지)에 한 번만 사용합니다. 이후 업데이트는 다시 예약 자동 업데이트로 받습니다.

**왜 수동인가.** `update.sh`는 이미지만 교체하고 NAS에 있는 `compose.yml`·`.env`는 바꾸지 않습니다. 이전 compose 파일로 새 이미지를 받으면 `FITLOG_OWNER_EMAIL`이 컨테이너에 전달되지 않습니다. 그러면 migration이 시작을 거부하고(DB는 그대로), 컨테이너는 unhealthy가 되며, 자동 업데이트도 `.update-failed`로 멈춥니다. 데이터는 안전하지만 서비스가 내려갑니다. 그래서 **병합 전에** 자동 업데이트를 멈추고 아래 순서로 진행합니다.

진행하면서 아래 값을 채워 두세요. 비밀번호·키 값은 이 문서에 적지 마세요.

| 항목 | 값 |
|---|---|
| 공개 주소 (`FITLOG_PUBLIC_URL`) | `https://` |
| 본인 Google 이메일 (`FITLOG_OWNER_EMAIL`) | |
| OAuth 클라이언트 ID | |
| 배포 전 이미지 ID | |
| 수동 백업 파일 | |

## 0. 병합 전 준비 (기존 서비스는 그대로)

- [ ] **자동 업데이트 일시 중지.** `sudo crontab -e`에서 `update.sh` 줄 앞에 `#`을 붙이고 `sudo crontab -l`로 확인합니다. NAS 작업 스케줄러를 쓰면 해당 작업을 비활성화합니다.
- [ ] **HTTPS 주소 준비.** 도메인과 reverse proxy(`https://<도메인>` → NAS `51881`)를 연결하고, 브라우저에서 인증서 경고 없이 열리는지 확인합니다. Google은 IP 주소나 HTTPS가 아닌 redirect 주소를 허용하지 않습니다.
- [ ] **Google OAuth 클라이언트.** README의 [로그인과 초대](../../README.md#로그인과-초대) 준비 1~3단계를 따릅니다. 승인된 리디렉션 URI는 `https://<도메인>/auth/google/callback`과 **정확히** 같아야 합니다(끝 슬래시 없음).
  - OAuth 동의 화면이 "테스트" 상태이면 Google 콘솔에 등록한 테스트 사용자만 로그인할 수 있습니다. 지인 계정을 각각 추가하거나, 범위가 `openid email profile`뿐일 때 "프로덕션"으로 게시합니다. 게시할 때 콘솔에 나오는 확인 요구사항을 따르세요.
- [ ] **51881 포트 노출 점검.** 새 버전부터 `http://NAS_IP:51881`로는 로그인할 수 없습니다(Secure 쿠키, Origin 검사). 가능하면 방화벽에서 51881을 reverse proxy만 접근하도록 제한하세요.

## 1. 병합과 이미지 게시

- [ ] PR을 main에 병합하고 GitHub Actions(테스트 → 이미지 게시)가 성공했는지 확인합니다: https://github.com/RuyMin/fitlog/actions
- [ ] NAS 예약 작업이 아직 꺼져 있는지 다시 확인합니다(`sudo crontab -l`).

## 2. NAS 설정 파일 (기존 컨테이너는 계속 실행)

```bash
cd /volume1/docker/fitlog/automation
cp compose.yml compose.yml.v2-backup
cp .env .env.v2-backup
curl -fSLo compose.yml https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/compose.yml
curl -fSLo .env.example https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/.env.example
```

`.env`에 다음 세 줄을 추가합니다(`.env.example` 참고).

```text
FITLOG_PUBLIC_URL=https://<도메인>
FITLOG_OWNER_EMAIL=<본인 Google 이메일>
GOOGLE_OAUTH_CLIENT_ID=<클라이언트 ID>
```

OAuth 클라이언트 보안 비밀번호는 `.env`가 아니라 config 폴더의 파일 한 줄로 둡니다. 컨테이너 사용자(10001)만 읽을 수 있게 합니다.

```bash
sudo touch /volume1/docker/fitlog/config/google-oauth-client-secret
sudo chown 10001:10001 /volume1/docker/fitlog/config/google-oauth-client-secret
sudo chmod 600 /volume1/docker/fitlog/config/google-oauth-client-secret
sudo vi /volume1/docker/fitlog/config/google-oauth-client-secret
```

설정이 컨테이너까지 전달되는지 확인합니다. 출력에 세 값과 `GOOGLE_OAUTH_CLIENT_SECRET_FILE`이 보여야 합니다.

```bash
sudo docker compose --env-file .env -f compose.yml config --quiet
sudo docker compose --env-file .env -f compose.yml config | grep -E 'FITLOG_PUBLIC_URL|FITLOG_OWNER_EMAIL|GOOGLE_OAUTH'
```

## 3. 백업과 현재 행 수 기록

```bash
sudo docker compose --env-file .env -f compose.yml exec -T fitlog python -c "
import sqlite3, datetime; from pathlib import Path
p = Path('/app/data/backups'); p.mkdir(exist_ok=True)
t = p / ('before-v3-manual-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + '.db')
s = sqlite3.connect('file:/app/data/fitlog.db?mode=ro', uri=True); d = sqlite3.connect(t); s.backup(d)
print(t, d.execute('PRAGMA integrity_check').fetchone()[0], 'version', d.execute('PRAGMA user_version').fetchone()[0])
for n in ['exercises','workouts','workout_sets','meals','body_metrics','sleep_records','import_archives']: print(n, d.execute(f'select count(*) from {n}').fetchone()[0])
d.close(); s.close()"
```

- [ ] 출력이 `ok`와 `version 2`인지 확인하고 파일 이름과 행 수를 적어 둡니다. 가능하면 이 파일을 NAS 밖에도 복사합니다.
- [ ] 되돌리기에 쓸 현재 이미지를 남겨 둡니다.

```bash
old=$(sudo docker inspect --format '{{.Image}}' "$(sudo docker compose --env-file .env -f compose.yml ps -q fitlog)")
echo "$old"
sudo docker image tag "$old" fitlog-rollback:v2
```

## 4. 배포

```bash
sudo docker compose --env-file .env -f compose.yml pull
sudo docker compose --env-file .env -f compose.yml up -d --wait --wait-timeout 180
sudo docker compose --env-file .env -f compose.yml logs --tail 50 fitlog
curl -f http://localhost:51881/api/health
```

시작에 실패하면 로그의 마지막 오류를 확인합니다. migration은 한 트랜잭션이라 실패하면 DB가 v2 그대로 남습니다.

| 로그 메시지 | 원인과 조치 |
|---|---|
| `FITLOG_OWNER_EMAIL is required` | compose.yml을 새로 받지 않았거나 `.env`에 값이 없습니다. 2단계를 다시 확인합니다. |
| `FITLOG_PUBLIC_URL must be ...` | `https://도메인` 형식이어야 하며 경로·끝 문자열이 없어야 합니다. |
| `Existing rows violate foreign keys` | 기존 DB에 참조가 끊긴 행이 있습니다. DB는 바뀌지 않았습니다. 되돌린 뒤 해당 행을 확인해야 합니다. |

migration 결과를 확인합니다. 3단계에서 적은 행 수와 같아야 하고, 모든 행이 사용자 1명(관리자)에게 속해야 합니다.

```bash
sudo docker compose --env-file .env -f compose.yml exec -T fitlog python -c "
import sqlite3; c = sqlite3.connect('file:/app/data/fitlog.db?mode=ro', uri=True)
print('version', c.execute('PRAGMA user_version').fetchone()[0])
print(c.execute('select id, email, role, google_sub is not null from users').fetchall())
for n in ['exercises','workouts','workout_sets','meals','body_metrics','sleep_records','import_archives']: print(n, c.execute(f'select count(*), count(distinct user_id) from {n}').fetchone())
print('fk', c.execute('PRAGMA foreign_key_check').fetchall())"
```

- [ ] `version 3`, 사용자 1명(`admin`, 아직 미연결 `0`), 행 수 동일, `fk []`.
- [ ] `data/backups/before-v3-*.db`(앱이 자동으로 만든 백업)도 생겼는지 확인합니다.

## 5. 동작 확인

- [ ] `https://<도메인>/`을 열면 `/login`으로 이동합니다.
- [ ] 본인 Google 계정으로 로그인하면 기존 기록이 그대로 보입니다. 설정에서 권한이 "관리자"이고 Google Sheets 카드가 보이며 "지금 동기화"가 동작합니다.
- [ ] `sudo docker compose --env-file .env -f compose.yml exec fitlog python -m app.admin users`에서 본인 계정이 `linked`로 바뀌었습니다.
- [ ] 시크릿 창에서 `https://<도메인>/api/meals`는 401입니다.
- [ ] `curl -sI https://<도메인>/ | grep -i -E 'content-security-policy|x-frame-options'`로 보안 헤더가 붙는지 확인합니다(proxy가 지우지 않는지).
- [ ] 이미 설치한 PWA가 예전 화면을 보이면 앱을 완전히 닫았다가 다시 엽니다.

## 6. 지인 초대

```bash
sudo docker compose --env-file .env -f compose.yml exec fitlog python -m app.admin invite --note "이름"
```

- [ ] 링크를 개인 메시지로만 보냅니다. 1회용이며 7일 후 만료됩니다.
- [ ] 첫 지인이 가입한 뒤 그 계정에서 기록이 비어 있고(본인 기록이 보이지 않음), 설정 권한이 "멤버"이며 Google Sheets 카드가 없는지 함께 확인합니다.
- [ ] 로그인 요청 제한(분당 20회)은 클라이언트 IP 기준입니다. reverse proxy 뒤에서는 모든 사용자가 proxy IP 하나로 보이므로 이 한도를 함께 씁니다. 10명 규모에서는 충분합니다.

## 7. 자동 업데이트 재개

- [ ] `sudo crontab -e`에서 붙였던 `#`을 지웁니다.
- [ ] `sudo bash /volume1/docker/fitlog/automation/update.sh` 실행 결과가 `Image unchanged; container left running.`이고 `.update-failed`가 없습니다.

## 되돌리기

**migration이 실패해 v3가 시작하지 않은 경우**(DB는 v2 그대로):

```bash
cd /volume1/docker/fitlog/automation
cp compose.yml.v2-backup compose.yml
cp .env.v2-backup .env
sudo docker image tag fitlog-rollback:v2 ghcr.io/ruymin/fitlog:v2-local
sed -i 's/^FITLOG_IMAGE_TAG=.*/FITLOG_IMAGE_TAG=v2-local/' .env
sudo docker compose --env-file .env -f compose.yml up -d --pull never --wait --wait-timeout 120
```

자동 업데이트는 원인을 해결하고 이 체크리스트를 다시 진행할 때까지 꺼 둡니다. 다시 진행할 때 `.env`의 `FITLOG_IMAGE_TAG`를 `latest`로 되돌리세요.

**v3로 전환된 뒤 되돌려야 하는 경우:** 이전 버전 앱은 v3 DB를 열지 않습니다("Database schema is newer than this application"). 백업 복원이 필요합니다. 전환 이후 입력한 기록과 지인 계정은 사라지므로 먼저 현재 DB를 별도로 보존하세요.

```bash
sudo docker compose --env-file .env -f compose.yml stop fitlog
cd /volume1/docker/fitlog/data
keep="v3-keep-$(date +%Y%m%dT%H%M%S)"
for f in fitlog.db fitlog.db-wal fitlog.db-shm; do [ -f "$f" ] && sudo cp -p "$f" "$keep-$f"; done
sudo cp backups/<3단계의 before-v3-manual 파일> fitlog.db
sudo rm -f fitlog.db-wal fitlog.db-shm
```

그다음 위의 "migration이 실패한 경우" 명령으로 v2 이미지와 설정을 되돌립니다.
