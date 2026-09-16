"""One-time startup wrapper for removing verified migration sidecars."""
import os

_data_dir = os.environ.get("MEDPARK_DATA_DIR", "/app/user_data")
_db_path = os.environ.get("DATABASE_PATH") or os.path.join(_data_dir, "runtime", "medpark_global_maps.db")
for _suffix in (".restore-upload-wal", ".restore-upload-shm"):
    try:
        os.remove(f"{_db_path}{_suffix}")
    except FileNotFoundError:
        pass

from app import app
