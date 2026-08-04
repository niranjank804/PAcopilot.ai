"""Reader for the TM1 `.pro` TurboIntegrator export format.

The format is line-oriented and numerically tagged, not free text:

    602,"DATA - Load - Oracle"     <- scalar: tag,value
    566,42                         <- block:  tag,line-count then N raw lines
    <42 lines of SQL>
    572,217                        <- Prolog, 217 lines
    <217 lines of TI>

Scalars and blocks share the same `tag,rest` shape, so the reader cannot tell
them apart syntactically — `566,42` is indistinguishable from a scalar whose
value is 42. Block tags are therefore declared (`BLOCK_TAGS`) rather than
inferred, and anything else is read as a scalar.

This layer is deliberately dumb: it turns bytes into tags and raw text and
knows nothing about TurboIntegrator. Meaning is applied in parser.py.
"""

import re
from dataclasses import dataclass, field

# Tags whose value is a line count followed by that many raw lines.
BLOCK_TAGS: dict[int, str] = {
    566: "datasource_query",
    560: "parameter_names",
    561: "parameter_types",
    590: "parameter_defaults",
    637: "parameter_prompts",
    577: "variable_names",
    578: "variable_types",
    579: "variable_positions",
    580: "variable_start_bytes",
    581: "variable_end_bytes",
    582: "variable_formulas",
    572: "prolog",
    573: "metadata",
    574: "data",
    575: "epilog",
}

SCALAR_TAGS: dict[int, str] = {
    601: "format_version",
    602: "name",
    562: "datasource_type",
    585: "datasource_name_client",
    586: "datasource_name_server",
    564: "datasource_username",
    565: "datasource_password",
    567: "delimiter",
    568: "quote_character",
    588: "decimal_separator",
    589: "thousand_separator",
    569: "skip_lines",
    576: "ui_data",
    593: "datasource_odbo_provider",
    594: "datasource_odbo_datasource",
    595: "datasource_odbo_catalog",
    596: "datasource_odbo_sap_client_id",
    597: "datasource_odbo_location",
    598: "datasource_odbo_hierarchy",
    599: "max_error_count",
    603: "has_security_access",
    638: "unicode_datasource",
}

_TAG_LINE = re.compile(r"^(\d{3,4}),(.*)$", re.S)


@dataclass
class ProFile:
    """Raw tag content of a `.pro` export, before interpretation."""

    scalars: dict[str, str] = field(default_factory=dict)
    blocks: dict[str, list[str]] = field(default_factory=dict)
    # Tags present in the file that this reader has no name for. Surfaced
    # rather than dropped: TM1 versions add tags, and silently discarding
    # them is how a parser quietly stops representing the real file.
    unknown_tags: list[int] = field(default_factory=list)

    def scalar(self, name: str, default: str = "") -> str:
        return self.scalars.get(name, default)

    def block(self, name: str) -> list[str]:
        return self.blocks.get(name, [])

    def section(self, name: str) -> str:
        return "\n".join(self.blocks.get(name, []))


def _unquote(value: str) -> str:
    """TM1 wraps string scalars in double quotes and doubles embedded ones."""

    value = value.strip()

    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('""', '"')

    return value


def read_pro(text: str) -> ProFile:
    """Parse `.pro` text into tags. Never raises on malformed input.

    A truncated or corrupted export should yield whatever was readable — a
    partially-parsed process is still useful, and refusing the whole file
    because one block is short would drop the other 90% of the knowledge.
    """

    # utf-8-sig handles the BOM these exports carry; callers that read bytes
    # should decode with it. Normalise line endings so counts are reliable.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    result = ProFile()
    index = 0

    while index < len(lines):
        match = _TAG_LINE.match(lines[index])

        if match is None:
            index += 1
            continue

        tag = int(match.group(1))
        rest = match.group(2)

        if tag in BLOCK_TAGS:
            try:
                count = int(rest.strip())
            except ValueError:
                # A block tag whose count is not a number: treat as scalar so
                # the value is preserved rather than swallowing later lines.
                result.scalars[BLOCK_TAGS[tag]] = _unquote(rest)
                index += 1
                continue

            start = index + 1
            end = min(start + max(count, 0), len(lines))
            result.blocks[BLOCK_TAGS[tag]] = lines[start:end]
            index = end
            continue

        if tag in SCALAR_TAGS:
            result.scalars[SCALAR_TAGS[tag]] = _unquote(rest)
        else:
            result.unknown_tags.append(tag)

        index += 1

    return result
