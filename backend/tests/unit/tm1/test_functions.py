import pytest

from src.tm1 import functions as tm1_functions
from src.tm1.functions import (
    find_calls,
    function_count,
    lookup,
    search,
    validate_code,
    validate_process,
)

# Real, valid TI source. Nothing here may ever be reported: a false positive
# on working code is worse than missing a real problem, because it trains
# reviewers to ignore the checker.
VALID_TI = """
# Build the Product dimension
sDim = 'zTest_Product';

IF( DimensionExists( sDim ) = 0 );
   DimensionCreate( sDim );
ENDIF;

DimensionDeleteAllElements( sDim );
DimensionElementInsert( sDim, '', 'All Products', 'C' );
DimensionElementComponentAdd( sDim, 'All Products', 'Hardware', 1 );

nSize = DIMSIZ( sDim );
WHILE( nSize > 0 );
   sElem = DIMNM( sDim, nSize );
   IF( ELLEV( sDim, sElem ) = 0 );
      ATTRPUTS( 'x', sDim, sElem, 'Caption' );
   ENDIF;
   nSize = nSize - 1;
END;
"""

VALID_RULES = """
SKIPCHECK;
['Change'] = N: DB( 'BalanceSheet', !Organization, 'Balance', !Years );
['Q1'] = ['Balance', 'Mar'];
FEEDERS;
['Balance'] => DB( 'Trial Balance', !Organization, 'Balance' );
"""


def test_library_loads():
    assert function_count() > 400


class TestLookup:

    def test_exact_and_case_insensitive(self):
        assert lookup("DimensionElementInsert") is not None
        assert lookup("dimensionelementinsert") is not None
        assert lookup("  ABS  ") is not None

    def test_unknown_returns_none(self):
        assert lookup("TotallyMadeUpFunction") is None
        assert lookup("") is None

    def test_context_and_version_tags(self):
        db = lookup("DB")
        assert db is not None and db.contexts == ("Rules",)

        cube_save = lookup("CubeSaveData")
        assert cube_save is not None and cube_save.versions == ("v11",)

    def test_search(self):
        assert any(f.name == "DimensionElementInsert" for f in search("dimensionelement"))
        assert search("") == []


class TestNoFalsePositives:
    """The property that matters most."""

    def test_valid_ti_is_clean(self):
        assert validate_code(VALID_TI, context="TI", version="v12") == []

    def test_valid_rules_are_clean(self):
        assert validate_code(VALID_RULES, context="Rules", version="v12") == []

    def test_function_names_in_comments_ignored(self):
        code = """
# CubeSaveData( 'Sales' ) was removed
# and SaveDataAll() with it
DimensionCreate( 'X' );
"""
        assert validate_code(code, context="TI", version="v12") == []

    def test_function_names_in_strings_ignored(self):
        code = """
sMsg = 'remember to call CubeSaveData( x )';
sOther = 'ExecuteCommand( ''dir'' )';
DimensionCreate( 'X' );
"""
        assert validate_code(code, context="TI", version="v12") == []

    def test_identifiers_containing_function_names_ignored(self):
        code = "vCubeSaveData = 1;\nmy_ExecuteCommand = 2;\nDimensionCreate( 'X' );"
        assert validate_code(code, context="TI", version="v12") == []

    def test_unlisted_functions_never_reported(self):
        # The library documents public functions; absence is not proof of
        # non-existence, so an unrecognised name must be left alone.
        code = "SomeUndocumentedInternalFunction( 1, 2 );"
        assert validate_code(code, context="TI", version="v12") == []


