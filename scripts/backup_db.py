#!/usr/bin/env python3
"""nursing-erp 数据库自动备份脚本

用法:
    python scripts/backup_db.py                           # 手动备份
    python scripts/backup_db.py --hourly                   # 每小时备份（保留 24 份）
    python scripts/backup_db.py --daily                    # 每日备份（保留 30 份）
    python scripts/backup_db.py --cleanup 7                # 清理 7 天前的备份

建议 Crontab:
    0 * * * * cd /path/to/nursing-erp && python scripts/backup_db.py --hourly
    3 3 * * * cd /path/to/nursing-erp && python scripts/backup_db.py --daily

数据库连接从环境变量读取，与 Django settings 一致:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
默认使用 Docker 容器内的连接参数。
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", Path(__file__).resolve().parent.parent / "backups"))
DB_HOST = os.environ.get("DB_HOST", "nursing-db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "nursing_erp")
DB_USER = os.environ.get("DB_USER", "nursing")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def _pg_dump(output_path: Path) -> None:
    """Run pg_dump and gzip the result."""
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD

    with open(output_path.with_suffix(".sql"), "wb") as f:
        subprocess.run(
            [
                "pg_dump",
                "-h", DB_HOST,
                "-p", DB_PORT,
                "-U", DB_USER,
                "-d", DB_NAME,
                "--no-owner",
                "--no-acl",
                "--compress=0",
            ],
            stdout=f, stderr=subprocess.PIPE, env=env, check=True,
        )

    # Compress
    with open(output_path.with_suffix(".sql"), "rb") as src:
        with gzip.open(output_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    output_path.with_suffix(".sql").unlink()
    print(f"Backup saved: {output_path} ({output_path.stat().st_size} bytes)")


def backup_hourly() -> None:
    """Hourly rolling backup — keeps last 24 hours."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    hour = datetime.now().strftime("%H")
    path = BACKUP_DIR / f"nursing_erp_hourly_{hour}.sql.gz"
    _pg_dump(path)


def backup_daily() -> None:
    """Daily rolling backup — keeps last 30 days."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    path = BACKUP_DIR / f"nursing_erp_daily_{day}.sql.gz"
    _pg_dump(path)


def backup_manual() -> None:
    """One-shot backup with timestamp."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = BACKUP_DIR / f"nursing_erp_{ts}.sql.gz"
    _pg_dump(path)


def cleanup(days: int) -> None:
    """Remove backups older than `days` days."""
    cutoff = datetime.now() - timedelta(days=days)
    for f in BACKUP_DIR.glob("*.sql.gz"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            f.unlink()
            print(f"Removed old backup: {f.name}")


def main():
    parser = argparse.ArgumentParser(description="nursing-erp database backup")
    parser.add_argument("--hourly", action="store_true")
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--cleanup", type=int, metavar="DAYS", help="Remove backups older than DAYS")
    args = parser.parse_args()

    if args.cleanup:
        cleanup(args.cleanup)
        return

    if args.hourly:
        backup_hourly()
    elif args.daily:
        backup_daily()
    else:
        backup_manual()


if __name__ == "__main__":
    main()
