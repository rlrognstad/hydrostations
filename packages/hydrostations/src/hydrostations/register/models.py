"""Pydantic models for the source register.

Every source (agency/network) is declared as one YAML entry under
`register/sources/`. The entry's `protocol` field discriminates which
adapter class handles it and which protocol-specific config block
(`kiwis`/`wfs`/`arcgis`/`nwis`/`wise`) it must carry.

Protocol adapters (kiwis, wfs, arcgis_feature_server) are truly reusable --
a new agency on one of these protocols is a new register entry, not a new
Python class. Bespoke adapters (nwis_rdb, wise_discodata) still get a
register entry for their metadata (license, coverage, compartments), but
their fetch logic stays hand-written Python; the register just carries the
config values that logic reads instead of module constants.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from hydrostations.adapters.base import BBox
from hydrostations.schema import COMPARTMENTS


class SourceEntryBase(BaseModel):
    source_id: str
    name: str
    operator: str
    endpoint: str
    compartments: list[str]
    license: str
    redistribution_ok: bool = True
    coverage: list[tuple[float, float, float, float]]
    live: bool = True
    # NWIS's own bbox-size API limit is what originally motivated this --
    # opt-in per source, not blanket, since a coverage bbox is a coarse
    # hand-declared approximation and skipping on it can suppress genuinely
    # valid results near the edge for sources that don't need the guard.
    skip_out_of_coverage: bool = False
    notes: str | None = None

    @field_validator("compartments")
    @classmethod
    def _known_compartments(cls, v: list[str]) -> list[str]:
        bad = set(v) - set(COMPARTMENTS)
        if bad:
            raise ValueError(f"unknown compartment codes: {sorted(bad)}")
        return v

    def coverage_bboxes(self) -> tuple[BBox, ...]:
        return tuple(BBox(*c) for c in self.coverage)


class KiwisConfig(BaseModel):
    datasource: str = "0"
    id_field: str
    name_field: str
    lat_field: str
    lon_field: str
    return_fields: list[str]
    parameter_type_by_compartment: dict[str, str]


class KiwisEntry(SourceEntryBase):
    protocol: Literal["kiwis"]
    kiwis: KiwisConfig


class WfsCollectionConfig(BaseModel):
    type_name: str
    id_field: str = "id"
    name_field: str = "name"
    start_field: str | None = None
    end_field: str | None = None


class WfsConfig(BaseModel):
    version: str = "2.0.0"
    page_size: int = 1000
    # Workaround knob, not a spec requirement: some GeoServer deployments
    # (verified on GGMN's) throw a server-side NullPointerException when
    # startIndex is combined with a bbox filter but no explicit sort.
    sort_by: str | None = None
    collections: dict[str, WfsCollectionConfig]


class WfsEntry(SourceEntryBase):
    protocol: Literal["wfs"]
    wfs: WfsConfig


class ArcGisConfig(BaseModel):
    page_size: int = 1000
    id_field: str
    name_field: str
    out_fields: list[str]
    where_by_compartment: dict[str, str]
    # Optional: a field whose value represents the "native variable" for a
    # record (e.g. HidroWeb's TipoEstacao). Not every ArcGIS Feature Service
    # has an equivalent single field, so this stays config-driven rather
    # than assumed.
    variable_field: str | None = None


class ArcGisEntry(SourceEntryBase):
    protocol: Literal["arcgis_feature_server"]
    arcgis: ArcGisConfig


class OgcFeaturesCollectionConfig(BaseModel):
    collection: str
    id_field: str
    name_field: str


class OgcFeaturesConfig(BaseModel):
    page_size: int = 500
    collections: dict[str, OgcFeaturesCollectionConfig]


class OgcFeaturesEntry(SourceEntryBase):
    protocol: Literal["ogc_features"]
    ogc_features: OgcFeaturesConfig


class NwisConfig(BaseModel):
    site_type_by_compartment: dict[str, str]
    param_code_by_compartment: dict[str, str]


class NwisEntry(SourceEntryBase):
    protocol: Literal["nwis_rdb"]
    nwis: NwisConfig


class HubeauCompartmentConfig(BaseModel):
    path: str
    id_field: str
    name_field: str
    lon_field: str
    lat_field: str
    first_obs_field: str | None = None
    last_obs_field: str | None = None


class HubeauConfig(BaseModel):
    page_size: int = 1000
    compartments: dict[str, HubeauCompartmentConfig]


class HubeauEntry(SourceEntryBase):
    protocol: Literal["hubeau"]
    hubeau: HubeauConfig


class WiseConfig(BaseModel):
    table: str
    page_size: int = 5000
    zone_types_by_compartment: dict[str, list[str]]


class WiseEntry(SourceEntryBase):
    protocol: Literal["wise_discodata"]
    wise: WiseConfig


class SieremEntry(SourceEntryBase):
    protocol: Literal["bulk_kml"]
    live: bool = False


class NrfaConfig(BaseModel):
    id_field: str = "id"
    name_field: str = "name"
    lon_field: str = "longitude"
    lat_field: str = "latitude"
    fields: list[str]


class NrfaEntry(SourceEntryBase):
    protocol: Literal["nrfa_ws"]
    nrfa: NrfaConfig


class SnotelConfig(BaseModel):
    network_code_by_compartment: dict[str, str]


class SnotelEntry(SourceEntryBase):
    protocol: Literal["snotel_awdb"]
    snotel: SnotelConfig


class CocorahsConfig(BaseModel):
    # No "all states" mode exists (confirmed live: it crashes the server)
    # and no bbox filter either -- the full inventory is one request per
    # jurisdiction, so the jurisdiction list itself is real, tunable config.
    states: list[str]


class CocorahsEntry(SourceEntryBase):
    protocol: Literal["cocorahs_export"]
    cocorahs: CocorahsConfig


SourceEntry = Annotated[
    KiwisEntry
    | WfsEntry
    | ArcGisEntry
    | OgcFeaturesEntry
    | NwisEntry
    | WiseEntry
    | HubeauEntry
    | SieremEntry
    | NrfaEntry
    | SnotelEntry
    | CocorahsEntry,
    Field(discriminator="protocol"),
]
SourceEntryAdapter: TypeAdapter[SourceEntry] = TypeAdapter(SourceEntry)
