import time

import pytest

from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.extractor import extract_metadata
from src.tm1.service import tm1_integration_service

_KNOWN_OBJECT_TYPES = {"cube", "dimension", "hierarchy", "process", "chore"}


@pytest.mark.asyncio
async def test_extract_metadata_completes_within_generous_ceiling(
    db_session, live_connection
):
    org, user, connection = live_connection

    start = time.perf_counter()
    summary = await extract_metadata(db_session, connection.id, org.id)
    elapsed = time.perf_counter() - start

    print(
        f"\nExtraction: {summary.objects_created} objects, "
        f"{summary.relationships_created} relationships in {elapsed:.2f}s"
    )

    # Soft ceiling, not a precise benchmark — see tests/performance/benchmark_graph.py
    # for that. This just catches "extraction never returns" on a huge model.
    assert elapsed < 120, (
        f"Metadata extraction took {elapsed:.1f}s — investigate before relying "
        "on on-demand extraction for large models."
    )


@pytest.mark.asyncio
async def test_dependency_traversal_is_internally_consistent(
    db_session, live_connection
):
    org, user, connection = live_connection

    await extract_metadata(db_session, connection.id, org.id)

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)

    if not cubes:
        pytest.skip("No cubes in this model to validate the dependency graph against.")

    cube_name = cubes[0]

    relationships = await dependency_analyzer.get_object_relationships(
        db_session, connection.id, org.id, "cube", cube_name
    )
    assert relationships["object_type"] == "cube"
    assert relationships["name"] == cube_name

    dependencies = await dependency_analyzer.find_dependencies(
        db_session, connection.id, org.id, "cube", cube_name
    )
    for entry in dependencies:
        assert entry["object_type"] in _KNOWN_OBJECT_TYPES
        assert entry["depth"] >= 1

    unused = await dependency_analyzer.find_unused_objects(
        db_session, connection.id, org.id
    )
    for entry in unused:
        assert entry["object_type"] in _KNOWN_OBJECT_TYPES

    print(
        f"\n'{cube_name}' has {len(dependencies)} transitive dependencies; "
        f"{len(unused)} objects in the model are unused."
    )
