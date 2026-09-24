from src.tm1.rules.analysis import analyze_rules, trace_cell
from src.tm1.rules.parser import parse_rules


def codes(report) -> list[str]:
    return [f["code"] for f in report["findings"]]


# ------------------------------------------------------------------ parser


def test_parse_reads_directives_and_sections():
    parsed = parse_rules(
        """
        SKIPCHECK;
        FEEDSTRINGS;
        ['Margin'] = N: ['Revenue'] - ['Cost'];
        FEEDERS;
        ['Revenue'] => ['Margin'];
        """
    )

    assert parsed.skipcheck is True
    assert parsed.feedstrings is True
    assert parsed.has_feeders_section is True
    assert len(parsed.calculations) == 1
    assert len(parsed.feeders) == 1
    assert parsed.calculations[0].elements == ["Margin"]
    assert parsed.calculations[0].qualifier == "N"
    assert parsed.feeders[0].target_elements == ["Margin"]


def test_parse_ignores_comments_but_keeps_line_numbers():
    parsed = parse_rules(
        "\n".join(
            [
                "# line 1 comment",
                "SKIPCHECK;",
                "# another comment",
                "['Margin'] = N: 1;",
            ]
        )
    )

    assert parsed.calculations[0].line_number == 4


def test_parse_handles_semicolon_inside_a_string():
    parsed = parse_rules("['Note'] = S: 'a;b';")

    assert len(parsed.calculations) == 1
    assert parsed.calculations[0].qualifier == "S"


def test_parse_handles_a_statement_spanning_lines():
    parsed = parse_rules(
        "['Margin'] = N:\n    ['Revenue']\n    - ['Cost'];"
    )

    assert len(parsed.calculations) == 1
    assert "Revenue" in parsed.calculations[0].expression


def test_parse_marks_unresolvable_feeder_targets():
    parsed = parse_rules(
        """
        SKIPCHECK;
        ['Margin'] = N: 1;
        FEEDERS;
        ['Revenue'] => DB('Other', !Month);
        """
    )

    assert parsed.feeders[0].resolvable is False
    assert parsed.feeders[0].target_elements == []


def test_parse_empty_rules_is_safe():
    for value in (None, "", "   \n  "):
        parsed = parse_rules(value)
        assert parsed.calculations == []
        assert parsed.skipcheck is False


# ---------------------------------------------------------------- analysis


def test_detects_unfed_calculation_under_skipcheck():
    # The classic defect: leaf values correct, every total zero.
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Gross Margin'] = N: ['Revenue'] - ['COGS'];
        FEEDERS;
        ['Revenue'] => ['Margin %'];
        """
    )

    assert "unfed_calculation" in codes(report)
    finding = next(
        f for f in report["findings"] if f["code"] == "unfed_calculation"
    )
    assert finding["severity"] == "critical"
    assert "Gross Margin" in finding["message"]


def test_fed_calculation_produces_no_unfed_finding():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Gross Margin'] = N: ['Revenue'] - ['COGS'];
        FEEDERS;
        ['Revenue'] => ['Gross Margin'];
        """
    )

    assert "unfed_calculation" not in codes(report)
    assert report["summary"]["critical"] == 0


def test_skipcheck_with_no_feeders_section_is_critical():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Margin'] = N: ['Revenue'] - ['Cost'];
        """
    )

    assert "skipcheck_without_feeders" in codes(report)
    # The per-statement check stays quiet; one clear finding, not N.
    assert "unfed_calculation" not in codes(report)


def test_feeders_without_skipcheck_is_a_warning():
    report = analyze_rules(
        """
        ['Margin'] = N: ['Revenue'] - ['Cost'];
        FEEDERS;
        ['Revenue'] => ['Margin'];
        """
    )

    assert "feeders_without_skipcheck" in codes(report)


def test_unresolvable_feeders_downgrade_unfed_to_warning():
    # We cannot see through DB(), so we must not claim certainty.
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Margin'] = N: 1;
        FEEDERS;
        ['Revenue'] => DB('Other', !Month);
        """
    )

    finding = next(
        f for f in report["findings"] if f["code"] == "unfed_calculation"
    )
    assert finding["severity"] == "warning"
    assert "could not be resolved" in finding["message"]
    assert report["summary"]["analysis_is_partial"] is True


def test_detects_calculation_stranded_below_feeders():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['A'] = N: 1;
        FEEDERS;
        ['A'] => ['A'];
        ['B'] = N: 2;
        """
    )

    finding = next(
        f for f in report["findings"] if f["code"] == "calculation_below_feeders"
    )
    assert finding["severity"] == "critical"
    assert "['B']" in finding["statement"]


def test_detects_shadowed_area():
    report = analyze_rules(
        """
        ['Margin'] = N: 1;
        ['Margin'] = N: 2;
        """
    )

    finding = next(f for f in report["findings"] if f["code"] == "shadowed_area")
    assert "never runs" in finding["message"]


def test_detects_feeder_to_uncalculated_area():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Margin'] = N: 1;
        FEEDERS;
        ['Margin'] => ['Nothing Here'];
        """
    )

    assert "feeder_to_uncalculated_area" in codes(report)


def test_string_rule_without_feedstrings_is_reported():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['Label'] = S: 'x';
        FEEDERS;
        ['Label'] => ['Label'];
        """
    )

    assert "string_rules_without_feedstrings" in codes(report)


def test_findings_are_ordered_by_severity():
    report = analyze_rules(
        """
        SKIPCHECK;
        ['A'] = N: 1;
        ['A'] = N: 2;
        FEEDERS;
        ['A'] => ['Missing'];
        """
    )

    severities = [f["severity"] for f in report["findings"]]
    assert severities == sorted(
        severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s]
    )


def test_clean_rules_produce_no_findings():
    report = analyze_rules(
        """
        SKIPCHECK;
        FEEDSTRINGS;
        ['Gross Margin'] = N: ['Revenue'] - ['COGS'];
        FEEDERS;
        ['Revenue'] => ['Gross Margin'];
        """
    )

    assert report["findings"] == []
    assert report["summary"]["calculation_count"] == 1


# ------------------------------------------------------------------- trace


def test_trace_finds_applied_statement_and_missing_feed():
    result = trace_cell(
        """
        SKIPCHECK;
        ['Gross Margin'] = N: ['Revenue'] - ['COGS'];
        FEEDERS;
        ['Revenue'] => ['Other'];
        """,
        ["Gross Margin", "EMEA", "Jan"],
    )

    assert result["calculated"] is True
    assert result["is_fed"] is False
    assert "read zero" in result["warning"]
    assert result["applied_statement"]["qualifier"] == "N"


def test_trace_reports_when_no_rule_applies():
    result = trace_cell("['Margin'] = N: 1;", ["Revenue", "EMEA"])

    assert result["calculated"] is False
    assert "stored data" in result["message"]


def test_trace_reports_shadowing_statements():
    result = trace_cell(
        "['Margin'] = N: 1;\n['Margin'] = N: 2;",
        ["Margin", "Jan"],
    )

    assert result["applied_statement"]["line_number"] == 1
    assert len(result["also_matched"]) == 1


def test_trace_requires_every_area_element_to_be_present():
    # ['Margin','Actual'] must not match a cell that is only 'Margin'.
    rules = "['Margin','Actual'] = N: 1;"

    assert trace_cell(rules, ["Margin", "Jan"])["calculated"] is False
    assert trace_cell(rules, ["Margin", "Actual", "Jan"])["calculated"] is True


def test_trace_is_case_insensitive():
    result = trace_cell("['Margin'] = N: 1;", ["margin", "jan"])

    assert result["calculated"] is True
