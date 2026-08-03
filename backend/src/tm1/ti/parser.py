"""Semantic parser: a `.pro` export becomes a structured ProcessRecord.

Everything here is derived deterministically from the file. Nothing is
inferred by a model — the point of parsing is that the answers are facts, not
guesses, so downstream pattern and convention learning stands on solid ground.

What a model *would* be needed for (the business purpose of a process in
plain English) is deliberately left as a field for a later enrichment step
rather than faked here.
"""

import re
from dataclasses import asdict, dataclass, field

from src.tm1.functions import lookup as lookup_function
from src.tm1.ti.format import ProFile, read_pro

# TM1 datasource type codes as they appear in tag 562.
DATASOURCE_TYPES = {
    "NULL": "none",
    "": "none",
    "ODBC": "odbc",
    "CHARACTERDELIMITED": "ascii_delimited",
    "ASCII": "ascii",
    "VIEW": "cube_view",
    "SUBSET": "dimension_subset",
    "TM1CUBEVIEW": "cube_view",
    "TM1DIMENSIONSUBSET": "dimension_subset",
}

SECTIONS = ("prolog", "metadata", "data", "epilog")

# Call sites we care about, and which argument carries the object name.
# Index is 0-based into the argument list.
_CUBE_WRITE_FUNCTIONS = {
    "CELLPUTN": 1,
    "CELLPUTS": 1,
    "CELLINCREMENTN": 1,
}
_CUBE_READ_FUNCTIONS = {
    "CELLGETN": 0,
    "CELLGETS": 0,
    "CELLISUPDATEABLE": 0,
    "DB": 0,
}
_CUBE_ADMIN_FUNCTIONS = {
    "CUBECREATE": 0,
    "CUBEDESTROY": 0,
    "CUBECLEARDATA": 0,
    "CUBEEXISTS": 0,
    "VIEWZEROOUT": 0,
}
_DIMENSION_FUNCTIONS = {
    "DIMENSIONCREATE": 0,
    "DIMENSIONDESTROY": 0,
    "DIMENSIONEXISTS": 0,
    "DIMENSIONDELETEALLELEMENTS": 0,
    "DIMENSIONELEMENTINSERT": 0,
    "DIMENSIONELEMENTDELETE": 0,
    "DIMENSIONELEMENTCOMPONENTADD": 0,
    "DIMENSIONELEMENTCOMPONENTDELETE": 0,
    "DIMIX": 0,
    "DIMNM": 0,
    "DIMSIZ": 0,
    "ELLEV": 0,
    "ELISANC": 0,
    "ELPAR": 0,
    "ELCOMP": 0,
}
# Attribute functions name the dimension that owns the attribute, not the
# attribute itself: AttrPutS( Value, DimName, ElName, AttrName ).
_ATTRIBUTE_FUNCTIONS: dict[str, tuple[tuple[int, str], ...]] = {
    "ATTRPUTS": ((1, "dimension"), (3, "attribute")),
    "ATTRPUTN": ((1, "dimension"), (3, "attribute")),
    "ATTRS": ((0, "dimension"), (2, "attribute")),
    "ATTRN": ((0, "dimension"), (2, "attribute")),
    "ATTRINSERT": ((0, "dimension"), (2, "attribute")),
    "ATTRDELETE": ((0, "dimension"), (1, "attribute")),
}
# Subset and view functions name their CONTAINER first and the object second:
# SubsetCreate( DimName, SubName ), ViewCreate( CubeName, ViewName ). Reading
# argument 0 as the subset or the view records a dimension under the name
# "subset" and a cube under the name "view" — which then propagates into the
# knowledge graph as a wrong-typed node. Each argument is therefore typed
# individually below rather than by which family the function belongs to.
#
# SubsetCreateByMDX is the exception: SubsetCreateByMDX( SubName, MDX ) has no
# dimension argument at all, so its argument 0 really is the subset.
_VIEW_FUNCTIONS: dict[str, tuple[tuple[int, str], ...]] = {
    "VIEWCREATE": ((0, "cube"), (1, "view")),
    "VIEWDESTROY": ((0, "cube"), (1, "view")),
    "VIEWEXISTS": ((0, "cube"), (1, "view")),
    "VIEWZEROOUT": ((0, "cube"), (1, "view")),
    "VIEWSUBSETASSIGN": ((0, "cube"), (1, "view"), (2, "dimension"), (3, "subset")),
    "VIEWCREATEBYMDX": ((0, "cube"), (1, "view")),
}
_SUBSET_FUNCTIONS: dict[str, tuple[tuple[int, str], ...]] = {
    "SUBSETCREATE": ((0, "dimension"), (1, "subset")),
    "SUBSETDESTROY": ((0, "dimension"), (1, "subset")),
    "SUBSETEXISTS": ((0, "dimension"), (1, "subset")),
    "SUBSETELEMENTINSERT": ((0, "dimension"), (1, "subset")),
    "SUBSETDELETEALLELEMENTS": ((0, "dimension"), (1, "subset")),
    "SUBSETMDXSET": ((0, "dimension"), (1, "subset")),
    "SUBSETCREATEBYMDX": ((0, "subset"),),
}
_SECURITY_FUNCTIONS = {
    "SECURITYREFRESH",
    "ADDCLIENT",
    "ADDGROUP",
    "ASSIGNCLIENTTOGROUP",
    "REMOVECLIENTFROMGROUP",
    "ELEMENTSECURITYPUT",
    "CELLSECURITYCUBECREATE",
    "DELETECLIENT",
    "DELETEGROUP",
}
# Deliberately narrow. ProcessBreak is ordinary flow control — it stops
# reading the source and falls through to the Epilog, which still runs — and
# ItemSkip silently discards a record, which is the opposite of handling an
# error. Counting either as error handling overstates how defensively a
# codebase is written, which is exactly the measure a team would act on.
_ERROR_FUNCTIONS = {"PROCESSERROR", "PROCESSQUIT", "ITEMREJECT"}

