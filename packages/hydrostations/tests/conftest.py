import pytest
import respx

from hydrostations.register import load_entries


@pytest.fixture
def mocked_api():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture(scope="session")
def register_entries():
    """Real, validated production register entries keyed by source_id.

    Constructing adapters from these (rather than hand-built fixture
    entries) doubles as an implicit regression test that the shipped YAML
    itself stays valid.
    """
    return {e.source_id: e for e in load_entries()}
