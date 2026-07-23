"""Benchmark: metadata graph extraction and traversal against a real TM1
server.

Usage:
    PYTHONPATH=. python tests/performance/benchmark_graph.py

Required env vars: TM1_ADDRESS, TM1_USER, TM1_PASSWORD
Optional: TM1_PORT (default 8010), TM1_SSL (default true)
"""

import asyncio
import time

from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.extractor import extract_metadata
from src.tm1.service import tm1_integration_service
from tests.performance._shared import (
    AsyncSessionLocal,
    cleanup_benchmark_org,
    create_benchmark_connection,
    ensure_credentials_key,
    tm1_config_from_env,
)


async def main() -> None:
    config = tm1_config_from_env()
    ensure_credentials_key()

    async with AsyncSessionLocal() as db:
        org, user, connection = await create_benchmark_connection(
            db, config, "Benchmark: graph"
        )

        try:
            start = time.perf_counter()
            summary = await extract_metadata(db, connection.id, org.id)
            extract_elapsed = time.perf_counter() - start

            print("\n=== Graph Extraction Benchmark ===")
            print(f"Objects created:       {summary.objects_created}")
            print(f"Relationships created: {summary.relationships_created}")
            print(f"Extraction time:       {extract_elapsed:.3f}s")

            cubes = await tm1_integration_service.list_cubes(
                db, connection.id, org.id
            )

            if not cubes:
                print("\nNo cubes in this model — skipping traversal timing.")
                return

            cube_name = cubes[0]

            start = time.perf_counter()
            dependents = await dependency_analyzer.find_dependents(
                db, connection.id, org.id, "cube", cube_name
            )
            find_dependents_elapsed = time.perf_counter() - start

            start = time.perf_counter()
            dependencies = await dependency_analyzer.find_dependencies(
                db, connection.id, org.id, "cube", cube_name
            )
            find_dependencies_elapsed = time.perf_counter() - start

            print(f"\nSample object:         cube '{cube_name}'")
            print(
                f"find_dependents:       {len(dependents)} results in "
                f"{find_dependents_elapsed:.3f}s"
            )
            print(
                f"find_dependencies:     {len(dependencies)} results in "
                f"{find_dependencies_elapsed:.3f}s"
            )
        finally:
            await cleanup_benchmark_org(db, org)


if __name__ == "__main__":
    asyncio.run(main())
