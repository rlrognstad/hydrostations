"""Loads and validates the YAML source register.

`load_entries()` is the only thing this module does for now -- reading
every `sources/*.yaml` file and validating it against the pydantic models
in `register.models`. Turning validated entries into adapter instances
(`build_adapters()`) is added once the adapters themselves are ported to
accept a register entry.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from hydrostations.exceptions import RegisterError
from hydrostations.register.models import SourceEntry, SourceEntryAdapter

_SOURCES_DIR = Path(__file__).parent / "sources"


@lru_cache
def load_entries(sources_dir: Path | None = None) -> tuple[SourceEntry, ...]:
    """Read and validate every `*.yaml` file in `sources_dir` (default: the
    package's own `register/sources/`)."""
    directory = sources_dir or _SOURCES_DIR
    entries = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text())
            entries.append(SourceEntryAdapter.validate_python(raw))
        except (ValidationError, yaml.YAMLError) as exc:
            raise RegisterError(f"invalid register entry {path.name}: {exc}") from exc

    ids = [e.source_id for e in entries]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise RegisterError(f"duplicate source_id(s) in register: {sorted(duplicates)}")

    return tuple(entries)