# Flow control worth recording separately rather than discarding.
_FLOW_FUNCTIONS = {"PROCESSBREAK", "ITEMSKIP"}
_LOGGING_FUNCTIONS = {"ASCIIOUTPUT", "TEXTOUTPUT", "LOGOUTPUT"}
_PERFORMANCE_FUNCTIONS = {
    "ENABLEBULKLOADMODE",
    "DISABLEBULKLOADMODE",
    "CUBESETLOGCHANGES",
    "VIEWEXTRACTSKIPCALCSSET",
    "VIEWEXTRACTSKIPRULEVALUESSET",
    "VIEWEXTRACTSKIPZEROESSET",
    "BATCHUPDATESTART",
    "BATCHUPDATEFINISH",
}

_COMMENT = re.compile(r"#[^\n]*")

# String literals and comments in one alternation, left to right, so a '#'
# inside a literal is part of the literal and a quote inside a comment does
# not open a string. Scanning for either one separately gets this wrong.
_NOISE = re.compile(r"'(?:[^']|'')*'|#[^\n]*")

_CALL = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)\s*\(")

# TM1 functions invoked as bare statements. `ProcessQuit;` has no argument
# list, so a call regex anchored on '(' never sees it — and these are exactly
# the error-handling and persistence calls worth knowing about.
_STATEMENT_FUNCTIONS = frozenset(
    {
        "PROCESSQUIT",
        "PROCESSBREAK",
        "PROCESSERROR",
        "ITEMSKIP",
        "ITEMREJECT",
        "SAVEDATAALL",
        "CUBESAVEDATA",
        "SECURITYREFRESH",
        "SYNCHRONIZED",
        "DISABLEBULKLOADMODE",
        "ENABLEBULKLOADMODE",
        "BATCHUPDATESTART",
        "BATCHUPDATEFINISH",
        "SERVERSHUTDOWN",
    }
)
_STATEMENT_CALL = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*)\s*;",
)

