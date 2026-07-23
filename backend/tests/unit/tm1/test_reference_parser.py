from src.tm1.metadata.reference_parser import (
    extract_rule_cube_references,
    extract_ti_cube_writes,
)


def test_rule_db_references_are_extracted():
    rule_text = (
        "['Total'] = N: DB('Expense', !Region, 'Amount') "
        "+ db( 'FX Rates' , !Currency, 'Rate');"
    )

    assert extract_rule_cube_references(rule_text) == {"Expense", "FX Rates"}


def test_rule_without_db_references_returns_empty_set():
    assert extract_rule_cube_references("['Total'] = N: ['A'] + ['B'];") == set()
    assert extract_rule_cube_references("") == set()


def test_ti_cellput_targets_are_extracted():
    code = (
        "CellPutN(1, 'Sales', 'NA', 'Widgets');\n"
        "CELLPUTS('done', 'Status Cube', 'Flag');\n"
        "CellIncrementN(vAmount, 'Expense', vRegion, vAccount);"
    )

    assert extract_ti_cube_writes(code) == {"Sales", "Status Cube", "Expense"}


def test_ti_write_with_nested_call_in_value_argument():
    code = "CellPutN(CellGetN('Source', !Region, 'Amt'), 'Target', !Region, 'Amt');"

    assert extract_ti_cube_writes(code) == {"Target"}


def test_ti_write_with_variable_cube_name_is_ignored():
    code = "CellPutN(1, vCubeName, 'NA', 'Widgets');"

    assert extract_ti_cube_writes(code) == set()


def test_ti_code_without_writes_returns_empty_set():
    assert extract_ti_cube_writes("x = CellGetN('Sales', 'NA');") == set()
    assert extract_ti_cube_writes("") == set()
