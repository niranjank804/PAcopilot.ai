"""Benchmark: one tool-enabled AI chat call against a real TM1 server and
the real Anthropic provider.

Usage:
    PYTHONPATH=. python tests/performance/benchmark_ai.py

Required env vars: TM1_ADDRESS, TM1_USER, TM1_PASSWORD, ANTHROPIC_API_KEY
Optional: TM1_PORT (default 8010), TM1_SSL (default true)
"""

import asyncio
import time

from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from tests.performance._shared import (
    AsyncSessionLocal,
    cleanup_benchmark_org,
    create_benchmark_connection,
    ensure_credentials_key,
    require_env,
    tm1_config_from_env,
)


async def main() -> None:
    config = tm1_config_from_env()
    require_env("ANTHROPIC_API_KEY")

    if not settings.ANTHROPIC_API_KEY:
        raise SystemExit(
            "ANTHROPIC_API_KEY is set in the environment but not visible to "
            "the app's settings — check it's set before the app was imported."
        )

    ensure_credentials_key()

    async with AsyncSessionLocal() as db:
        org, user, connection = await create_benchmark_connection(
            db, config, "Benchmark: AI"
        )

        try:
            start = time.perf_counter()
            result = await ai_orchestrator.chat(
                db,
                organization_id=org.id,
                user_id=user.id,
                message=(
                    f"Using TM1 connection {connection.id}, list the cubes "
                    "available in this model."
                ),
                agent="developer",
            )
            elapsed = time.perf_counter() - start

            print("\n=== AI Tool-Call Benchmark ===")
            print(f"Latency:             {elapsed:.3f}s")
            print(f"Model:               {result.model}")
            print(
                f"Tokens:              {result.usage.input_tokens} in / "
                f"{result.usage.output_tokens} out"
            )
            print(f"Estimated cost:      ${result.estimated_cost_usd:.4f}")
            print(f"Response preview:    {result.content[:200]!r}")
        finally:
            await cleanup_benchmark_org(db, org)


if __name__ == "__main__":
    asyncio.run(main())
