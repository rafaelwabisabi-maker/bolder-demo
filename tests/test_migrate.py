"""
Tests for the candidates.json -> Postgres mapping. No DB required
(psycopg is imported lazily, only under --apply).

These pin the bug class that matters: the live records use Portuguese keys
(nome, whatsapp, salario_atual, score_tecnico, ...). If the mapping drifts back
to English keys, every migrated row would silently insert NULLs. This test
fails loudly if that regresses.
"""
import json

import migrate_to_postgres as m


def test_map_candidate_row_uses_real_portuguese_keys():
    c = {
        "nome": "Ana Lima",
        "email": "ana@example.com",
        "whatsapp": "+55 11 90000-0001",
        "linkedin": "https://linkedin.com/in/example",
        "cidade": "Campinas",
        "estado": "SP",
        "cv_link": "https://drive.example.com/cv/ana",
        "salario_atual": "R$ 18.000",
        "pretensao_salarial": "R$ 22.000",
        "score_tecnico": 8,
        "score_fit": 7,
        "score_expectativas": 9,
        "score_final": 8.0,
        "rating": "A",
        "status_pipeline": "TRIAGEM",
        "observacoes": "Forte em operacoes industriais.",
        "source": "form",
        "last_updated": "2026-04-05T14:30:00Z",
    }
    row = m.map_candidate_row(c)
    assert row["email"] == "ana@example.com"
    assert row["name"] == "Ana Lima"
    assert row["score_final"] == 8.0
    assert row["rating"] == "A"
    assert row["contact"]["whatsapp"] == "+55 11 90000-0001"
    assert row["contact"]["linkedin"].endswith("example")
    assert row["salary"]["atual"] == "R$ 18.000"
    assert row["salary"]["pretensao"] == "R$ 22.000"
    assert row["grid_scores"]["tecnico"] == 8
    assert row["grid_scores"]["fit"] == 7
    assert row["cv_path"].endswith("/ana")
    assert row["last_action_at"] == "2026-04-05T14:30:00Z"


def test_map_candidate_row_missing_email_is_none():
    assert m.map_candidate_row({"nome": "No Email"})["email"] is None


def test_load_candidates_handles_bare_list(tmp_path):
    vdir = tmp_path / "VAGA-X-2026"
    vdir.mkdir()
    (vdir / "candidates.json").write_text(
        json.dumps([{"email": "a@b.com", "nome": "A"}]), encoding="utf-8"
    )
    vaga_id, cands = m.load_candidates_json(vdir)
    assert vaga_id == "VAGA-X-2026"
    assert len(cands) == 1
    assert cands[0]["nome"] == "A"


def test_load_candidates_handles_object_shape(tmp_path):
    vdir = tmp_path / "VAGA-Y-2026"
    vdir.mkdir()
    (vdir / "candidates.json").write_text(
        json.dumps({"vaga_id": "VAGA-Y-CUSTOM", "candidates": [{"email": "c@d.com"}]}),
        encoding="utf-8",
    )
    vaga_id, cands = m.load_candidates_json(vdir)
    assert vaga_id == "VAGA-Y-CUSTOM"
    assert len(cands) == 1
