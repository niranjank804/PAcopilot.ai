from src.tm1.deployment import ti_analysis


def test_clean_process_has_no_errors():
    content = {
        "prolog": (
            "sCube = 'Sales';\n"
            "nCount = 0;\n"
            "sMessage = 'Loading ' | sCube;\n"
        ),
        "epilog": "LogOutput('INFO', sMessage);",
    }

    assert ti_analysis.analyze(content) == []


def test_assigned_variable_used_with_different_case_is_reported():
    content = {
        "prolog": "sCubeName = 'Sales';",
        "data": "CellPutN(1, sCubename, 'Actual');",
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    assert "sCubeName" in errors[0]
    assert "sCubename" in errors[0]


def test_declared_parameter_case_mismatch_names_the_declaration():
    content = {
        "parameters": [{"name": "pSourceFile", "type": "String"}],
        "prolog": "sPath = psourcefile;",
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    # The declared spelling is the one the author should converge on.
    assert "Use 'pSourceFile' everywhere" in errors[0]


def test_mixed_case_function_names_are_not_reported():
    # TI function names are case-insensitive and real code mixes them
    # freely; only names the process declares or assigns are variables.
    content = {
        "prolog": "nValue = CellGetN('Sales', 'A');",
        "data": "nValue = cellgetn('Sales', 'B');",
    }

    assert ti_analysis.analyze(content) == []


def test_identifiers_inside_string_literals_are_ignored():
    content = {
        "prolog": "sName = 'sname SNAME Sname';",
    }

    assert ti_analysis.analyze(content) == []


def test_escaped_quote_inside_string_does_not_leak_identifiers():
    content = {
        "prolog": "sMsg = 'it''s sMSG here';",
        "epilog": "LogOutput('INFO', sMsg);",
    }

    assert ti_analysis.analyze(content) == []


def test_commented_out_code_is_ignored():
    content = {
        "prolog": "sCube = 'Sales';\n# sCUBE = 'Old';",
    }

    assert ti_analysis.analyze(content) == []


def test_hash_inside_string_does_not_start_a_comment():
    content = {
        "prolog": "sTag = '# not a comment';\nnCount = 0;\nnCOUNT = 1;",
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    assert "nCount" in errors[0]


def test_source_columns_without_declared_variables_are_reported():
    content = {"data": "sAccount = v1;\nnAmount = v2;"}

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    assert "v1, v2" in errors[0]
    assert "ASCII" in errors[0]


def test_source_columns_are_clean_once_declared():
    content = {
        "variables": [
            {"name": "v1", "type": "String"},
            {"name": "v2", "type": "Numeric"},
        ],
        "data": "sAccount = v1;\nnAmount = v2;",
    }

    assert ti_analysis.analyze(content) == []


def test_source_column_not_among_declared_variables_is_reported():
    content = {
        "variables": [{"name": "v1", "type": "String"}],
        "data": "sAccount = v1;\nnAmount = v7;",
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    assert "v7" in errors[0]


def test_empty_content_is_clean():
    assert ti_analysis.analyze(None) == []
    assert ti_analysis.analyze({}) == []


def test_invented_datasource_variables_are_reported():
    # The real defect: the agent named source columns after the dimensions
    # they feed, but TI only creates the columns declared in `variables`.
    content = {
        "variables": [
            {"name": "v1", "type": "String"},
            {"name": "v2", "type": "Numeric"},
        ],
        "data": (
            "sOrg = Organization;\n"
            "sYear = Years;\n"
            "nAmount = vCashFlow_Direct_Method_;\n"
        ),
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 1
    assert "Data reads undefined name(s)" in errors[0]
    for name in ("Organization", "Years", "vCashFlow_Direct_Method_"):
        assert name in errors[0]


def test_function_calls_are_never_undefined():
    content = {
        "prolog": (
            "nIndex = DimensionElementCount('Region');\n"
            "sName = SUBST(ATTRS('Region', 'US', 'Caption'), 1, 3);\n"
            "IF(nIndex > 0);\n"
            "ItemSkip;\n"
            "ENDIF;\n"
        ),
    }

    assert ti_analysis.analyze(content) == []


def test_reserved_datasource_globals_are_allowed():
    content = {
        "prolog": (
            "DatasourceNameForServer = 'C:\\data.csv';\n"
            "sCheck = DatasourceASCIIDelimiter;\n"
        ),
        "data": "nValue = NValue;\nsText = SValue;",
    }

    assert ti_analysis.analyze(content) == []


def test_parameters_and_locals_resolve():
    content = {
        "parameters": [{"name": "pSourceFile", "type": "String"}],
        "prolog": "sPath = pSourceFile;\nnCount = 0;",
        "epilog": "LogOutput('INFO', sPath);\nnTotal = nCount;",
    }

    assert ti_analysis.analyze(content) == []


def test_forward_reference_is_not_a_false_positive():
    # Assigned in the Epilog, read in the Prolog. Order-sensitivity here
    # would block a legitimate draft.
    content = {
        "prolog": "nSeen = nTotal;",
        "epilog": "nTotal = 5;",
    }

    assert ti_analysis.analyze(content) == []


def test_undefined_names_reported_per_tab():
    content = {
        "metadata": "sA = Alpha;",
        "data": "sB = Beta;",
    }

    errors = ti_analysis.analyze(content)

    assert len(errors) == 2
    assert any("Metadata reads" in e and "Alpha" in e for e in errors)
    assert any("Data reads" in e and "Beta" in e for e in errors)


def test_cube_view_datasource_variables_are_not_reported_as_undefined():
    # A view datasource generates one variable per dimension plus dValue.
    # None of them can appear in `variables`, so checking against that list
    # would block every legitimate view-driven process.
    content = {
        "data": (
            "IF(dAmountClass @= 'B200');\n"
            "  ITEMSKIP;\n"
            "ENDIF;\n"
            "CELLINCREMENTN(dValue, vCube, dVersion, dPeriod, dEntity);"
        ),
        "prolog": "vCube = 'Allocation BOBID';",
    }

    assert ti_analysis.analyze(content, datasource_type="View") == []


def test_server_side_datasource_is_used_when_the_draft_omits_one():
    content = {"data": "sOrg = dEntity;"}

    # An update that leaves the datasource alone still has to be analysed
    # against the datasource the process actually runs on.
    assert ti_analysis.analyze(content, datasource_type="View") == []
    assert ti_analysis.analyze(content, datasource_type="None") != []


def test_casing_is_still_checked_on_a_view_datasource():
    content = {
        "prolog": "sCubeName = 'Sales';",
        "data": "CellPutN(dValue, sCubename, dEntity);",
    }

    errors = ti_analysis.analyze(content, datasource_type="View")

    assert len(errors) == 1
    assert "sCubeName" in errors[0]


def test_ascii_datasource_still_catches_invented_source_variables():
    content = {
        "datasource_type": "ASCII",
        "variables": [{"name": "v1", "type": "String"}],
        "data": "sOrg = Organization;",
    }

    errors = ti_analysis.analyze(content, datasource_type="View")

    # The draft's own datasource wins over the server's.
    assert len(errors) == 1
    assert "Organization" in errors[0]
