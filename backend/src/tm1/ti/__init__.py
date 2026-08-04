"""Deterministic parsing and analysis of exported TurboIntegrator processes.

The pipeline is layered so each stage can be tested and reused on its own:

    format.py      `.pro` bytes            -> tags and raw blocks
    parser.py      tags                    -> ProcessRecord (facts)
    patterns.py    many ProcessRecords     -> recognised process patterns
    conventions.py many ProcessRecords     -> coding conventions + confidence

No stage calls a model. Everything produced here is derived from the source
files, so downstream generation can cite it as evidence rather than opinion.
"""

from src.tm1.ti.conventions import CodingDNA, infer_conventions
from src.tm1.ti.format import ProFile, read_pro
from src.tm1.ti.parser import ObjectRef, ProcessRecord, parse_process
from src.tm1.ti.patterns import PATTERNS, PatternMatch, classify

__all__ = [
    "CodingDNA",
    "ObjectRef",
    "PATTERNS",
    "PatternMatch",
    "ProFile",
    "ProcessRecord",
    "classify",
    "infer_conventions",
    "parse_process",
    "read_pro",
]
