"""Tests for the TurboIntegrator `.pro` parser.

The fixtures below are hand-written minimal exports rather than copies of the
customer processes that motivated this parser: the real files carry datasource
credentials and proprietary SQL, and a test suite is not a place to keep them.
Each fixture reproduces one structural fact observed in that corpus.
"""

import pytest

from src.tm1.ti import classify, infer_conventions, parse_process, read_pro
from src.tm1.ti.conventions import _has_inline_comment
from src.tm1.ti.parser import _split_args

ODBC_EXPORT = """601,100
602,"DATA - Load - Ledger"
562,"ODBC"
586,"FINDW"
564,"svc_tm1_read"
565,"qJ>CmD08fzD>ZUkdMapa"
566,3
SELECT account, amount
FROM gl.balances
WHERE period = ?pPeriod?
567,","
560,2
pPeriod
pYear
561,2
2
2
590,2
pPeriod,"2024-01"
pYear,"2024"
637,2
pPeriod,
pYear,
577,2
ACCOUNT
AMOUNT
578,2
2
1
572,6

# =========================================
# PURPOSE : Load ledger balances
# =========================================
If( pPeriod @= '' );
ProcessQuit;
EndIf;
573,0
574,3
nValue = StringToNumber( AMOUNT );
CellPutN( nValue, 'Finance', pYear, ACCOUNT );
ItemSkip;
575,2
CubeSetLogChanges( 'Finance', 1 );
SaveDataAll;
"""


def parse(text: str, name: str = "sample.pro"):
    return parse_process(text, source_file=name)


class TestFormat:
    def test_reads_scalars_and_blocks(self):
        pro = read_pro(ODBC_EXPORT)

        assert pro.scalar("name") == "DATA - Load - Ledger"
        assert pro.scalar("datasource_type") == "ODBC"
        assert len(pro.block("datasource_query")) == 3
        assert len(pro.block("prolog")) == 6

    def test_block_lines_are_not_read_as_tags(self):
        """SQL and TI lines can begin with digits and a comma."""

        text = '602,"P"\n566,2\n123,456\n789,0\n572,1\nx = 1;\n'
        pro = read_pro(text)

        assert pro.block("datasource_query") == ["123,456", "789,0"]
        assert pro.section("prolog") == "x = 1;"

    def test_truncated_block_does_not_raise(self):
        """A short file yields what was readable rather than nothing."""

        pro = read_pro('602,"P"\n572,500\nonly = 1;\n')

        assert pro.scalar("name") == "P"
        assert pro.section("prolog").strip() == "only = 1;"

    def test_unknown_tags_are_reported_not_dropped(self):
        pro = read_pro('602,"P"\n9999,x\n')

        assert 9999 in pro.unknown_tags


