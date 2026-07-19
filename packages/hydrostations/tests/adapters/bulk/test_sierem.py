import pytest

from hydrostations.adapters.bulk.sierem import SieremAdapter
from hydrostations.exceptions import AdapterNotImplementedError

STUB_ADAPTERS = {"sierem": SieremAdapter}


@pytest.mark.parametrize("source_id,adapter_cls", STUB_ADAPTERS.items())
def test_stub_adapter_raises_not_implemented(source_id, adapter_cls, register_entries):
    with pytest.raises(AdapterNotImplementedError):
        adapter_cls(register_entries[source_id]).fetch_stations()