class TestDetection:

    def test_v11_only_function_flagged_on_v12(self):
        issues = validate_code("CubeSaveData( 'Sales' );", context="TI", version="v12")
        assert len(issues) == 1
        assert issues[0]["function"] == "CubeSaveData"
        assert issues[0]["kind"] == "version"

    def test_same_code_clean_on_v11(self):
        assert validate_code("CubeSaveData( 'Sales' );", context="TI", version="v11") == []

    def test_version_skipped_when_unknown(self):
        assert validate_code("CubeSaveData( 'Sales' );", context="TI") == []

    def test_rules_only_function_flagged_in_ti(self):
        issues = validate_code("nVal = DB( 'Sales', 'Actual' );", context="TI")
        assert any(i["function"] == "DB" and i["kind"] == "context" for i in issues)

    def test_ti_only_function_flagged_in_rules(self):
        issues = validate_code(
            "['x'] = N: DimensionElementInsert( 'D', '', 'E', 'N' );",
            context="Rules",
        )
        assert any(i["kind"] == "context" for i in issues)

    def test_repeated_calls_reported_once(self):
        code = "CubeSaveData( 'a' );\nCubeSaveData( 'b' );\nCubeSaveData( 'c' );"
        assert len(validate_code(code, context="TI", version="v12")) == 1

    def test_line_numbers(self):
        assert find_calls("A(\n)\nB()")[0][1] == 1
        issues = validate_code(
            "DimensionCreate( 'X' );\n\n\nSaveDataAll();", context="TI", version="v12"
        )
        assert issues[0]["line"] == 4


class TestValidateProcess:

    def test_sections_are_tagged(self):
        issues = validate_process(
            {
                "prolog": "DimensionCreate( 'X' );",
                "metadata": "",
                "data": "CubeSaveData( 'Sales' );",
                "epilog": "SaveDataAll();",
            },
            version="v12",
        )
        assert sorted({i["section"] for i in issues}) == ["data", "epilog"]

    def test_clean_process(self):
        assert validate_process({"prolog": VALID_TI}, version="v12") == []

    def test_missing_sections_tolerated(self):
        assert validate_process({}, version="v12") == []


class TestHashInsideStringLiterals:
    """Regression: '#' is ordinary inside a TM1 string.

    Stripping comments before strings let a '#' in a literal blank the rest of
    the line including its closing quote, breaking quote parity for everything
    after it — which both fabricated calls out of later string contents and
    hid real ones.
    """

    def test_format_mask_does_not_hide_later_calls(self):
        code = "sMask = '#,##0';\nCubeSaveData( 'Sales' );"
        issues = validate_code(code, context="TI", version="v12")
        assert [i["function"] for i in issues] == ["CubeSaveData"]

    def test_prose_after_hash_string_is_not_scanned_as_code(self):
        code = "sTag = 'Batch #7';\nsMsg = 'Fiscal Year (FY) rollover complete';"
        assert validate_code(code, context="Rules") == []

    def test_hash_element_name_is_string_content(self):
        code = "sMdx = '{ [Region].[#All] }';\nsTxt = 'use CellGetN( ) here';"
        assert validate_code(code, context="Rules") == []

    def test_apostrophe_in_comment_does_not_break_parity(self):
        code = "# don't call Year( ) here\nDimensionCreate( 'X' );"
        assert validate_code(code, context="TI", version="v12") == []

    def test_paired_hash_strings_do_not_blank_code_between(self):
        code = "a = '#';\nb = '#';\nc = DB( 'x' );"
        assert any(i["function"] == "DB" for i in validate_code(code, context="TI"))

    def test_concatenated_hash_label_keeps_real_call_visible(self):
        code = "sMsg = 'Loading batch #' | NumberToString( nBatch );\nSaveDataAll();"
        issues = validate_code(code, context="TI", version="v12")
        assert [i["function"] for i in issues] == ["SaveDataAll"]


class TestVersionValidation:
    """Regression: an unrecognised version matched no function's version list
    and therefore flagged every documented call in the file."""

    @pytest.mark.parametrize("bad", ["12", "V12", "v13", "2.0", ""])
    def test_non_canonical_version_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_code("DimensionCreate( 'X' );", context="TI", version=bad)

    def test_canonical_versions_accepted(self):
        for good in ("v11", "v12"):
            validate_code("DimensionCreate( 'X' );", context="TI", version=good)


class TestDataCorrections:
    """Regression: rows whose context tags contradicted their own family and
    so produced false positives on ordinary code."""

    def test_year_valid_in_rules(self):
        assert validate_code("['x'] = N: YEAR( sDate );", context="Rules") == []

    def test_fill_valid_in_ti(self):
        assert validate_code("sPad = FILL( '-', 10 );", context="TI") == []

    def test_dfrst_valid_in_ti_and_rules(self):
        assert validate_code("sEl = DFRST( 'Region' );", context="TI") == []
        assert validate_code("['x'] = S: DFRST( 'Region' );", context="Rules") == []

    def test_descriptions_have_no_nbsp(self):
        from src.tm1.functions import _library

        assert not [f.name for f in _library().values() if " " in f.description]


