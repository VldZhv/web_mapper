from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "web_mapper.db"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3"}
MAX_IMAGE_SIZE = 15 * 1024 * 1024
MAX_AUDIO_SIZE = 30 * 1024 * 1024

app = Flask(__name__)
app.json.ensure_ascii = False



def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                floor_plan_path TEXT,
                scale REAL,
                calibration_points TEXT,
                grid_step REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                points TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                room_id INTEGER,
                name TEXT NOT NULL,
                color TEXT NOT NULL,
                points TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(room_id) REFERENCES rooms(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                autostart INTEGER DEFAULT 0,
                looped INTEGER DEFAULT 0,
                volume INTEGER DEFAULT 100,
                file_path TEXT NOT NULL,
                original_file_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )



def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"



def validate_points(points: list[dict[str, Any]]) -> bool:
    if not points or len(points) < 3:
        return False
    for p in points:
        if not isinstance(p, dict):
            return False
        if "x" not in p or "y" not in p:
            return False
        if not isinstance(p["x"], (int, float)) or not isinstance(p["y"], (int, float)):
            return False
    return True



def ensure_project_dir(project_id: int) -> Path:
    p = UPLOADS_DIR / str(project_id)
    p.mkdir(parents=True, exist_ok=True)
    return p



def serialize_project(project_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            return None
        rooms = conn.execute("SELECT * FROM rooms WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
        zones = conn.execute("SELECT * FROM zones WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
        tracks = conn.execute("SELECT * FROM tracks WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()

    return {
        "id": project["id"],
        "name": project["name"],
        "description": project["description"],
        "floorPlanPath": project["floor_plan_path"],
        "scale": project["scale"],
        "gridStep": project["grid_step"],
        "calibrationPoints": json.loads(project["calibration_points"]) if project["calibration_points"] else None,
        "createdAt": project["created_at"],
        "updatedAt": project["updated_at"],
        "rooms": [
            {
                "id": row["id"],
                "name": row["name"],
                "points": json.loads(row["points"]),
                "createdAt": row["created_at"],
            }
            for row in rooms
        ],
        "zones": [
            {
                "id": row["id"],
                "roomId": row["room_id"],
                "name": row["name"],
                "color": row["color"],
                "points": json.loads(row["points"]),
                "createdAt": row["created_at"],
            }
            for row in zones
        ],
        "tracks": [
            {
                "id": row["id"],
                "name": row["name"],
                "x": row["x"],
                "y": row["y"],
                "autostart": bool(row["autostart"]),
                "looped": bool(row["looped"]),
                "volume": row["volume"],
                "filePath": row["file_path"],
                "originalFileName": row["original_file_name"],
                "createdAt": row["created_at"],
            }
            for row in tracks
        ],
    }


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/projects")
def list_projects():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, description, created_at, updated_at FROM projects ORDER BY id DESC").fetchall()
    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ])


@app.post("/api/projects")
def create_project():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Название проекта обязательно"}), 400
    description = str(payload.get("description", "")).strip()
    ts = now_iso()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO projects(name, description, created_at, updated_at) VALUES(?,?,?,?)",
            (name, description, ts, ts),
        )
        project_id = cur.lastrowid
    ensure_project_dir(project_id)
    return jsonify(serialize_project(project_id)), 201


@app.get("/api/projects/<int:project_id>")
def get_project(project_id: int):
    project = serialize_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    return jsonify(project)


@app.post("/api/projects/<int:project_id>/plan")
def upload_plan(project_id: int):
    project = serialize_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    if "file" not in request.files:
        return jsonify({"error": "Файл не передан"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Имя файла пустое"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Поддерживаются только PNG/JPG/BMP"}), 400

    data = file.read()
    if len(data) > MAX_IMAGE_SIZE:
        return jsonify({"error": "Файл слишком большой (макс. 15 МБ)"}), 400

    project_dir = ensure_project_dir(project_id)
    plan_name = f"plan_{uuid.uuid4().hex}{ext}"
    plan_path = project_dir / plan_name
    plan_path.write_bytes(data)

    rel_path = f"/api/files/{project_id}/{plan_name}"
    with get_db() as conn:
        conn.execute(
            "UPDATE projects SET floor_plan_path = ?, updated_at = ? WHERE id = ?",
            (rel_path, now_iso(), project_id),
        )
    return jsonify({"floorPlanPath": rel_path})


@app.post("/api/projects/<int:project_id>/calibration")
def set_calibration(project_id: int):
    payload = request.get_json(silent=True) or {}
    points = payload.get("points")
    distance_m = payload.get("distanceMeters")
    if not isinstance(points, list) or len(points) != 2:
        return jsonify({"error": "Нужно передать две точки"}), 400
    if not isinstance(distance_m, (int, float)) or distance_m <= 0:
        return jsonify({"error": "Некорректная дистанция"}), 400

    dx = points[1]["x"] - points[0]["x"]
    dy = points[1]["y"] - points[0]["y"]
    px_dist = (dx ** 2 + dy ** 2) ** 0.5
    if px_dist <= 0:
        return jsonify({"error": "Точки калибровки совпадают"}), 400

    scale = px_dist / distance_m
    grid_step = payload.get("gridStep")
    if not isinstance(grid_step, (int, float)) or grid_step <= 0:
        grid_step = distance_m

    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not exists:
            return jsonify({"error": "Проект не найден"}), 404
        conn.execute(
            "UPDATE projects SET scale = ?, calibration_points = ?, grid_step = ?, updated_at = ? WHERE id = ?",
            (scale, json.dumps(points, ensure_ascii=False), grid_step, now_iso(), project_id),
        )
    return jsonify({"scale": scale, "gridStep": grid_step})


@app.post("/api/projects/<int:project_id>/rooms")
def create_room(project_id: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    points = payload.get("points")
    if not name:
        return jsonify({"error": "Название зала обязательно"}), 400
    if not isinstance(points, list) or not validate_points(points):
        return jsonify({"error": "Некорректный контур зала"}), 400

    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not exists:
            return jsonify({"error": "Проект не найден"}), 404
        cur = conn.execute(
            "INSERT INTO rooms(project_id, name, points, created_at) VALUES(?,?,?,?)",
            (project_id, name, json.dumps(points), now_iso()),
        )
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/projects/<int:project_id>/zones")
def create_zone(project_id: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    color = str(payload.get("color", "#4caf50")).strip() or "#4caf50"
    points = payload.get("points")
    room_id = payload.get("roomId")
    if not name:
        return jsonify({"error": "Название зоны обязательно"}), 400
    if not isinstance(points, list) or not validate_points(points):
        return jsonify({"error": "Некорректный контур зоны"}), 400

    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not exists:
            return jsonify({"error": "Проект не найден"}), 404
        if room_id:
            room_exists = conn.execute("SELECT 1 FROM rooms WHERE id = ? AND project_id = ?", (room_id, project_id)).fetchone()
            if not room_exists:
                return jsonify({"error": "Связанный зал не найден"}), 404
        cur = conn.execute(
            "INSERT INTO zones(project_id, room_id, name, color, points, created_at) VALUES(?,?,?,?,?,?)",
            (project_id, room_id, name, color, json.dumps(points), now_iso()),
        )
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/projects/<int:project_id>/tracks")
def create_track(project_id: int):
    name = str(request.form.get("name", "")).strip()
    x = request.form.get("x", type=float)
    y = request.form.get("y", type=float)
    autostart = 1 if request.form.get("autostart") == "true" else 0
    looped = 1 if request.form.get("looped") == "true" else 0
    volume = request.form.get("volume", type=int)
    file = request.files.get("file")

    if not name:
        return jsonify({"error": "Название трека обязательно"}), 400
    if x is None or y is None:
        return jsonify({"error": "Координаты трека обязательны"}), 400
    if volume is None or volume < 0 or volume > 100:
        return jsonify({"error": "Громкость должна быть от 0 до 100"}), 400
    if not file or not file.filename:
        return jsonify({"error": "MP3 файл обязателен"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        return jsonify({"error": "Поддерживается только MP3"}), 400
    data = file.read()
    if len(data) > MAX_AUDIO_SIZE:
        return jsonify({"error": "Файл слишком большой (макс. 30 МБ)"}), 400

    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not exists:
            return jsonify({"error": "Проект не найден"}), 404

    filename = secure_filename(Path(file.filename).stem) or "track"
    stored_name = f"{filename}_{uuid.uuid4().hex}.mp3"
    path = ensure_project_dir(project_id) / stored_name
    path.write_bytes(data)
    rel_path = f"/api/files/{project_id}/{stored_name}"

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO tracks(project_id, name, x, y, autostart, looped, volume, file_path, original_file_name, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (project_id, name, x, y, autostart, looped, volume, rel_path, file.filename, now_iso()),
        )
    return jsonify({"id": cur.lastrowid, "filePath": rel_path}), 201


@app.get("/api/files/<int:project_id>/<path:filename>")
def get_file(project_id: int, filename: str):
    full = ensure_project_dir(project_id) / filename
    if not full.exists() or not full.is_file():
        return jsonify({"error": "Файл не найден"}), 404
    return send_file(full)


@app.get("/api/projects/<int:project_id>/export")
def export_project(project_id: int):
    project = serialize_project(project_id)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404

    export_dir = DATA_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    json_path = export_dir / f"project_{project_id}.json"
    json_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    return send_file(json_path, as_attachment=True, download_name=f"project_{project_id}.json")


@app.delete("/api/projects/<int:project_id>")
def delete_project(project_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return jsonify({"error": "Проект не найден"}), 404
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    shutil.rmtree(UPLOADS_DIR / str(project_id), ignore_errors=True)
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
