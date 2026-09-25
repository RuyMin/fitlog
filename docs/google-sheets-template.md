# Google Sheets 입력 템플릿

하나의 Spreadsheet에 다음 **5개 탭**을 만듭니다. 첫 행은 헤더입니다. 비어 있는 탭에도 헤더를 넣습니다.
헤더 순서는 바꿔도 되지만 이름은 정확해야 하며 중복·추가 헤더는 허용하지 않습니다.
행 위치/정렬은 매칭에 영향을 주지 않습니다. 완전히 빈 행은 건너뜁니다. 시트당 데이터 최대 20,000행입니다.

## workouts

```text
external_id,workout_date,title,body_part,started_at,ended_at,memo,updated_at
```

## workout_sets

```text
external_id,workout_external_id,exercise,set_number,weight,reps,completed,rpe,rir,memo,updated_at
```

## meals

```text
external_id,eaten_at,meal_type,name,calories,protein,carbohydrates,fat,memo,image_url,updated_at
```

## body_metrics

```text
external_id,measured_at,weight,body_fat,skeletal_muscle,memo,updated_at
```

## sleep

```text
external_id,sleep_start,sleep_end,duration_minutes,sleep_type,memo,updated_at
```

## 공통 규칙

- `external_id`: 행의 영구 식별자, 각 탭에서 유일. 영문·숫자·`_ . : -`만, 최대 200자. 정렬/수정 시 바꾸지 않습니다. 행을 복제하면 새 ID가 필요합니다.
- `updated_at`: 수정할 때마다 갱신하는 **행의 버전 시각**. Google Sheets 자체 수정 시각을 자동으로 가져오지 않습니다. 같거나 오래된 버전은 모든 변경을 건너뜁니다.
- 날짜: `workout_date`는 `2026-09-14`. 시각은 `2026-09-14T20:00:00+09:00` 또는 `2026-09-14T11:00:00Z`. 시각에는 초와 시간대가 필요합니다.
- 날짜/시각/ID 컬럼은 Google Sheets의 **일반 텍스트** 형식을 사용합니다. CSV 업로드 시 숫자·날짜·수식 자동 변환을 끄고 원본 ISO 문자를 유지합니다. 로케일 날짜와 Excel 숫자 날짜는 거부됩니다.
- 필수: 모든 탭의 ID/updated_at; workouts의 날짜/title; sets의 parent/exercise/set_number/completed; meals의 eaten_at/meal_type/name; body의 measured_at 및 측정값 하나 이상; sleep의 start/end/type.
- 선택 값은 빈 셀입니다. `0`과 미기록은 구분됩니다. 단위 문자열(kg, g)은 숫자 칸에 쓰지 않습니다. 영양 수치는 모르면 비워 두며 임의 추정하지 않습니다.
- workouts: title 최대 200자. ended_at이 있으면 started_at이 필요합니다.
- sets: `workout_external_id`는 workouts ID. `exercise`는 정확한 종목명으로 재사용/자동 생성합니다. 공백만 다른 이름은 정리하지만 한글/영문 별칭은 자동 병합하지 않습니다.
- sets: `set_number`는 같은 운동 세션·종목 안에서 양의 정수로 유일. completed는 `true`/`false`. 중량/횟수 음수 불가, RPE 0–10, RIR 0–100. RIR 범위나 드롭세트는 숫자로 축약하지 말고 memo에 보존합니다.
- meals: meal_type은 `breakfast`, `lunch`, `dinner`, `snack`, `other`. image_url은 http(s) URL 또는 빈칸. 이미지 다운로드는 하지 않습니다.
- body: weight > 0, body_fat 0–100(%), skeletal_muscle >= 0(kg).
- sleep: type `main`/`nap`, 종료가 시작보다 최소 1분 이후. duration_minutes는 비우면 자동 계산; 입력하면 시작·종료의 경과시간(분 단위 내림)과 일치해야 합니다. 분할 수면 가능, 기존 수면과 겹치면 전체 취소.
- memo 최대 5,000자. 추가 정보를 잃지 않도록 memo에 라벨과 단위를 붙여 저장합니다.

## 예제와 실제 기록

`examples/*.csv`는 가상 예제입니다. 실제 시트에서 예제 행은 제거하세요.
현재 사용자의 변환 기록은 Git 제외 경로 `data/imports/legacy-20260926/*.csv`에 있습니다.
이 **5개 CSV를 각각 새 탭으로 업로드**하고 탭 이름을 파일 이름(확장자 제외)과 맞추세요.
workout_sets의 ID와 workouts의 ID를 그대로 유지해야 로컬 이관 데이터와 중복되지 않습니다.
업로드한 뒤 같은 CSV를 다시 가져와도 동일한 ID/updated_at은 건너뜁니다.
수면 CSV는 실제 기록이 없어 헤더만 있습니다.

원본 Excel은 위 정규화 스키마와 다르므로 원본 파일을 그대로 5개 탭 대신 사용할 수 없습니다.
원본 7개 시트 전체는 SQLite import_archives에 파일 바이트와 비어 있지 않은 셀 값으로 보존하며 설정 화면에서 열람/다운로드합니다.
루틴·대시보드·입력 예시를 실제 수행 기록으로 만들지 않습니다.
러닝 상세, 추가 영양소, RIR 범위, 인바디 추가 수치는 해당 기록 memo와 원본에 보존합니다.
복합 세트/중량 미상 세트는 볼륨 합계에서 제외되며 0으로 간주하지 않습니다.
원본의 어시스트 풀업 보조중량과 편측 반복수 표기는 그대로 보존합니다.

## 동기화 규칙과 한계

전체 시트 읽기 → 전체 행 검증 → SQLite writer 예약 → ID 조회 → 최신 버전만 upsert → 수면/제약 검증 → 한 번에 commit.
실패하면 종목 자동 생성까지 전부 rollback하며 최근 오류 상태만 별도 저장합니다.
시트에서 삭제한 행은 SQLite에서 삭제하지 않습니다. 앱에서 삭제한 가져온 행은 시트에 남아 있으면 다음 sync에서 다시 생깁니다.
앱의 로컬 행(source=local)은 ID가 같아도 덮어쓰지 않습니다. 가져온 행은 Google Sheets가 기준이며 더 최신 시트 버전은 앱에서 수정한 값도 덮어씁니다. 양방향 충돌 해결은 아직 없습니다.
같은 세션/종목의 세트 번호 교환이 고유 제약에 부딪히면 부분 반영 없이 취소됩니다. 충돌 없는 번호로 단계적으로 바꿉니다.
한 DB는 한 Spreadsheet에 연결됩니다. 최초 성공한 ID를 저장하고 다른 Spreadsheet ID로 변경하면 import를 거부합니다.
초기 Excel 이관은 아직 연결되지 않은 기본 소스의 ID를 준비하므로 제공한 CSV를 그 Spreadsheet에 올려 사용합니다.

Google 연결 없음/장애는 일반 기록·대시보드·통계 조회에 영향을 주지 않습니다.
설정 상태의 `configured`는 파일 존재/ID 입력 여부만 뜻하며 실제 인증은 수동 sync 때 검증합니다.
`Connected`는 마지막 동기화 성공을 뜻하고 실시간 연결 보증이 아닙니다.
