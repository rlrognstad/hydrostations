"""Loads and validates the YAML source register, and builds adapter instances.

`load_entries()` reads every `sources/*.yaml` file and validates it against
the pydantic models in `register.models`. `build_adapters()` turns those
entries into ready-to-use `SourceAdapter` instances, keyed by `source_id` --
this is what `core._default_registry()` calls.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from hydrostations.adapters.base import SourceAdapter
from hydrostations.adapters.bespoke.hubeau import HubeauAdapter
from hydrostations.adapters.bespoke.nwis import NwisAdapter
from hydrostations.adapters.bespoke.wise import WiseAdapter
from hydrostations.adapters.bulk.cocorahs import CocorahsAdapter
from hydrostations.adapters.bulk.ghcnd import GhcndAdapter
from hydrostations.adapters.bulk.nrfa import NrfaAdapter
from hydrostations.adapters.bulk.sierem import SieremAdapter
from hydrostations.adapters.bulk.snotel import SnotelAdapter
from hydrostations.adapters.protocols.arcgis import ArcGisFeatureServerAdapter
from hydrostations.adapters.protocols.kiwis import KiWisAdapter
from hydrostations.adapters.protocols.ogc_features import OgcFeaturesAdapter
from hydrostations.adapters.protocols.wfs import WfsAdapter
from hydrostations.exceptions import RegisterError
from hydrostations.register.models import SourceEntry, SourceEntryAdapter

_SOURCES_DIR = Path(__file__).parent / "sources"

# Keyed by protocol, not source_id -- multiple sources on the same protocol
# (e.g. a second KiWIS agency) share one class. Updated as adapters move
# into adapters/protocols|bespoke|bulk/ during the generalization steps.
_ADAPTER_CLASSES: dict[str, type[SourceAdapter]] = {
    "kiwis": KiWisAdapter,
    "wfs": WfsAdapter,
    "arcgis_feature_server": ArcGisFeatureServerAdapter,
    "ogc_features": OgcFeaturesAdapter,
    "nwis_rdb": NwisAdapter,
    "wise_discodata": WiseAdapter,
    "hubeau": HubeauAdapter,
    "bulk_kml": SieremAdapter,
    "nrfa_ws": NrfaAdapter,
    "snotel_awdb": SnotelAdapter,
    "cocorahs_export": CocorahsAdapter,
    "ghcnd_bulk": GhcndAdapter,
}


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


def build_adapters(sources_dir: Path | None = None) -> dict[str, SourceAdapter]:
    """Fresh adapter instances for every registered source, keyed by source_id.

    Not cached (unlike `load_entries()`) -- matches the pre-register
    `_default_registry()`'s behavior of returning new instances per call.
    """
    return {e.source_id: _ADAPTER_CLASSES[e.protocol](e) for e in load_entries(sources_dir)}