class TestParser:
    def test_extracts_datasource_and_parameters(self):
        record = parse(ODBC_EXPORT)

        assert record.name == "DATA - Load - Ledger"
        assert record.datasource_type == "odbc"
        assert record.datasource_name == "FINDW"
        assert "?pPeriod?" in record.datasource_query
        assert [p["name"] for p in record.parameters] == ["pPeriod", "pYear"]
        assert [v["name"] for v in record.variables] == ["ACCOUNT", "AMOUNT"]

    def test_credentials_are_flagged_but_never_captured(self):
        record = parse(ODBC_EXPORT)
        payload = record.as_dict()

        assert record.has_stored_credentials is True
        assert "svc_tm1_read" not in str(payload)
        assert "qJ>CmD08fzD" not in str(payload)

    def test_name_falls_back_to_filename_when_tag_602_absent(self):
        """TM1 omits tag 602 in many exports; the filename carries the name."""

        record = parse('601,100\n562,"NULL"\n', "ADMIN - Delete Attributepro.txt")

        assert record.name == "ADMIN - Delete Attribute"

    def test_name_fallback_strips_download_suffix(self):
        record = parse("601,100\n", "DATA - Load - FX Ratespro-1.txt")

        assert record.name == "DATA - Load - FX Rates"

    def test_identifies_cube_writes_and_sections(self):
        record = parse(ODBC_EXPORT)

        assert record.cubes_written == {"Finance"}
        assert any(o.section == "data" for o in record.objects)

    def test_detects_statement_form_functions(self):
        """`ProcessQuit;` has no argument list and a call regex misses it."""

        record = parse(ODBC_EXPORT)

        assert "PROCESSQUIT" in record.functions_used
        assert "SAVEDATAALL" in record.functions_used
        assert record.uses_error_handling is True

    def test_ignores_function_names_inside_string_literals(self):
        """MDX passed to SubsetCreateByMDX is not TI code."""

        text = (
            "601,100\n572,1\n"
            "SubsetCreateByMDX( 'sTemp', 'Account', "
            "'{Descendants( [Account].[Total] )}' );\n"
        )
        record = parse(text)

        assert "DESCENDANTS" not in record.functions_used
        assert "SUBSETCREATEBYMDX" in record.functions_used

    def test_captures_mdx_expressions(self):
        text = (
            "601,100\n572,1\n"
            "SubsetCreateByMDX( 'sTemp', '{ TM1SubsetAll( [Account] ) }' );\n"
        )
        record = parse(text)

        assert record.mdx_expressions == ["{ TM1SubsetAll( [Account] ) }"]

    def test_ignores_function_names_inside_comments(self):
        text = "601,100\n572,1\n# calls CellPutN( 1, 'Cube' ) eventually\n"
        record = parse(text)

        assert "CELLPUTN" not in record.functions_used

    def test_hash_inside_a_literal_does_not_start_a_comment(self):
        """'#,##0' is a common TM1 format mask."""

        text = "601,100\n572,2\nsMask = '#,##0';\nCellPutS( sMask, 'Cube', 'a' );\n"
        record = parse(text)

        assert "CELLPUTS" in record.functions_used

    def test_variable_object_names_are_marked_non_literal(self):
        text = "601,100\n572,1\nCellPutN( 1, sCubeName, 'a' );\n"
        record = parse(text)

        reference = next(o for o in record.objects if o.kind == "cube")
        assert reference.literal is False
        assert reference.name == "sCubeName"

    def test_container_arguments_are_typed_as_their_own_kind(self):
        """SubsetCreate( Dim, Sub ) names a dimension first, not a subset."""

        text = "601,100\n572,1\nSubsetCreate( 'Account', 'zTmp' );\n"
        record = parse(text)

        kinds = {(o.name, o.kind, o.access) for o in record.objects}

        assert ("Account", "dimension", "reference") in kinds
        assert ("zTmp", "subset", "create") in kinds
        assert not any(o.name == "Account" and o.kind == "subset" for o in record.objects)

    def test_view_functions_name_the_cube_first(self):
        text = "601,100\n572,1\nViewCreate( 'Finance', 'zTmpView' );\n"
        record = parse(text)

        kinds = {(o.name, o.kind, o.access) for o in record.objects}

        assert ("Finance", "cube", "reference") in kinds
        assert ("zTmpView", "view", "create") in kinds

    def test_destroying_a_view_does_not_destroy_its_cube(self):
        text = "601,100\n575,1\nViewDestroy( 'Finance', 'zTmpView' );\n"
        record = parse(text)

        cube = next(o for o in record.objects if o.kind == "cube")
        view = next(o for o in record.objects if o.kind == "view")

        assert cube.access == "reference"
        assert view.access == "destroy"

    def test_subset_create_by_mdx_has_no_dimension_argument(self):
        """SubsetCreateByMDX( SubName, MDX ) — argument 0 really is the subset."""

        text = "601,100\n572,1\nSubsetCreateByMDX( 'zTmp', '{ [a] }' );\n"
        record = parse(text)

        assert ("zTmp", "subset") in {(o.name, o.kind) for o in record.objects}
        assert not any(o.kind == "dimension" for o in record.objects)

    def test_attribute_functions_name_the_owning_dimension(self):
        text = "601,100\n574,1\nAttrPutS( vName, 'Account', vElem, 'Description' );\n"
        record = parse(text)

        kinds = {(o.name, o.kind) for o in record.objects}

        assert ("Account", "dimension") in kinds
        assert ("Description", "attribute") in kinds

    def test_view_subset_assign_records_all_four_containers(self):
        text = (
            "601,100\n572,1\n"
            "ViewSubsetAssign( 'Finance', 'vTmp', 'Account', 'sTmp' );\n"
        )
        record = parse(text)

        kinds = {(o.name, o.kind) for o in record.objects}

        assert kinds >= {
            ("Finance", "cube"),
            ("vTmp", "view"),
            ("Account", "dimension"),
            ("sTmp", "subset"),
        }

    def test_temporary_flag_is_recorded(self):
        """A Temporary view is destroyed by TM1, so it is not a leak."""

        text = "601,100\n572,1\nViewCreate( 'Finance', 'zTmp', 1 );\n"

        assert parse(text).uses_temporary_objects is True
        assert parse("601,100\n572,1\nViewCreate( 'Finance', 'zTmp' );\n").uses_temporary_objects is False

    def test_flow_control_is_not_counted_as_error_handling(self):
        """ProcessBreak exits the source loop; the Epilog still runs."""

        text = "601,100\n574,2\nItemSkip;\nProcessBreak;\n"
        record = parse(text)

        assert record.uses_error_handling is False
        assert "ITEMSKIP" in record.functions_used

    def test_reports_functions_it_cannot_identify(self):
        text = "601,100\n572,1\nNotARealTM1Function( 1 );\n"
        record = parse(text)

        assert "NOTAREALTM1FUNCTION" in record.unknown_functions

    def test_language_keywords_are_not_unknown_functions(self):
        text = "601,100\n572,3\nIf( 1 = 1 );\nElseIf( 2 = 2 );\nEndIf;\n"
        record = parse(text)

        assert record.unknown_functions == []

    def test_empty_input_produces_warnings_not_an_exception(self):
        record = parse("", "")

        assert record.parse_warnings


