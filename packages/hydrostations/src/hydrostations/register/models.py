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
from hydrostations.schema import COMPARTMENTS, SOURCE_CLASSES


class SourceEntryBase(BaseModel):
    source_id: str
    name: str
    operator: str
    # agency: official national/subnational hydrological or met service.
    # research: academic compilation or observatory. citizen: volunteer /
    # crowd-sourced network. Lets a downstream consumer include/exclude/
    # weight sources differently -- required, not defaulted to "agency",
    # since guessing wrong here is worse than being forced to decide.
    source_class: str
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

    @field_validator("source_class")
    @classmethod
    def _known_source_class(cls, v: str) -> str:
        if v not in SOURCE_CLASSES:
            raise ValueError(f"unknown source_class {v!r}, must be one of {SOURCE_CLASSES}")
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


class SocrataConfig(BaseModel):
    dataset_id: str  # the Socrata "4x4" resource id, e.g. "hp9r-jxuu"
    id_field: str
    name_field: str
    lat_field: str
    lon_field: str
    elevation_field: str | None = None
    first_obs_field: str | None = None
    last_obs_field: str | None = None
    # strptime pattern for first/last obs when they aren't ISO-8601
    # (IDEAM's are "DD/MM/YYYY"); None -> best-effort ISO parsing.
    date_format: str | None = None
    # A record's native station-type field, and which of its values feed
    # each compartment -- config-driven, same reasoning as GHCN's
    # element_by_compartment.
    category_field: str
    category_by_compartment: dict[str, list[str]]
    page_size: int = 1000


class SocrataEntry(SourceEntryBase):
    protocol: Literal["socrata"]
    socrata: SocrataConfig


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


class SieremConfig(BaseModel):
    # The master index KML: every per-basin/per-station-type station file
    # listed as a <NetworkLink> href. SieremGoogleBassin.kml (by drainage
    # basin) is the complete one.
    index_kml: str = "SieremGoogleBassin.kml"
    # Which filename type-suffix tokens feed each compartment -- SIEREM
    # names its station files <BASIN><TYPE>.kml (HYDRO, PLUVI, PLGRA,
    # SYNOP, CLIMA, METEO, AGRO, AGROB, CATCH). Only the unambiguous types
    # are mapped by default; SYNOP/CLIMA/METEO stations also record
    # rainfall and could be folded into P here without a code change,
    # same reasoning as GHCN's element_by_compartment.
    type_by_compartment: dict[str, list[str]] = Field(
        default_factory=lambda: {"Q": ["HYDRO"], "P": ["PLUVI", "PLGRA"]}
    )


class SieremEntry(SourceEntryBase):
    protocol: Literal["bulk_kml"]
    live: bool = False
    # Every SieremConfig field is defaulted, so the block is optional in YAML.
    sierem: SieremConfig = Field(default_factory=SieremConfig)


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


class GhcndConfig(BaseModel):
    stations_path: str = "ghcnd-stations.txt"
    inventory_path: str = "ghcnd-inventory.txt"
    # e.g. {P: [PRCP]} -- a station is included in a compartment if the
    # inventory lists any of that compartment's elements for it.
    element_by_compartment: dict[str, list[str]]


class GhcndEntry(SourceEntryBase):
    protocol: Literal["ghcnd_bulk"]
    ghcnd: GhcndConfig


class GrdcConfig(BaseModel):
    # The zip's own internal filename -- kept configurable rather than
    # hardcoded in case BfG ever renames it, same reasoning as GHCN's
    # stations_path/inventory_path.
    xlsx_member: str = "GRDC_Stations.xlsx"


class GrdcEntry(SourceEntryBase):
    protocol: Literal["grdc_ftp"]
    grdc: GrdcConfig


class IsmnConfig(BaseModel):
    # Which of the JSON's free-text native variable labels count toward
    # each compartment -- config-driven, not hardcoded, same reasoning as
    # GHCN's element_by_compartment. A station can match more than one
    # compartment and gets one record per match.
    variable_by_compartment: dict[str, list[str]]


class IsmnEntry(SourceEntryBase):
    protocol: Literal["ismn_bulk"]
    ismn: IsmnConfig


class AmerifluxEntry(SourceEntryBase):
    # No config block -- nothing protocol-specific to declare: a single
    # compartment and fixed sub-paths under `endpoint`.
    protocol: Literal["ameriflux_bulk"]


class WqpEntry(SourceEntryBase):
    # No config block -- one compartment (WQ), one Station-search endpoint,
    # no per-compartment split, same reasoning as AmerifluxEntry. Bespoke
    # rather than bulk: WQP has a real server-side bBox filter.
    protocol: Literal["wqp_station"]


class PsmslConfig(BaseModel):
    # Which of PSMSL's per-dataset station lists to read. Metric (default)
    # is PSMSL's full holdings; the RLR subset
    # ("rlr.monthly.data/filelist.txt") is the datum-continuous, QC'd set
    # recommended for sea-level trend analysis -- kept configurable, same
    # reasoning as GHCN's stations_path.
    filelist_path: str = "met.monthly.data/filelist.txt"


class PsmslEntry(SourceEntryBase):
    protocol: Literal["psmsl_filelist"]
    # Every PsmslConfig field is defaulted, so the block is optional in YAML.
    psmsl: PsmslConfig = Field(default_factory=PsmslConfig)


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
    | CocorahsEntry
    | GhcndEntry
    | GrdcEntry
    | IsmnEntry
    | AmerifluxEntry
    | WqpEntry
    | PsmslEntry
    | SocrataEntry,
    Field(discriminator="protocol"),
]
SourceEntryAdapter: TypeAdapter[SourceEntry] = TypeAdapter(SourceEntry)
