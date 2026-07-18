import pytest

from hydrostations.adapters.sierem import SieremAdapter
from hydrostations.exceptions import AdapterNotImplementedError

STUB_ADAPTERS = [SieremAdapter]


@pytest.mark.parametrize("adapter_cls", STUB_ADAPTERS)
def test_stub_adapter_raises_not_implemented(adapter_cls):
    with pytest.raises(AdapterNotImplementedError):
        adapter_cls().fetch_stations()
