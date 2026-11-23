"""Atomic writes with optimistic concurrency for a local, resumable workbench."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Conflict(ValueError):
    pass


class ProjectStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    revision INTEGER NOT NULL, document TEXT NOT NULL
                )
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def add(self, project):
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO projects VALUES (?, ?, 1, ?)", (
                project["id"], project["title"], json.dumps(project, ensure_ascii=False)))

    def list_projects(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT id, title FROM projects ORDER BY rowid DESC").fetchall()

    def load(self, project_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT document, revision FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return json.loads(row[0]), row[1]

    def save(self, project, expected):
        with closing(self.connect()) as db, db:
            result = db.execute("""
                UPDATE projects SET document = ?, revision = revision + 1
                WHERE id = ? AND revision = ?
            """, (json.dumps(project, ensure_ascii=False), project["id"], expected))
            if result.rowcount != 1:
                raise Conflict("项目已在另一个页面更新，请刷新后重新核对。")