# Functions whose argument carries an MDX expression rather than TI code, and
# the 0-based position of that argument. Indices verified against the observed
# call sites, not assumed:
#   SubsetCreateByMDX( SubName, MDX )
#   SubsetMDXSet( DimName, SubName, MDX )
#   ViewCreateByMDX( CubeName, ViewName, MDX )
_MDX_ARGUMENT = {
    "SUBSETCREATEBYMDX": 1,
    "SUBSETMDXSET": 2,
    "VIEWCREATEBYMDX": 2,
}


@dataclass
class ObjectRef:
    """A named TM1 object a process touches, and how."""

    name: str
    kind: str  # cube | dimension | view | subset | attribute
    access: str  # read | write | create | destroy | reference
    section: str
    literal: bool  # False when the name came from a variable, not a literal


@dataclass
class ProcessRecord:

    name: str = ""
    source_file: str = ""
    format_version: str = ""

    datasource_type: str = "none"
    datasource_name: str = ""
    datasource_query: str = ""
    delimiter: str = ""
    quote_character: str = ""

    # Whether the export carried datasource credentials. The values are never
    # read into the record: these files are destined for a knowledge base and
    # an embedding index, and a service-account name is a credential half.
    has_stored_credentials: bool = False

    parameters: list[dict] = field(default_factory=list)
    variables: list[dict] = field(default_factory=list)

    prolog: str = ""
    metadata: str = ""
    data: str = ""
    epilog: str = ""

    objects: list[ObjectRef] = field(default_factory=list)
    functions_used: dict[str, int] = field(default_factory=dict)
    unknown_functions: list[str] = field(default_factory=list)
    mdx_expressions: list[str] = field(default_factory=list)

    comments: list[str] = field(default_factory=list)
    header_comment: str = ""

    uses_logging: bool = False
    uses_error_handling: bool = False
    # ItemSkip / ProcessBreak: real and common, but a different practice from
    # failing deliberately, and reporting them together hides how rarely a
    # codebase actually validates its input.
    uses_record_skipping: bool = False
    uses_security_functions: bool = False
    performance_functions: list[str] = field(default_factory=list)
    temporary_objects: list[str] = field(default_factory=list)
    has_cleanup: bool = False
    # A view or subset created with the Temporary flag is destroyed by TM1
    # when the session ends, so its absence from the Epilog is not a leak.
    uses_temporary_objects: bool = False

    line_counts: dict[str, int] = field(default_factory=dict)
    unknown_tags: list[int] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    # Reserved for a later LLM enrichment pass. Left empty by the parser so
    # that a generated summary can never be mistaken for parsed fact.
    business_purpose: str = ""

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["objects"] = [asdict(o) for o in self.objects]
        return payload

    @property
    def cubes_written(self) -> set[str]:
        return {o.name for o in self.objects if o.kind == "cube" and o.access == "write"}

    @property
    def cubes_read(self) -> set[str]:
        return {o.name for o in self.objects if o.kind == "cube" and o.access == "read"}

    @property
    def dimensions_used(self) -> set[str]:
        return {o.name for o in self.objects if o.kind == "dimension"}


def _access_for(function: str, default: str) -> str:
    if function.endswith("CREATE") or function.endswith("CREATEBYMDX"):
        return "create"
    if function.endswith("DESTROY"):
        return "destroy"
    return default


def _name_from_filename(source_file: str) -> str:
    """`DATA - Load - FX Ratespro-1.txt` -> `DATA - Load - FX Rates`."""

    if not source_file:
        return ""

    stem = re.sub(r"\.(txt|pro)$", "", source_file, flags=re.I)
    # Exports are `<name>.pro`; flattening to .txt glues `pro` onto the name,
    # and re-downloads add a ` (1)` or `-1` disambiguator after it.
    stem = re.sub(r"pro(?:[-\s]*\(?\d+\)?)?$", "", stem)

    return stem.strip()


