"""One disposable SQLite location shared by discovery; never touch real data."""
import atexit
import os
import secrets
import tempfile

TEMP = tempfile.TemporaryDirectory(prefix="fitlog-test-")
os.environ["FITLOG_DATA_DIR"] = TEMP.name
atexit.register(TEMP.cleanup)


def create_user(email: str = "owner@example.com", role: str = "admin"):
    from app.database import SessionLocal
    from app.models import User
    with SessionLocal() as session:
        user = User(email=email, role=role, google_sub="sub-" + secrets.token_hex(8))
        session.add(user)
        session.commit()
        return user


def act_as(user) -> None:
    """Stand-in for the login session until the auth flow exists."""
    from app.api.deps import current_user
    from app.main import app
    app.dependency_overrides[current_user] = lambda: user


def reset_database() -> None:
    """Empty every table and drop any signed-in override."""
    from app.database import Base, engine, initialize_database
    from app.main import app
    app.dependency_overrides.clear()
    initialize_database()  # idempotent; lets a test module run on its own
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


def fresh_owner(email: str = "owner@example.com", role: str = "admin"):
    """Empty every table, then sign in as a single new user."""
    reset_database()
    user = create_user(email, role)
    act_as(user)
    return user
