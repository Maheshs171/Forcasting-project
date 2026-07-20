"""
config/connections.py
────────────────────────
Registry of named database connections, stored in connections.json next
to this file. Lets the app switch which SQL Server/database it talks to
without touching code or restarting — table/column names stay the same
across every connection (config/settings.py's table config applies to
whichever connection is currently active).

On first run, seeds the registry from the existing .env values (if
present) as a connection named "default", so nothing breaks for anyone
already using the old single-connection setup.
"""

import os
import json
import threading

_LOCK = threading.Lock()
_PATH = os.path.join(os.path.dirname(__file__), "connections.json")


def _seed_from_env() -> dict:
    from dotenv import load_dotenv
    load_dotenv()
    server = os.getenv("SQL_SERVER")
    registry = {"active": None, "connections": {}}
    if server:
        registry["connections"]["default"] = {
            "server":   server,
            "database": os.getenv("SQL_DATABASE"),
            "username": os.getenv("SQL_USERNAME"),
            "password": os.getenv("SQL_PASSWORD"),
            "port":     int(os.getenv("SQL_PORT", "3342")),
        }
        registry["active"] = "default"
    return registry


def _load() -> dict:
    if not os.path.exists(_PATH):
        registry = _seed_from_env()
        _save(registry)
        return registry
    with open(_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(registry: dict):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def list_connections() -> list[dict]:
    """Never returns passwords."""
    with _LOCK:
        registry = _load()
        active = registry.get("active")
        return [
            {
                "name": name,
                "server": c["server"],
                "database": c["database"],
                "username": c.get("username"),
                "port": c.get("port", 3342),
                "is_active": name == active,
            }
            for name, c in registry.get("connections", {}).items()
        ]


def get_active_name() -> str | None:
    with _LOCK:
        return _load().get("active")


def get_active() -> dict | None:
    """Full connection dict including password — for internal use by fetcher.py only."""
    with _LOCK:
        registry = _load()
        active = registry.get("active")
        if not active:
            return None
        return registry["connections"].get(active)


def add_connection(name: str, server: str, database: str, username: str, password: str, port: int = 3342, make_active: bool = True):
    with _LOCK:
        registry = _load()
        registry.setdefault("connections", {})[name] = {
            "server": server, "database": database,
            "username": username, "password": password, "port": port,
        }
        if make_active or not registry.get("active"):
            registry["active"] = name
        _save(registry)


def set_active(name: str):
    with _LOCK:
        registry = _load()
        if name not in registry.get("connections", {}):
            raise KeyError(f"No connection named '{name}'")
        registry["active"] = name
        _save(registry)


def delete_connection(name: str):
    with _LOCK:
        registry = _load()
        if name not in registry.get("connections", {}):
            raise KeyError(f"No connection named '{name}'")
        del registry["connections"][name]
        if registry.get("active") == name:
            registry["active"] = next(iter(registry["connections"]), None)
        _save(registry)


def test_connection(server: str, database: str, username: str, password: str, port: int = 3342) -> tuple[bool, str]:
    import pymssql
    try:
        conn = pymssql.connect(server=server, port=port, database=database, user=username, password=password, timeout=8)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return True, "Connected successfully"
    except Exception as e:
        return False, str(e)