def _split_args(call_text: str) -> list[str]:
    """Split a call's argument list, respecting nesting and string literals."""

    args: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False
    index = 0

    while index < len(call_text):
        char = call_text[index]

        if in_string:
            if char == "'":
                if index + 1 < len(call_text) and call_text[index + 1] == "'":
                    current.append("''")
                    index += 2
                    continue
                in_string = False
            current.append(char)
        elif char == "'":
            in_string = True
            current.append(char)
        elif char in "([":
            depth += 1
            current.append(char)
        elif char in ")]":
            if depth == 0:
                break
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)

        index += 1

    if current:
        args.append("".join(current).strip())

    return args


def _literal(value: str) -> tuple[str, bool]:
    """Return (name, is_literal). Non-literals are variable references."""

    value = value.strip()

    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'"), True

    return value, False


def _mask(code: str) -> str:
    """Blank out comments and string literals, preserving every offset.

    Offsets must line up with the original text: call *names* are found in
    the masked copy (so `Descendants(` inside an MDX string is not mistaken
    for a TI call), while call *arguments* are read from the original at the
    same position, because the argument values live inside those literals.
    """

    def blank(match: re.Match) -> str:
        return "".join("\n" if c == "\n" else " " for c in match.group(0))

    return _NOISE.sub(blank, code)


def _iter_calls(code: str):
    """Yield (FUNCTION_UPPER, raw_args_text) for each genuine call site."""

    masked = _mask(code)

    for match in _CALL.finditer(masked):
        yield match.group(1).upper(), code[match.end():]


def _iter_statements(code: str):
    """Yield FUNCTION_UPPER for each bare `Function;` statement."""

    masked = _mask(code)

    for match in _STATEMENT_CALL.finditer(masked):
        name = match.group(1).upper()
        if name in _STATEMENT_FUNCTIONS:
            yield name


def _collect(record: ProcessRecord, section: str, code: str) -> None:
    if not code.strip():
        return

    def add(name_arg: str, kind: str, access: str) -> None:
        name, is_literal = _literal(name_arg)
        if not name:
            return
        record.objects.append(
            ObjectRef(
                name=name,
                kind=kind,
                access=access,
                section=section,
                literal=is_literal,
            )
        )

    def note(function: str) -> None:
        record.functions_used[function] = record.functions_used.get(function, 0) + 1

        if function in _LOGGING_FUNCTIONS:
            record.uses_logging = True
        if function in _ERROR_FUNCTIONS:
            record.uses_error_handling = True
        if function in _FLOW_FUNCTIONS:
            record.uses_record_skipping = True
        if function in _SECURITY_FUNCTIONS:
            record.uses_security_functions = True
        if function in _PERFORMANCE_FUNCTIONS:
            if function not in record.performance_functions:
                record.performance_functions.append(function)

    for function in _iter_statements(code):
        note(function)

    for function, tail in _iter_calls(code):
        note(function)

        args = _split_args(tail)

        def arg(position: int) -> str | None:
            return args[position] if position < len(args) else None

        if function in _MDX_ARGUMENT:
            expression = arg(_MDX_ARGUMENT[function])
            if expression:
                text, is_literal = _literal(expression)
                if is_literal and text.strip():
                    record.mdx_expressions.append(text.strip())

        # Single-argument families: the whole call refers to one object.
        for table, kind, access in (
            (_CUBE_WRITE_FUNCTIONS, "cube", "write"),
            (_CUBE_READ_FUNCTIONS, "cube", "read"),
            (_DIMENSION_FUNCTIONS, "dimension", "reference"),
            (_CUBE_ADMIN_FUNCTIONS, "cube", "reference"),
        ):
            if function in table:
                value = arg(table[function])
                if value is not None:
                    add(value, kind, _access_for(function, access))

        # Families that name a container and the object inside it. Only the
        # object itself is created or destroyed; naming its container is a
        # reference, so a ViewDestroy must not mark the cube as destroyed.
        # ViewCreate/SubsetCreate take an optional trailing Temporary flag;
        # a temporary object is owned by the session and destroyed by TM1
        # automatically, so it is not a leak when the Epilog does not destroy
        # it. Recorded here so a cleanup check can tell the two cases apart.
        if function in ("VIEWCREATE", "SUBSETCREATE") and len(args) > 2:
            flag = args[2].strip().strip("'")
            if flag and flag != "0":
                record.uses_temporary_objects = True

        for table in (_VIEW_FUNCTIONS, _SUBSET_FUNCTIONS, _ATTRIBUTE_FUNCTIONS):
            if function not in table:
                continue

            positions = table[function]
            innermost = positions[-1][0]

            for position, kind in positions:
                value = arg(position)
                if value is None:
                    continue
                access = (
                    _access_for(function, "reference")
                    if position == innermost
                    else "reference"
                )
                add(value, kind, access)