class TestSplitArgs:
    def test_respects_nesting_and_literals(self):
        args = _split_args("1, Subst( a, 1, 2 ), 'a, b' )")

        assert args == ["1", "Subst( a, 1, 2 )", "'a, b'"]

    def test_handles_doubled_quote_escape(self):
        args = _split_args("'it''s', 2 )")

        assert args == ["'it''s'", "2"]


class TestInlineComments:
    def test_full_line_comment_is_not_inline(self):
        assert _has_inline_comment("# ===== SECTION =====\nx = 1;\n") is False

    def test_trailing_comment_is_inline(self):
        assert _has_inline_comment("x = 1; # set it\n") is True

    def test_hash_in_literal_is_not_a_comment(self):
        assert _has_inline_comment("sMask = '#,##0';\n") is False

    def test_finds_inline_comment_after_an_earlier_literal(self):
        assert _has_inline_comment("s = '#,##0'; # trailing\n") is True


class TestPatterns:
    def test_classifies_a_relational_loader(self):
        matches = {m.key for m in classify(parse(ODBC_EXPORT))}

        assert "oracle_loader" in matches

    def test_every_match_carries_evidence(self):
        for match in classify(parse(ODBC_EXPORT)):
            assert match.evidence, f"{match.key} matched without evidence"
            assert 0 < match.score <= 1

    def test_unrelated_process_matches_nothing(self):
        record = parse('601,100\n602,"noop"\n562,"NULL"\n572,1\nnX = 1;\n')

        assert classify(record) == []

    def test_a_pattern_requires_its_defining_property(self):
        """Shared weak signals must not add up to the wrong label.

        This process has parameters and writes a cube — enough votes to clear
        the threshold — but no ODBC datasource, so it is not an ODBC loader.
        """

        text = (
            '601,100\n602,"DATA - Load - Manual"\n562,"NULL"\n'
            "560,1\npMonth\n561,1\n2\n"
            "574,1\nCellPutN( 1, 'Finance', pMonth );\n"
        )
        record = parse(text)

        assert record.parameters
        assert record.cubes_written == {"Finance"}
        assert "oracle_loader" not in {m.key for m in classify(record)}
        assert "ascii_loader" not in {m.key for m in classify(record)}

    def test_cleanup_requires_a_destroy_call(self):
        record = parse(ODBC_EXPORT)

        assert "cleanup" not in {m.key for m in classify(record)}


