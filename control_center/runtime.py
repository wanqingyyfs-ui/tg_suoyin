from __future__ import annotations

import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "TG 索引控制中心"
CONTROL_CONFIG_NAME = "control_center.json"
DEFAULT_ENV = {
    "SITE_URL": "https://tg-suoyin.vercel.app",
    "TELEGRAM_BOT_TOKEN": "",
    "BOT_REQUEST_TIMEOUT": "30",
    "BOT_POLLING_TIMEOUT": "25",
    "BOT_WEBHOOK_HOST": "127.0.0.1",
    "BOT_WEBHOOK_PORT": "8899",
    "BOT_WEBHOOK_SECRET": "",
    "ADMIN_HOST": "127.0.0.1",
    "ADMIN_PORT": "8787",
    "ADMIN_TOKEN": "",
    "FRONTEND_HOST": "127.0.0.1",
    "FRONTEND_PORT": "4321",
}
DEFAULT_CONTROL_CONFIG = {
    "auto_start_frontend": False,
    "auto_start_admin": False,
    "auto_start_bot": False,
    "auto_restart": True,
    "minimize_to_tray": True,
    "backup_before_delete": True,
    "refresh_frontend_after_change": True,
}
SENSITIVE_KEYS = {"TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "BOT_WEBHOOK_SECRET", "ADMIN_TOKEN"}


def _looks_like_root(path: Path) -> bool:
    return (path / "bot.py").is_file() and (path / "scripts").is_dir() and (path / "data").is_dir()


def discover_root() -> Path:
    override = os.environ.get("TG_SUOYIN_ROOT", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    candidates.extend([Path.cwd(), Path(__file__).resolve().parent.parent, Path(sys.argv[0]).resolve().parent])
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if _looks_like_root(resolved):
            return resolved
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


ROOT_DIR = discover_root()
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "rectg.db"
ENV_PATH = ROOT_DIR / ".env"
CONTROL_CONFIG_PATH = DATA_DIR / CONTROL_CONFIG_NAME
LOG_DIR = ROOT_DIR / "logs"
WEB_PUBLIC_DIR = ROOT_DIR / "web" / "public"
WEB_DIST_DIR = ROOT_DIR / "web" / "dist"


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def configure_child_stdio(channel: str) -> None:
    """Give windowed/frozen child modes a durable stdout/stderr target."""
    ensure_runtime_dirs()
    safe = "".join(ch for ch in channel if ch.isalnum() or ch in "-_") or "service"
    target = LOG_DIR / f"raw-{safe}.log"
    try:
        if target.exists() and target.stat().st_size > 20 * 1024 * 1024:
            rotated = target.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            target.replace(rotated)
    except OSError:
        pass
    stream = target.open("a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    print(f"\n--- {datetime.now().isoformat(timespec='seconds')} child={safe} pid={os.getpid()} ---", flush=True)


def parse_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    values = dict(DEFAULT_ENV)
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def apply_env(values: dict[str, str] | None = None) -> dict[str, str]:
    loaded = values or parse_env_file()
    for key, value in loaded.items():
        os.environ[key] = str(value)
    return loaded


def _quote_env(value: str) -> str:
    value = str(value)
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or any(ch in value for ch in '#"\''):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_env_file(updates: dict[str, str], path: Path = ENV_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pending = {str(k): str(v) for k, v in updates.items()}
    output: list[str] = []
    seen: set[str] = set()
    for raw in existing_lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                output.append(f"{key}={_quote_env(pending[key])}")
                seen.add(key)
                continue
        output.append(raw)
    missing = [key for key in pending if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# 由 TG 索引控制中心维护")
        output.extend(f"{key}={_quote_env(pending[key])}" for key in missing)
    text = "\n".join(output).rstrip() + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp.replace(path)
    apply_env(parse_env_file(path))


def load_control_config() -> dict[str, Any]:
    values = dict(DEFAULT_CONTROL_CONFIG)
    if CONTROL_CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONTROL_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                values.update({k: loaded[k] for k in DEFAULT_CONTROL_CONFIG if k in loaded})
        except (OSError, ValueError, TypeError):
            pass
    return values


def save_control_config(values: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    data = dict(DEFAULT_CONTROL_CONFIG)
    data.update({k: values[k] for k in DEFAULT_CONTROL_CONFIG if k in values})
    tmp = CONTROL_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONTROL_CONFIG_PATH)


def connect_db(*, readonly: bool = False) -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在：{DB_PATH}")
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    if not readonly:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_database_schema() -> None:
    scripts = ROOT_DIR / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from message_indexer import init_message_index_schema  # type: ignore

    conn = connect_db()
    try:
        init_message_index_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                url TEXT NOT NULL,
                image_url TEXT,
                sort_order INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def backup_database(reason: str = "manual") -> Path:
    ensure_runtime_dirs()
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在：{DB_PATH}")
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:24] or "backup"
    target = backup_dir / f"rectg-{datetime.now():%Y%m%d-%H%M%S}-{safe_reason}.db"
    source = sqlite3.connect(str(DB_PATH), timeout=10)
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def redact(text: str, env: dict[str, str] | None = None) -> str:
    result = str(text)
    values = env or parse_env_file()
    for key in SENSITIVE_KEYS:
        secret = values.get(key, "").strip()
        if secret and len(secret) >= 6:
            result = result.replace(secret, "***REDACTED***")
    return result


def selected_placeholders(values: Iterable[Any]) -> tuple[str, list[Any]]:
    params = list(values)
    if not params:
        raise ValueError("没有选择任何记录")
    return ",".join("?" for _ in params), params


def refresh_frontend_data() -> list[Path]:
    apply_env()
    export_script = ROOT_DIR / "scripts" / "export_frontend_data.py"
    if not export_script.exists():
        raise FileNotFoundError(f"缺少导出脚本：{export_script}")
    old_argv = sys.argv[:]
    old_cwd = Path.cwd()
    try:
        os.chdir(ROOT_DIR)
        sys.argv = [str(export_script)]
        runpy.run_path(str(export_script), run_name="__main__")
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    WEB_DIST_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in ("data.json", "sitemap.xml", "robots.txt"):
        source = WEB_PUBLIC_DIR / name
        if source.exists():
            target = WEB_DIST_DIR / name
            shutil.copy2(source, target)
            copied.append(target)
    return copied


def service_program_and_args(service: str) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--service", service]
    return sys.executable, ["-m", "control_center", "--service", service]


def utility_program_and_args(utility: str) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--utility", utility]
    return sys.executable, ["-m", "control_center", "--utility", utility]


def run_service(service: str) -> int:
    ensure_runtime_dirs()
    apply_env()
    os.chdir(ROOT_DIR)
    scripts = ROOT_DIR / "scripts"
    for path in (ROOT_DIR, scripts):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    if service == "frontend":
        from .frontend_server import serve

        serve()
        return 0
    if service == "admin":
        import admin_dashboard  # type: ignore

        old_argv = sys.argv[:]
        try:
            sys.argv = ["admin_dashboard.py"]
            admin_dashboard.main()
        finally:
            sys.argv = old_argv
        return 0
    if service == "bot":
        import bot  # type: ignore

        bot.run_polling(drop_webhook=True, summary_interval=None)
        return 0
    raise ValueError(f"未知服务：{service}")


def run_utility(name: str) -> int:
    if name == "export":
        copied = refresh_frontend_data()
        print("✅ 前端数据已刷新：" + ", ".join(str(path.relative_to(ROOT_DIR)) for path in copied), flush=True)
        return 0
    if name == "db-backup":
        print(f"✅ 数据库备份完成：{backup_database('manual')}", flush=True)
        return 0
    if name == "frontend-build":
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise FileNotFoundError("未找到 npm。请先安装 Node.js 22 或使用 GitHub Actions 生成的便携包。")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [npm, "run", "frontend:prepare"],
            cwd=ROOT_DIR,
            env=os.environ.copy(),
            stdout=sys.stdout,
            stderr=sys.stderr,
            creationflags=flags,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"前端构建失败，退出码 {result.returncode}")
        print("✅ 前端构建完成。", flush=True)
        return 0
    raise ValueError(f"未知工具：{name}")
