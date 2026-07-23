"""Benchmark: metadata read operations against a real TM1 server.

Usage:
    PYTHONPATH=. python tests/performance/benchmark_metadata.py

Required env vars: TM1_ADDRESS, TM1_USER, TM1_PASSWORD
Optional: TM1_PORT (default 8010), TM1_SSL (default true)
"""

import asyncio
import time
import tracemalloc

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

    tracemalloc.start()

    async with AsyncSessionLocal() as db:
        org, user, connection = await create_benchmark_connection(
            db, config, "Benchmark: metadata"
        )

        try:
            start = time.perf_counter()
            cubes = await tm1_integration_service.list_cubes(
                db, connection.id, org.id
            )
            list_cubes_elapsed = time.perf_counter() - start

            start = time.perf_counter()
            for cube_name in cubes:
                await tm1_integration_service.get_cube(
                    db, connection.id, org.id, cube_name
                )
            get_cube_elapsed = time.perf_counter() - start

            start = time.perf_counter()
            dimensions = await tm1_integration_service.list_dimensions(
                db, connection.id, org.id
            )
            list_dimensions_elapsed = time.perf_counter() - start

            start = time.perf_counter()
            for dimension_name in dimensions:
                await tm1_integration_service.get_dimension(
                    db, connection.id, org.id, dimension_name
                )
            get_dimension_elapsed = time.perf_counter() - start

            _, peak_memory = tracemalloc.get_traced_memory()

            print("\n=== Metadata Benchmark ===")
            print(f"Cubes:               {len(cubes)} in {list_cubes_elapsed:.3f}s")
            print(
                f"get_cube (all):      {get_cube_elapsed:.3f}s "
                f"({get_cube_elapsed / max(len(cubes), 1):.4f}s/cube)"
            )
            print(
                f"Dimensions:          {len(dimensions)} in "
                f"{list_dimensions_elapsed:.3f}s"
            )
            print(
                f"get_dimension (all): {get_dimension_elapsed:.3f}s "
                f"({get_dimension_elapsed / max(len(dimensions), 1):.4f}s/dim)"
            )
            print(f"Peak traced memory:  {peak_memory / 1024 / 1024:.2f} MB")
        finally:
            tracemalloc.stop()
            await cleanup_benchmark_org(db, org)


if __name__ == "__main__":
    asyncio.run(main())
