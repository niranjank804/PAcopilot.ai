import uuid

from TM1py import TM1Service

from src.tm1.resilience import call_with_resilience

# Cap on cells returned per MDX query — same discipline as MAX_ELEMENTS /
# MAX_NODES elsewhere: a wide-open ad hoc MDX tool can otherwise pull back
# an unbounded cellset.
MAX_CELLS = 500


class CellsetResult:

    def __init__(self, cells: dict[str, float]):
        self.cells = cells


async def execute_mdx(
    client: TM1Service,
    connection_id: uuid.UUID,
    mdx: str,
    **resilience_kwargs,
) -> CellsetResult:
    """Runs read-only MDX and returns a flat {element-path: value} map.

    Uses TM1py's *_elements_value_dict variant (keys are pipe-joined member
    names, e.g. "Jan-2026|Actual|Revenue") rather than the raw axis-indexed
    cellset — far simpler to turn into chart-ready rows, at the cost of
    losing axis structure for multi-series results (acceptable for a first
    version; see visualization module notes).
    """

    cells = await call_with_resilience(
        connection_id,
        client.cubes.cells.execute_mdx_elements_value_dict,
        mdx,
        top=MAX_CELLS,
        skip_zeros=True,
        **resilience_kwargs,
    )

    return CellsetResult(cells=dict(cells))
