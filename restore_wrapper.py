import hashlib
import hmac
import os
import sqlite3

from flask import g, jsonify, request

from app import (
    app,
    DB_PATH,
    DATABASE_WRITE_LOCK,
    PACKAGED_DB_CRITICAL_COUNTS,
    ensure_db_dir,
    sqlite_table_counts,
)


@app.post("/_internal/database-restore-chunk")
def database_restore_chunk():
    expected_token = os.environ.get("DATABASE_RESTORE_TOKEN", "")
    supplied_token = request.headers.get("X-Database-Restore-Token", "")
    if not expected_token or not supplied_token or not hmac.compare_digest(expected_token, supplied_token):
        return jsonify(error="not found"), 404
    try:
        offset = int(request.headers.get("X-Restore-Offset", "-1"))
        total_size = int(request.headers.get("X-Restore-Total", "-1"))
    except (TypeError, ValueError):
        return jsonify(error="invalid restore metadata"), 400
    if offset < 0 or total_size <= 0 or total_size > 64 * 1024 * 1024:
        return jsonify(error="invalid restore size"), 400
    chunk = request.get_data(cache=False)
    if not chunk or len(chunk) > 1024 * 1024:
        return jsonify(error="invalid restore chunk"), 400
    ensure_db_dir()
    upload_path = f"{DB_PATH}.restore-upload"
    if offset == 0:
        with open(upload_path, "wb") as upload_file:
            upload_file.write(chunk)
            upload_file.flush()
            os.fsync(upload_file.fileno())
    else:
        if not os.path.exists(upload_path):
            return jsonify(error="restore offset mismatch"), 409
        existing_size = os.path.getsize(upload_path)
        if existing_size == offset:
            with open(upload_path, "ab") as upload_file:
                upload_file.write(chunk)
                upload_file.flush()
                os.fsync(upload_file.fileno())
        elif existing_size == offset + len(chunk):
            with open(upload_path, "rb") as upload_file:
                upload_file.seek(offset)
                existing_chunk = upload_file.read(len(chunk))
            if not hmac.compare_digest(existing_chunk, chunk):
                return jsonify(error="restore duplicate chunk mismatch"), 409
        else:
            return jsonify(error="restore offset mismatch", received=existing_size), 409
    current_size = os.path.getsize(upload_path)
    if current_size < total_size:
        return jsonify(status="uploading", received=current_size, total=total_size)
    if current_size != total_size:
        os.unlink(upload_path)
        return jsonify(error="restore size mismatch"), 422
    expected_sha256 = request.headers.get("X-Restore-Sha256", "")
    digest = hashlib.sha256()
    with open(upload_path, "rb") as restored_file:
        for block in iter(lambda: restored_file.read(1024 * 1024), b""):
            digest.update(block)
    if not expected_sha256 or not hmac.compare_digest(digest.hexdigest(), expected_sha256):
        os.unlink(upload_path)
        return jsonify(error="restore checksum mismatch"), 422
    candidate = sqlite3.connect(f"file:{upload_path}?mode=ro", uri=True, timeout=30)
    try:
        counts = sqlite_table_counts(candidate)
        integrity = candidate.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = candidate.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        candidate.close()
    if integrity != "ok" or foreign_key_errors:
        os.unlink(upload_path)
        return jsonify(error="restore integrity check failed"), 422
    if not all(counts.get(table) == count for table, count in PACKAGED_DB_CRITICAL_COUNTS.items()):
        os.unlink(upload_path)
        return jsonify(error="restore row-count verification failed"), 422
    with DATABASE_WRITE_LOCK:
        current = g.pop("db", None)
        if current is not None:
            current.close()
        os.chmod(upload_path, 0o664)
        os.replace(upload_path, DB_PATH)
    return jsonify(
        status="restored",
        tables=len(counts),
        critical_counts={table: counts.get(table) for table in PACKAGED_DB_CRITICAL_COUNTS},
    )
