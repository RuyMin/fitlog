"""Google transport only: no database imports, no credential/error body logging."""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.sync_schemas import COLUMNS


class SyncError(Exception):
    def __init__(self, message: str, code: int = 422):
        self.message, self.code = message, code
        super().__init__(message)


@dataclass(frozen=True)
class SheetSnapshot:
    title: str
    tables: dict[str, list[list]]
    format: str = "standard"


class SheetReader(Protocol):
    def read(self) -> SheetSnapshot: ...


@dataclass(frozen=True)
class GoogleSettings:
    credential_file: str
    spreadsheet_id: str
    worksheets: dict[str, str]

    @classmethod
    def from_env(cls):
        return cls(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/app/config/google-service-account.json"),
                   os.getenv("GOOGLE_SPREADSHEET_ID", "").strip(),
                   {key: os.getenv("GOOGLE_WORKSHEET_" + key.upper(), key) for key in COLUMNS})

    def configured(self) -> bool:
        try:
            return bool(self.spreadsheet_id and Path(self.credential_file).is_file())
        except OSError:
            return False


class GoogleSheetsReader:
    def __init__(self, settings: GoogleSettings):
        self.settings = settings

    def read(self) -> SheetSnapshot:
        cfg = self.settings
        if not cfg.configured():
            raise SyncError("Google Spreadsheet ID와 서비스 계정 파일을 설정해 주세요.", 503)
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", cfg.spreadsheet_id):
            raise SyncError("Spreadsheet ID 형식이 올바르지 않습니다. URL 전체가 아닌 ID를 입력해 주세요.")
        if len(set(cfg.worksheets.values())) != len(COLUMNS) or any(not x.strip() for x in cfg.worksheets.values()):
            raise SyncError("Worksheet 이름은 비어 있지 않고 서로 달라야 합니다.")
        # Imports are deferred: missing/invalid Google setup never prevents app startup.
        import gspread
        from google.auth.exceptions import GoogleAuthError
        from requests.exceptions import RequestException
        client = None
        try:
            from google.oauth2.service_account import Credentials
            from google.auth.transport.requests import AuthorizedSession
            credentials = Credentials.from_service_account_file(cfg.credential_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
            client = gspread.Client(auth=credentials, session=AuthorizedSession(credentials, refresh_timeout=25, max_refresh_attempts=1))
            client.set_timeout((5, 25))
            book = client.open_by_key(cfg.spreadsheet_id)
            names = {w.title for w in book.worksheets()}
            korean = {"12주 루틴", "러닝 기록", "웨이트 기록", "인바디 기록", "대시보드", "식사 기록", "일일 운동 기록"}
            if set(cfg.worksheets.values()).issubset(names):
                mapping, sheet_format = cfg.worksheets, "standard"
            elif korean.issubset(names):
                if names != korean:
                    raise SyncError("한글 통합기록은 현재 7개 탭을 지원합니다. 추가 탭도 보존하려면 변환기 확장이 필요합니다.")
                mapping, sheet_format = {name: name for name in sorted(korean)}, "korean"
            else:
                raise SyncError("영어 표준 시트 5개 또는 기존 한글 통합기록 시트 7개가 필요합니다.")
            # Sentinel row/column lets validation reject oversized Korean snapshots.
            area = "A1:AY5001" if sheet_format == "korean" else "A:AZ"
            ranges = ["'" + name.replace("'", "''") + "'!" + area for name in mapping.values()]
            response = book.values_batch_get(ranges, params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"})
            values = response.get("valueRanges", [])
            if len(values) != len(mapping):
                raise SyncError("Worksheet 응답이 완전하지 않습니다. 다시 시도해 주세요.", 502)
            return SheetSnapshot(book.title, {key: value.get("values", []) for key, value in zip(mapping, values)}, sheet_format)
        except SyncError:
            raise
        except (gspread.SpreadsheetNotFound, PermissionError):
            raise SyncError("Spreadsheet를 찾거나 읽을 수 없습니다. ID와 서비스 계정 공유 권한을 확인해 주세요.", 502) from None
        except gspread.exceptions.APIError as exc:
            code = exc.response.status_code
            if code == 400:
                message = "Worksheet 이름과 필수 시트 5개가 있는지 확인해 주세요."
            elif code in (401, 403, 404):
                message = "Google Sheets API 활성화, Spreadsheet ID와 서비스 계정 공유 권한을 확인해 주세요."
            elif code == 429:
                message = "Google API 호출 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
            else:
                message = "Google Sheets 응답에 오류가 있습니다. 잠시 후 다시 시도해 주세요."
            raise SyncError(message, 502) from None
        except (OSError, ValueError, KeyError, GoogleAuthError):
            raise SyncError("서비스 계정 인증에 실패했습니다. JSON 키 파일과 유효기간을 확인해 주세요.", 503) from None
        except RequestException:
            raise SyncError("Google Sheets 연결이 지연되거나 실패했습니다. 잠시 후 다시 시도해 주세요.", 502) from None

        finally:
            if client is not None:
                client.http_client.session.close()
