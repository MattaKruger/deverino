from __future__ import annotations

from pathlib import Path

import yaml


def test_postgres_data_volume_mounts_postgres_18_parent_directory() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    postgres = compose["services"]["postgres"]
    assert postgres["image"] == "postgres:18-alpine"
    assert "pgdata:/var/lib/postgresql" in postgres["volumes"]
    assert "pgdata:/var/lib/postgresql/data" not in postgres["volumes"]


def test_compose_volume_names_are_stable() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert compose["volumes"]["pgdata"]["name"] == "deverino_pgdata"
    assert compose["volumes"]["pgdata_test"]["name"] == "deverino_pgdata_test"
    assert compose["volumes"]["vespadata"]["name"] == "deverino_vespadata"


def test_test_database_is_separate_from_dev_database() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    postgres = compose["services"]["postgres"]
    postgres_test = compose["services"]["postgres_test"]

    assert postgres_test["image"] == postgres["image"]
    assert postgres_test["environment"]["POSTGRES_DB"] == "deverino_test"
    assert postgres_test["ports"] == ["5433:5432"]
    assert "pgdata_test:/var/lib/postgresql" in postgres_test["volumes"]
    assert postgres_test["volumes"] != postgres["volumes"]