class TestReport:
    def test_reports_practices_a_corpus_does_not_follow(self):
        """The absence of a good practice is the finding worth surfacing."""

        from src.tm1.ti.report import build_report

        report = build_report([parse(ODBC_EXPORT, f"p{i}.pro") for i in range(4)])
        logging_row = next(h for h in report["health"] if h["key"] == "logging")

        assert logging_row["followed"] == 0
        assert logging_row["share"] == "0%"

    def test_cleanup_share_is_measured_against_creators_only(self):
        """Processes that create nothing cannot fail to clean up."""

        from src.tm1.ti.report import build_report

        report = build_report([parse(ODBC_EXPORT, f"p{i}.pro") for i in range(4)])
        cleanup = next(h for h in report["health"] if h["key"] == "cleanup")

        assert cleanup["total"] == 0
        assert cleanup["share"] == "n/a"

    def test_renders_without_established_standards(self):
        from src.tm1.ti.report import build_report, render_markdown

        markdown = render_markdown(build_report([parse(ODBC_EXPORT)]))

        assert "No practice was consistent enough" in markdown

    def test_empty_corpus_renders(self):
        from src.tm1.ti.report import build_report, render_markdown

        assert render_markdown(build_report([]))


class TestConventions:
    def test_confidence_is_damped_by_sample_size(self):
        """Three unanimous files must not outrank a large majority."""

        small = infer_conventions([parse(ODBC_EXPORT, f"p{i}.pro") for i in range(3)])
        large = infer_conventions([parse(ODBC_EXPORT, f"p{i}.pro") for i in range(60)])

        key = "no_inline_comments"
        small_value = next(c for c in small.conventions if c.key == key).confidence
        large_value = next(c for c in large.conventions if c.key == key).confidence

        assert small_value < large_value

    def test_separator_example_comes_from_the_corpus(self):
        """A stock example would contradict the rule for most organizations."""

        records = [
            parse('601,100\n602,"load_actuals_%d"\n562,"NULL"\n572,1\nnX = 1;\n' % i)
            for i in range(20)
        ]
        rule = next(
            c
            for c in infer_conventions(records).conventions
            if c.key == "process_name_separator"
        )

        assert "'_'" in rule.statement
        assert "load_actuals_0" in rule.statement
        assert "DATA - Load - Oracle" not in rule.statement

    def test_detects_parameter_prefix(self):
        dna = infer_conventions([parse(ODBC_EXPORT)])

        assert dna.naming["parameter_prefix"] == "p"

    def test_records_counter_examples(self):
        clean = parse(ODBC_EXPORT, "clean.pro")
        dirty = parse('601,100\n602,"dirty"\n572,1\nx = 1; # inline\n', "dirty.pro")

        dna = infer_conventions([clean, dirty])
        rule = next(c for c in dna.conventions if c.key == "no_inline_comments")

        assert rule.counter_examples == ["dirty"]
        assert rule.support == 1
        assert rule.sample == 2

    def test_empty_corpus_is_safe(self):
        dna = infer_conventions([])

        assert dna.process_count == 0
        assert dna.conventions == []

    @pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
    def test_enforced_filters_by_confidence(self, confidence):
        dna = infer_conventions([parse(ODBC_EXPORT, f"p{i}.pro") for i in range(20)])

        assert all(c.confidence >= confidence for c in dna.enforced(confidence))
