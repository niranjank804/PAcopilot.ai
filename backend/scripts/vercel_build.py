"""Vercel build step: migrate, then seed.

Mirrors the Render buildCommand line for line. It runs in Vercel's build
container with the project's environment variables, so it needs
DATABASE_URL to reach the database - and it fails the deployment if it
cannot, which is the point: a build that cannot migrate must not be
promoted to serve traffic.
"""

import os
import subprocess
import sys

STEPS = [
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    [sys.executable, "scripts/seed_roles.py"],
    [sys.executable, "scripts/seed_permissions.py"],
    [sys.executable, "scripts/seed_admin.py"],
]


def main() -> None:
    env = {**os.environ, "PYTHONPATH": "."}

    for step in STEPS:
        print("build:", " ".join(step[1:]), flush=True)
        subprocess.run(step, check=True, env=env)


if __name__ == "__main__":
    main()