class TestUnknownFunctionWarnings:
    """Invented function names are the complaint TM1 developers actually have.
    TI drafts are compiled against the server, which rejects them; rules and
    feeders have no compile step, so this is their only pre-execution check."""

    def test_off_by_default(self):
        code = "sX = SomeInventedFunction( 1 );"
        assert validate_code(code, context="Rules") == []

    def test_unknown_reported_as_warning_not_error(self):
        code = "['x'] = N: TotallyMadeUpFunction( 1 );"
        issues = validate_code(code, context="Rules", report_unknown=True)
        assert len(issues) == 1
        assert issues[0]["kind"] == "unknown"
        assert issues[0]["severity"] == "warning"
        assert issues[0]["function"] == "TotallyMadeUpFunction"

    def test_known_functions_never_warned(self):
        code = "['x'] = N: DB( 'C', !d ) * ABS( ['y'] );"
        issues = validate_code(code, context="Rules", report_unknown=True)
        assert [i for i in issues if i["kind"] == "unknown"] == []

    def test_language_keywords_are_not_unknown_functions(self):
        # ELSEIF( is ordinary TI syntax and is absent from the function
        # library — without the keyword guard it warns on valid code.
        code = """
IF( nX = 1 );
   a = 1;
ELSEIF( nX = 2 );
   b = 2;
ELSE;
   c = 3;
ENDIF;
WHILE( nY > 0 );
   nY = nY - 1;
END;
"""
        assert validate_code(code, context="TI", report_unknown=True) == []

    def test_real_ti_process_has_no_unknown_warnings(self):
        assert validate_code(VALID_TI, context="TI", report_unknown=True) == []

    def test_real_rules_have_no_unknown_warnings(self):
        assert validate_code(VALID_RULES, context="Rules", report_unknown=True) == []

    def test_unknowns_deduped(self):
        code = "a = MadeUp( 1 );\nb = MadeUp( 2 );\nc = MadeUp( 3 );"
        issues = validate_code(code, context="Rules", report_unknown=True)
        assert len(issues) == 1

    def test_errors_and_warnings_coexist(self):
        code = "a = MadeUpFn( 1 );\nb = DimensionElementInsert( 'D', '', 'E', 'N' );"
        issues = validate_code(code, context="Rules", report_unknown=True)
        kinds = {i["kind"] for i in issues}
        assert kinds == {"unknown", "context"}
        assert {i["severity"] for i in issues} == {"warning", "error"}

    def test_process_validation_passes_flag_through(self):
        sections = {"prolog": "x = MadeUpFn( 1 );"}
        assert validate_process(sections) == []
        issues = validate_process(sections, report_unknown=True)
        assert issues and issues[0]["kind"] == "unknown"
        assert issues[0]["section"] == "prolog"


class TestEdgeCases:

    def test_empty_input(self):
        assert validate_code("", context="TI", version="v12") == []
        assert find_calls("") == []

    def test_invalid_context_rejected(self):
        with pytest.raises(ValueError):
            validate_code("x", context="NotAContext")

    def test_unterminated_string_does_not_crash(self):
        validate_code("sX = 'unterminated;\nDimensionCreate( 'Y' );", context="TI")

    def test_crlf_line_endings(self):
        code = "DimensionCreate( 'X' );\r\n\r\nSaveDataAll();"
        issues = validate_code(code, context="TI", version="v12")
        assert issues and issues[0]["line"] == 3


# ---------------------------------------------------------------------------
# Data integrity. The library is scraped from a third-party reference, and a
# refresh from a worse export would silently break validation for every
# process. These pin the facts that matter.
# ---------------------------------------------------------------------------


def test_if_and_while_stay_valid_in_ti():
    """A cleaner-looking export of the same source tags IF as Rules-only.

    Regenerating from it would flag every IF( in every TI process. This test
    is the tripwire: a bad refresh fails here rather than in production.
    """

    assert tm1_functions.lookup("IF").supports_context("TI")
    assert tm1_functions.lookup("IF").supports_context("Rules")
    assert tm1_functions.lookup("While").supports_context("TI")


