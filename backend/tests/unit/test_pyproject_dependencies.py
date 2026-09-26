"""pyproject.toml's [project] dependencies must match requirements.txt.

Vercel installs from pyproject.toml; Render, CI and local installs use
requirements.txt. A pin bumped in only one of them would ship a different
dependency set to each host.
"""

import pathlib
import tomllib

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def test_pyproject_dependencies_match_requirements_txt():
    requirements = [
        line.strip()
        for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert sorted(project["dependencies"]) == sorted(requirements)
