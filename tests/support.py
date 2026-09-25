"""One disposable SQLite location shared by discovery; never touch real data."""
import atexit
import os
import tempfile

TEMP = tempfile.TemporaryDirectory(prefix="fitlog-test-")
os.environ["FITLOG_DATA_DIR"] = TEMP.name
atexit.register(TEMP.cleanup)
