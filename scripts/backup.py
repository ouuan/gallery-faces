"""Run only with web and worker stopped; archive the entire persistent volume."""

import argparse
import sqlite3
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["backup", "restore"])
parser.add_argument("archive", type=Path)
parser.add_argument("--data", type=Path, required=True)
args = parser.parse_args()
if args.action == "backup":
    with sqlite3.connect(args.data / "gallery.sqlite3") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Database integrity check failed")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with tarfile.open(args.archive, "w:gz") as archive:
        archive.add(args.data, arcname="data")
else:
    if args.data.exists() and any(args.data.iterdir()):
        raise SystemExit("Restore destination must be empty")
    args.data.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.archive, "r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (
                path.parts[0] != "data"
                or ".." in path.parts
                or member.issym()
                or member.islnk()
            ):
                raise SystemExit("Unsafe archive")
            member.name = str(Path(*path.parts[1:]))
            if member.name != ".":
                archive.extract(member, args.data, filter="data")
    with sqlite3.connect(args.data / "gallery.sqlite3") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Restored database failed integrity check")
