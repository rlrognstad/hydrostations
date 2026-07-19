import pytest

from hydrostations.exceptions import RegisterError
from hydrostations.register.loader import load_entries

_VALID_YAML = """\
source_id: fixture_a
name: Fixture A
operator: Test Operator
endpoint: https://example.com
protocol: bulk_kml
license: Public domain
compartments: [Q]
coverage:
  - [0.0, 0.0, 1.0, 1.0]
"""


def test_load_entries_reads_real_production_register():
    # Regression test: the shipped YAML under register/sources/ must stay
    # valid. No sources_dir override -- exercises the real default.
    entries = load_entries()
    ids = {e.source_id for e in entries}
    assert ids == {
        "nwis",
        "wise",
        "bom",
        "ggmn",
        "hidroweb",
        "sierem",
        "eccc",
        "hubeau",
        "nrfa",
    }


def test_load_entries_valid_fixture(tmp_path):
    (tmp_path / "fixture_a.yaml").write_text(_VALID_YAML)

    entries = load_entries(tmp_path)

    assert len(entries) == 1
    assert entries[0].source_id == "fixture_a"


def test_load_entries_rejects_duplicate_source_id(tmp_path):
    (tmp_path / "a.yaml").write_text(_VALID_YAML)
    (tmp_path / "b.yaml").write_text(_VALID_YAML)  # same source_id, different file

    with pytest.raises(RegisterError, match="duplicate source_id"):
        load_entries(tmp_path)


def test_load_entries_wraps_invalid_yaml(tmp_path):
    (tmp_path / "broken.yaml").write_text("not: valid: yaml: [unterminated")

    with pytest.raises(RegisterError, match="invalid register entry"):
        load_entries(tmp_path)


def test_load_entries_wraps_schema_validation_error(tmp_path):
    bad = _VALID_YAML.replace("compartments: [Q]", "compartments: [NOTREAL]")
    (tmp_path / "bad.yaml").write_text(bad)

    with pytest.raises(RegisterError, match="invalid register entry"):
        load_entries(tmp_path)
