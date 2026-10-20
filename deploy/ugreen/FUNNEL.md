# Tailscale Funnel로 FitLog 공개하기

지인은 앱 설치 없이 링크만 열고, 공유기 포트는 열지 않는 구성입니다.

```text
지인 브라우저 ──HTTPS──▶ Tailscale Funnel 중계 ──(암호화 유지)──▶ NAS의 tailscale 컨테이너 ──▶ FitLog 컨테이너
                                                        └ 인증서·HTTPS 종료는 여기서만
```

- 주소: `https://fitlog.<tailnet 이름>.ts.net`
- **Funnel 중계 서버는 내용을 볼 수 없습니다.** HTTPS는 NAS 안의 tailscale 컨테이너에서만 풀립니다([Tailscale 문서](https://tailscale.com/kb/1223/funnel)).
- 공개되는 것은 `fitlog`라는 **별도 Tailscale 기기 하나**뿐입니다. NAS 자체(관리 화면, 파일, SSH)는 인터넷에 열리지 않습니다.
- FitLog 포트 51881은 NAS의 `127.0.0.1`에만 열립니다. 같은 집 Wi-Fi나 Tailscale IP로 직접 접속하는 경로는 없어지고, 본인도 위 주소를 씁니다.
- 무료(Personal) 요금제에서 사용할 수 있습니다. Funnel은 베타이며 대역폭 제한이 있습니다(수치 비공개). 기록 앱 용도로는 충분합니다.

## 1. Tailscale 관리 콘솔 설정 (최초 1회)

https://login.tailscale.com/admin 에서 진행합니다.

1. **DNS** 메뉴에서 **MagicDNS**와 **HTTPS Certificates**를 켭니다.
   - 같은 화면의 tailnet 이름(`tailXXXX.ts.net`)이 주소에 들어갑니다. 다른 이름으로 바꿀 수 있다면 **이 단계에서** 정하세요. 나중에 바꾸면 `FITLOG_PUBLIC_URL`과 Google redirect URI도 다시 바꿔야 합니다.
2. **Access controls**(정책 파일)에 아래 두 항목을 추가하고 저장합니다. 이미 있는 `tagOwners`나 `nodeAttrs`가 있으면 그 안에 항목만 추가합니다.

   ```json
   "tagOwners": {
     "tag:fitlog": ["autogroup:admin"]
   },
   "nodeAttrs": [
     { "target": ["tag:fitlog"], "attr": ["funnel"] }
   ]
   ```

   - Funnel 권한을 `tag:fitlog` 기기에만 줍니다. 기본값처럼 `autogroup:member`에 주지 마세요. 그러면 내 다른 기기도 공개할 수 있게 됩니다.
   - 정책의 `acls`(또는 `grants`)를 직접 고쳐 쓰고 있다면 내 기기에서 `tag:fitlog:443`으로 접근하는 규칙도 있어야 합니다. 기본 정책(모두 허용)이면 따로 할 일이 없습니다.
3. **Settings → Keys → Generate auth key**에서 키를 만듭니다.
   - Reusable: 끔 / Ephemeral: 끔 / Tags: `tag:fitlog`
   - 만든 키는 한 번만 표시됩니다. 다음 단계에서 바로 `.env`에 넣습니다.

## 2. NAS 파일 준비

```bash
cd /volume1/docker/fitlog/automation
mkdir -p tailscale
curl -fSLo compose.yml https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/compose.yml
curl -fSLo tailscale/serve.json https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/tailscale/serve.json
curl -fSLo .env.example https://raw.githubusercontent.com/RuyMin/fitlog/main/deploy/ugreen/.env.example
sudo mkdir -p /volume1/docker/fitlog/tailscale
```

`.env`에 다음을 추가합니다.

```text
TS_AUTHKEY=<1-3단계에서 만든 키>
TS_HOSTNAME=fitlog
FITLOG_PUBLIC_URL=https://fitlog.<tailnet 이름>.ts.net
```

`serve.json`의 `${TS_CERT_DOMAIN}`은 그대로 둡니다. tailscale 컨테이너가 실행할 때 실제 주소로 바꿉니다.

## 3. 시작과 확인

v3 첫 배포라면 이 단계는 [RELEASE-v3.md](RELEASE-v3.md) 4단계에서 함께 실행합니다.

```bash
# 이전 구성(51881을 모든 주소에 공개)에서 넘어올 때는 기존 컨테이너를 먼저 멈춥니다. 포트 충돌을 막기 위해서입니다.
sudo docker compose --env-file .env -f compose.yml stop fitlog
sudo docker compose --env-file .env -f compose.yml up -d --wait --wait-timeout 180
sudo docker compose --env-file .env -f compose.yml logs --tail 30 tailscale
sudo docker compose --env-file .env -f compose.yml exec tailscale tailscale funnel status
```

- [ ] 관리 콘솔 **Machines**에 `fitlog` 기기가 `tag:fitlog`로 보입니다. 태그가 붙은 기기는 키 만료가 기본으로 꺼져 있는데, 목록에 "Expiry disabled"로 표시되는지 확인합니다. 아니라면 기기 메뉴(…)에서 **Disable key expiry**를 눌러 주세요. 키가 만료되면 공개 주소가 끊깁니다.
- [ ] `funnel status` 출력에 `https://fitlog.<tailnet>.ts.net`과 `(Funnel on)`이 보입니다.
- [ ] 첫 실행이 성공하면 `.env`에서 `TS_AUTHKEY` 값을 지웁니다. 로그인 상태는 `/volume1/docker/fitlog/tailscale`에 저장되어 유지됩니다.
- [ ] **휴대폰에서 Wi-Fi와 Tailscale을 모두 끈 상태로** `https://fitlog.<tailnet>.ts.net/api/health`를 열어 `{"status":"ok","app":"FitLog"}`가 보이는지 확인합니다. 공개 DNS 반영에 최대 10분 정도 걸릴 수 있습니다.

## 4. Google 로그인 설정

README의 [로그인과 초대](../../README.md#로그인과-초대) 준비 단계를 따르고, 주소만 Funnel 주소로 씁니다.

- 승인된 리디렉션 URI: `https://fitlog.<tailnet>.ts.net/auth/google/callback`
- `ts.net`은 내 도메인이 아니라서 Google의 도메인 소유 확인이 불가능합니다. OAuth 동의 화면을 **"테스트"** 상태로 두고 **테스트 사용자**에 본인과 지인의 Google 이메일을 등록합니다(최대 100명).
  - 지인을 초대할 때마다 ① Google 콘솔 테스트 사용자 등록 ② `python -m app.admin invite` 링크 발급을 함께 합니다. ①이 빠지면 Google 단계에서 로그인이 막힙니다.
  - 테스트 상태에서는 로그인 중 Google이 "확인되지 않은 앱" 같은 안내를 보여 줄 수 있습니다. 지인에게 미리 알려 주세요.

## 운영

| 하고 싶은 일 | 방법 |
|---|---|
| 공개를 잠시 막기 (본인은 Tailscale로 계속 사용) | `tailscale/serve.json`의 `AllowFunnel` 값을 `false`로 바꿉니다. 컨테이너가 파일 변경을 감지해 바로 적용합니다. 확인: `... exec tailscale tailscale funnel status` |
| 완전히 멈추기 | `sudo docker compose --env-file .env -f compose.yml stop` |
| Tailscale 이미지 업데이트 | `... pull tailscale` 후 `... up -d --wait`. `update.sh`는 FitLog 이미지만 갱신합니다. tailscale 컨테이너가 다시 만들어지면 네트워크를 공유하는 FitLog도 함께 다시 시작됩니다. |
| 기기 재인증이 필요할 때 | 관리 콘솔에서 새 키를 만들어 `.env`의 `TS_AUTHKEY`에 넣고 `up -d`. 끝나면 다시 지웁니다. |

- 로그인 요청 제한(분당 20회)은 클라이언트 IP 기준인데, Funnel 뒤에서는 모든 요청이 같은 주소로 보입니다. 사용자 전체가 이 한도를 함께 씁니다. 10명 규모에서는 충분합니다.
- 공개 주소는 누구나 열 수 있습니다. 기록을 보호하는 것은 앱의 Google 로그인·초대 제도입니다. 초대 링크는 개인 메시지로만 보내고, 쓰지 않는 계정은 `python -m app.admin disable`로 정지하세요.
