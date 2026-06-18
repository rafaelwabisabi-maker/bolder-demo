"""
migrate_to_postgres.py — One-shot migration from per-vaga candidates.json files
to the Postgres schema in postgres_schema.sql.

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/db
    # dry-run against the bundled fixture (no DB needed):
    python3 migrate_to_postgres.py --vaga-dir tests/fixtures --dry-run
    # live load against the real per-vaga folders:
    python3 migrate_to_postgres.py --vaga-dir ../animarh-ats/VAGAS_ATIVAS --apply

Design notes:
- Dry-run by default; --apply for live execution.
- psycopg is imported lazily (only when --apply), so the field-mapping logic
  is importable and unit-testable without a database driver installed.
- The real per-vaga records use Portuguese keys (nome, whatsapp, salario_atual,
  score_tecnico, ...). `map_candidate_row` is the single source of truth for the
  key mapping and is covered by tests/test_migrate.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable


def iter_vaga_dirs(root: Path) -> Iterable[Path]:
    """Each subfolder named VAGA-* is a vaga project."""
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.startswith("VAGA-"):
            yield child


def load_candidates_json(vaga_dir: Path) -> tuple[str, list[dict]]:
    """Returns (vaga_id, candidates_list). Handles both shapes seen in production:
    a bare JSON list (V2 per-vaga files) or a {vaga_id, candidates} object."""
    cj = vaga_dir / "candidates.json"
    if not cj.exists():
        return vaga_dir.name, []
    try:
        data = json.loads(cj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  ⚠️  {vaga_dir.name}: malformed candidates.json: {e}", file=sys.stderr)
        return vaga_dir.name, []
    if isinstance(data, list):
        return vaga_dir.name, data
    return data.get("vaga_id", vaga_dir.name), data.get("candidates", [])


def map_candidate_row(c: dict) -> dict:
    """Map a real per-vaga candidate record (Portuguese keys) to schema columns.
    Pure function, no DB, so it is unit-testable. This is where the live data
    keys (nome, whatsapp, salario_atual, score_tecnico, ...) meet the schema."""
    return {
        "email": c.get("email"),
        "name": c.get("nome"),
        "score_final": c.get("score_final"),
        "rating": c.get("rating"),
        "status_pipeline": c.get("status_pipeline"),
        "grid_scores": {
            "tecnico": c.get("score_tecnico"),
            "fit": c.get("score_fit"),
            "expectativas": c.get("score_expectativas"),
        },
        "contact": {
            "whatsapp": c.get("whatsapp"),
            "linkedin": c.get("linkedin"),
            "cidade": c.get("cidade"),
            "estado": c.get("estado"),
        },
        "salary": {
            "atual": c.get("salario_atual"),
            "pretensao": c.get("pretensao_salarial"),
        },
        "cv_path": c.get("cv_link"),
        "observations": c.get("observacoes"),
        "last_action": c.get("source"),
        "last_action_at": c.get("last_updated") or c.get("added_at"),
    }


def upsert_vaga(cur, vaga_id: str) -> None:
    cur.execute(
        """INSERT INTO vagas (vaga_id, client_name, role_title, status_pipeline)
           VALUES (%s, %s, %s, 'SOURCING')
           ON CONFLICT (vaga_id) DO NOTHING""",
        (vaga_id, vaga_id.split("-")[1] if "-" in vaga_id else "UNKNOWN", vaga_id),
    )


def upsert_candidate(cur, vaga_id: str, c: dict, source_path: Path, row: int) -> bool:
    """Anchored insert: each row references its source file + row index.
    Returns True if inserted, False if skipped (no email = no primary key)."""
    r = map_candidate_row(c)
    if not r["email"]:
        print(f"  ⚠️  {source_path}:{row} skipped — no email (primary key)", file=sys.stderr)
        return False
    cur.execute(
        """INSERT INTO candidates (
               vaga_id, email, name, score_final, rating, status_pipeline,
               grid_scores, contact, salary, cv_path, observations,
               last_action, last_action_at
           ) VALUES (
               %s, %s, %s, %s, %s, %s,
               %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb,
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
            r["email"],
            r["name"],
            r["score_final"],
            r["rating"],
            r["status_pipeline"],
            json.dumps(r["grid_scores"]),
            json.dumps(r["contact"]),
            json.dumps(r["salary"]),
            r["cv_path"],
            json.dumps(r["observations"]),
            r["last_action"],
            r["last_action_at"],
        ),
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vaga-dir", required=True, help="Path to a folder containing VAGA-* subfolders")
    ap.add_argument("--dry-run", action="store_true", help="Preview only (default if --apply not set)")
    ap.add_argument("--apply", action="store_true", help="Actually execute inserts")
    args = ap.parse_args()

    if not args.apply:
        print("DRY-RUN mode — no inserts will be executed. Pass --apply to commit.")

    root = Path(args.vaga_dir).resolve()
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        return 2

    conn = None
    if args.apply:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("DATABASE_URL not set", file=sys.stderr)
            return 2
        try:
            import psycopg
        except ImportError:
            print("Install psycopg first:  pip install 'psycopg[binary]'", file=sys.stderr)
            return 1
        conn = psycopg.connect(db_url, autocommit=False)

    vaga_count = candidate_count = skipped = 0
    try:
        for vaga_dir in iter_vaga_dirs(root):
            vaga_id, candidates = load_candidates_json(vaga_dir)
            if not candidates:
                continue
            vaga_count += 1
            print(f"  📂 {vaga_id}: {len(candidates)} candidates")

            if args.apply:
                with conn.cursor() as cur:
                    upsert_vaga(cur, vaga_id)
                    for i, c in enumerate(candidates):
                        try:
                            if upsert_candidate(cur, vaga_id, c, vaga_dir / "candidates.json", i):
                                candidate_count += 1
                            else:
                                skipped += 1
                        except Exception as e:  # one bad row must not kill the run
                            print(f"  ❌ {vaga_id}#{i}: {e}", file=sys.stderr)
                            skipped += 1
                conn.commit()
            else:
                # dry-run: still exercise the mapping so it fails loudly on bad data
                for i, c in enumerate(candidates):
                    if map_candidate_row(c)["email"]:
                        candidate_count += 1
                    else:
                        skipped += 1

        print(f"\n✅ {'Migrated' if args.apply else 'Would migrate'}: "
              f"{vaga_count} vagas, {candidate_count} candidates, {skipped} skipped")
        return 0
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