def parse_process(text: str, source_file: str = "") -> ProcessRecord:
    """Parse one `.pro` export into a structured record."""

    pro: ProFile = read_pro(text)
    record = ProcessRecord(source_file=source_file)

    # TM1 omits tag 602 in many exports — the process name is carried by the
    # filename instead (`DATA - Load - FX Ratespro.txt`). Falling back to it
    # is not a guess; it is where the server put the name.
    record.name = pro.scalar("name") or _name_from_filename(source_file)
    record.format_version = pro.scalar("format_version")
    record.unknown_tags = sorted(set(pro.unknown_tags))

    raw_type = pro.scalar("datasource_type").upper()
    record.datasource_type = DATASOURCE_TYPES.get(raw_type, raw_type.lower() or "none")
    record.datasource_name = pro.scalar("datasource_name_server") or pro.scalar(
        "datasource_name_client"
    )
    record.has_stored_credentials = bool(
        pro.scalar("datasource_username") or pro.scalar("datasource_password")
    )
    record.delimiter = pro.scalar("delimiter")
    record.quote_character = pro.scalar("quote_character")
    record.datasource_query = "\n".join(pro.block("datasource_query")).strip()

    names = pro.block("parameter_names")
    types = pro.block("parameter_types")
    defaults = pro.block("parameter_defaults")
    prompts = pro.block("parameter_prompts")

    for position, parameter in enumerate(names):
        if not parameter.strip():
            continue
        record.parameters.append(
            {
                "name": parameter.strip(),
                "type": (types[position].strip() if position < len(types) else ""),
                "default": (defaults[position].strip() if position < len(defaults) else ""),
                "prompt": (prompts[position].strip() if position < len(prompts) else ""),
            }
        )

    variable_names = pro.block("variable_names")
    variable_types = pro.block("variable_types")

    for position, variable in enumerate(variable_names):
        if not variable.strip():
            continue
        record.variables.append(
            {
                "name": variable.strip(),
                "type": (
                    variable_types[position].strip()
                    if position < len(variable_types)
                    else ""
                ),
            }
        )

    for section in SECTIONS:
        setattr(record, section, pro.section(section))
        record.line_counts[section] = len(pro.block(section))

    for section in SECTIONS:
        _collect(record, section, getattr(record, section))

    all_code = "\n".join(getattr(record, section) for section in SECTIONS)
    record.comments = [
        line.strip()
        for line in _COMMENT.findall(all_code)
        if line.strip().strip("#").strip()
    ]
    record.header_comment = "\n".join(record.comments[:12])

    record.temporary_objects = sorted(
        {
            o.name
            for o in record.objects
            if o.literal and re.match(r"^(z|tmp|temp)", o.name, re.I)
        }
    )
    record.has_cleanup = any(
        o.access == "destroy" and o.section == "epilog" for o in record.objects
    )

    record.unknown_functions = sorted(
        {
            function
            for function in record.functions_used
            if lookup_function(function) is None
            and function.upper()
            not in {"IF", "ELSEIF", "ELSE", "WHILE", "END", "ENDIF", "BREAK", "CONTINUE"}
        }
    )

    if not record.name:
        record.parse_warnings.append("No process name (tag 602) found.")
    if not any(record.line_counts.get(s) for s in SECTIONS):
        record.parse_warnings.append("No TI code sections found.")

    return record
