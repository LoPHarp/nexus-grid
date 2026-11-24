import json
import sqlite3
import time


class DB:
    """Job history. Plain sqlite3, all calls come from the single event-loop thread."""

    def __init__(self, path: str):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, type TEXT, params TEXT, priority INT, state TEXT,
            total INT, done INT, created REAL, finished REAL)""")
        # jobs that were running when the previous process stopped cannot be resumed
        self.c.execute("UPDATE jobs SET state='aborted' WHERE state IN ('queued','running')")
        self.c.commit()

    def next_job_id(self) -> int:
        return (self.c.execute("SELECT COALESCE(MAX(id),0) FROM jobs").fetchone()[0]) + 1

    def save_job(self, j: dict):
        self.c.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                       (j["id"], j["type"], json.dumps(j["params"]), j["priority"], j["state"],
                        j["total"], j["done"], j["created"], j.get("finished")))
        self.c.commit()

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["params"] = json.loads(d["params"])
        return d

    def get_job(self, jid: int):
        r = self.c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return self._row(r) if r else None

    def list_jobs(self, limit: int = 100) -> list[dict]:
        return [self._row(r) for r in
                self.c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def delete_job(self, jid: int):
        self.c.execute("DELETE FROM jobs WHERE id=?", (jid,))
        self.c.commit()


def now() -> float:
    return time.time()
