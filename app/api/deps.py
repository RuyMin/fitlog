"""Request identity shared by every private router.

Until the login flow lands (phase 6 step 3), no request is authenticated:
private APIs answer 401, and tests override `current_user`.
"""
from typing import Annotated

from fastapi import Depends, HTTPException

from app.models import User


def current_user() -> User:
    raise HTTPException(401, "로그인이 필요합니다.")


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]
