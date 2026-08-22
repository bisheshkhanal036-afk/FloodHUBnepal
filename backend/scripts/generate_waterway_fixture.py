"""One-off generator for tests/data/fixtures/osm/nepal-test-extract-
waterway.osm.pbf: a tiny, valid .osm.pbf containing a single
waterway=river way, inside TEST_AOI_BBOX_4326 (85.3050, 27.7020,
85.3110, 27.7080) — the same bbox tests/data/fixtures/osm/nepal-test-
extract.osm.pbf (buildings+roads) already uses.

A separate file rather than adding the river to that existing fixture,
so this phase's new test fixture can never affect Phase 2's own
buildings/roads test assertions (get_osm_features is not touched by
this phase).

Not run automatically anywhere — this is source for the binary fixture
committed alongside it, kept here purely so the fixture is reproducible
without re-deriving the osmium API calls from scratch. Run with:
    python scripts/generate_waterway_fixture.py
"""

from __future__ import annotations

from pathlib import Path

import osmium

OUT_PATH = Path(__file__).parent.parent / "tests" / "data" / "fixtures" / "osm" / "nepal-test-extract-waterway.osm.pbf"


def main() -> None:
    if OUT_PATH.exists():
        OUT_PATH.unlink()

    writer = osmium.SimpleWriter(str(OUT_PATH))
    writer.add_node(osmium.osm.mutable.Node(id=1, location=(85.3060, 27.7025), tags={}))
    writer.add_node(osmium.osm.mutable.Node(id=2, location=(85.3060, 27.7075), tags={}))
    writer.add_way(
        osmium.osm.mutable.Way(id=1, nodes=[1, 2], tags={"waterway": "river", "name": "Test River"})
    )
    writer.close()
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
