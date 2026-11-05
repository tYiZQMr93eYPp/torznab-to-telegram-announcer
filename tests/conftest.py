from pathlib import Path

import pytest

EXAMPLE_FEED = Path(__file__).parent.parent / "examples" / "torznab.example.xml"


@pytest.fixture(scope="session")
def example_xml() -> bytes:
    return EXAMPLE_FEED.read_bytes()
