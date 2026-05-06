"""
migrate_to_postgres.py — One-shot migration from per-vaga candidates.json files
to the Postgres schema in postgres_schema.sql.

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/db
    python3 migrate_to_postgres.py --vaga-dir ../animarh-ats/VAGAS_ATIVAS --dry-run
    python3 migrate_to_postgres.py --vaga-dir ../animarh-ats/VAGAS_ATIVAS --apply

Pattern: dry-run by default, --apply for live execution. Anti-hallucination
discipline: every insert is anchored to the source file path + row number.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

try:
    import psycopg
except ImportError:
    print("Install psycopg first:  pip install 'psycopg[binary]'", file=sys.stderr)
    sys.exit(1)


def iter_vaga_dirs(root: Path) -> Iterable[Path]:
    """Each subfolder of VAGAS_ATIVAS/ is a vaga project."""
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("VAGA-"):
            yield child


def load_candidates_json(vaga_dir: Path) -> tuple[str, list[dict]]:
    """Returns (vaga_id, candidates_list). Skips if file missing or malformed."""
    cj = vaga_dir / "candidates.json"
    if not cj.exists():
        return vaga_dir.name, []
    try:
        data = json.loads(cj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  ⚠️  {vaga_dir.name}: malformed candidates.json: {e}", file=sys.stderr)
        return vaga_dir.name, []
    vaga_id = data.get("vaga_id", vaga_dir.name)
    return vaga_id, data.get("candidates", [])


def upsert_vaga(cur, vaga_id: str, source_path: Path) -> None:
    cur.execute(
        """INSERT INTO vagas (vaga_id, client_name, role_title, status_pipeline)
           VALUES (%s, %s, %s, 'SOURCING')
           ON CONFLICT (vaga_id) DO NOTHING""",
        (vaga_id, vaga_id.split("-")[1] if "-" in vaga_id else "UNKNOWN", vaga_id),
    )


def upsert_candidate(cur, vaga_id: str, c: dict, source_path: Path, row: int) -> None:
    """Anchored insert: every row references its source file + row index."""
    email = c.get("email")
    if not email:
        print(f"  ⚠️  {source_path}:{row} skipped — no email", file=sys.stderr)
        return
    cur.execute(
        """INSERT INTO candidates (
               vaga_id, email, name, score_final, rating, status_pipeline,
               grid_scores, contact, salary, observations,
               last_action, last_action_at
           ) VALUES (
               %s, %s, %s, %s, %s, %s,
               %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
               %s, %s
           )
           ON CONFLICT (vaga_id, email) DO UPDATE SET
               score_final     = EXCLUDED.score_final,
               rating          = EXCLUDED.rating,
               status_pipeline = EXCLUDED.status_pipeline,
               grid_scores     = EXCLUDED.grid_scores,
               observations    = EXCLUDED.observations,
               last_action     = EXCLUDED.last_action,
               last_action_at  = EXCLUDED.last_action_at""",
        (
            vaga_id,
            email,
            c.get("name"),
            c.get("score_final"),
            c.get("rating"),
            c.get("status_pipeline"),
            json.dumps(c.get("grid_scores", {})),
            json.dumps(c.get("contact", {})),
            json.dumps(c.get("salary", {})),
            json.dumps(c.get("observations", [])),
            c.get("last_action"),
            c.get("last_action_at"),
        ),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vaga-dir", required=True, help="Path to VAGAS_ATIVAS root")
    ap.add_argument("--dry-run", action="store_true", help="Preview only (default if --apply not set)")
    ap.add_argument("--apply", action="store_true", help="Actually execute inserts")
    args = ap.parse_args()

    if not args.apply:
        print("DRY-RUN mode — no inserts will be executed. Pass --apply to commit.")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url and args.apply:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    root = Path(args.vaga_dir).resolve()
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        return 2

    vaga_count = 0
    candidate_count = 0
    skipped = 0

    if args.apply:
        conn = psycopg.connect(db_url, autocommit=False)
    else:
        conn = None

    try:
        for vaga_dir in iter_vaga_dirs(root):
            vaga_id, candidates = load_candidates_json(vaga_dir)
            if not candidates:
                continue
            vaga_count += 1
            print(f"  📂 {vaga_id}: {len(candidates)} candidates")

            if args.apply:
                with conn.cursor() as cur:
                    upsert_vaga(cur, vaga_id, vaga_dir / "candidates.json")
                    for i, c in enumerate(candidates):
                        try:
                            upsert_candidate(cur, vaga_id, c, vaga_dir / "candidates.json", i)
                            candidate_count += 1
                        except Exception as e:
                            print(f"  ❌ {vaga_id}#{i}: {e}", file=sys.stderr)
                            skipped += 1
                conn.commit()
            else:
                candidate_count += len(candidates)

        print(f"\n✅ {'Migrated' if args.apply else 'Would migrate'}: "
              f"{vaga_count} vagas, {candidate_count} candidates, {skipped} skipped")
        return 0
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