def test_dimension_functions_keep_all_three_contexts():
    for name in ("DIMIX", "DIMNM", "DIMSIZ"):
        function = tm1_functions.lookup(name)
        assert function.supports_context("TI"), name
        assert function.supports_context("Rules"), name
        assert function.supports_context("Excel"), name


def test_version_data_survives_a_refresh():
    # A version-less export would make every version check pass silently.
    assert tm1_functions.lookup("ExecuteCommand").versions == ("v11",)
    assert tm1_functions.lookup("ExecuteHttpRequest").versions == ("v12",)


def test_corrected_descriptions_are_served_not_the_upstream_text():
    put_n = tm1_functions.lookup("HierarchyAttrPutN").description
    put_s = tm1_functions.lookup("HierarchyAttrPutS").description

    # Upstream has these two swapped.
    assert "numeric" in put_n and "string" not in put_n
    assert "string" in put_s and "numeric" not in put_s

    # Upstream prepends ABS's description to LN's.
    assert "absolute value" not in tm1_functions.lookup("LN").description

    # Upstream says the Put function reads "from" an attribute.
    assert tm1_functions.lookup("ElementAttrPutS").description.startswith(
        "Uploads data to"
    )


def test_no_description_is_empty_or_mojibaked():
    for function in tm1_functions._library().values():
        assert function.description, function.name
        assert "Â" not in function.description, function.name
        assert "â" not in function.description, function.name


# ---------------------------------------------------------------------------
# Parenthesis-less statement calls.
# ---------------------------------------------------------------------------


def test_bare_statement_call_is_detected():
    assert tm1_functions.find_calls("SaveDataAll;") == [("SaveDataAll", 1)]


def test_bare_statement_v11_function_is_flagged_on_v12():
    issues = tm1_functions.validate_code(
        "SaveDataAll;", context="TI", version="v12"
    )

    assert [i["function"] for i in issues] == ["SaveDataAll"]
    assert issues[0]["kind"] == "version"


def test_right_hand_side_read_is_not_a_call():
    # Reading a datasource global is not an invocation.
    assert tm1_functions.find_calls("sChar = DatasourceASCIIDelimiter;") == []


def test_language_keywords_are_not_statement_calls():
    assert tm1_functions.find_calls("ELSE;\nENDIF;\nEND;\nBreak;") == []


def test_unknown_bare_identifier_is_not_a_call():
    # A variable named like nothing in the library must not be reported.
    assert tm1_functions.find_calls("nSomeLocalCounter;") == []


def test_function_name_in_a_comment_or_string_is_still_ignored():
    assert tm1_functions.find_calls("# SaveDataAll;") == []
    assert tm1_functions.find_calls("sMsg = 'SaveDataAll;';") == []


def test_context_error_uses_the_right_article():
    message = tm1_functions.validate_code(
        "n = DBRW('a', 'b');", context="TI"
    )[0]["message"]

    assert "it is an Excel function" in message


def test_a_real_process_produces_no_findings():
    # Excerpted from a live customer process — the false-positive guard.
    code = """
    sCube = 'Process Stats';
    sNow = TIMST( NOW, 'x' );
    CurrLine = CELLGETS ( sCube , 'All Index' , sDate , sProcess , 'x' );
    IF( SUBST( TM1USER(), 1, 2 ) @= 'R*' );
      sUser = '*CHORE*';
    ELSE;
      sUser = ATTRS( '}Clients', TM1USER(), 'x' );
    ENDIF;
    vSize = DIMSIZ( vDim );
    WHILE( vSize > 0 );
        vElement = DIMNM( vDim, vSize );
        IF( ELLEV( vDim, vElement ) = 0 );
            SUBSETELEMENTINSERT( vDim, vSubset, vElement, 0 );
        ENDIF;
        vSize = vSize - 1;
    END;
    VIEWZEROOUT( vTargetCube, vView );
    CELLINCREMENTN( dValue, vTargetCube, dVersion, dPeriod );
    ItemSkip;
    """

    assert tm1_functions.validate_code(code, context="TI", version="v11") == []
