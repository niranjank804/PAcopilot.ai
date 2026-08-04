"""The gate must reject the junk that was actually uploaded, and nothing else.

The samples below are shortened from a real scraped IBM Docs corpus that
reported "completed" on upload while containing no reference content at
all.
"""

import pytest

from src.knowledge import quality

# A scraped IBM Docs table of contents: link text alternating with URLs.
SCRAPED_TOC = "\n".join(
    line
    for topic, slug in [
        ("Introduction", "excel-introduction"),
        ("What's new in Planning Analytics", "excel-whats-new"),
        ("Planning Analytics Trial", "excel-planning-analytics-trial"),
        ("Getting started", "excel-getting-started"),
        ("Connecting to datasources", "excel-connecting-datasources"),
        ("Settings", "excel-settings"),
        ("Work with data and reports", "excel-work-data-reports"),
        ("Explore TM1 data", "excel-explore-tm1-data"),
        ("Cube Viewer", "excel-cube-viewer"),
        ("Action buttons", "excel-action-buttons"),
        ("Troubleshoot", "pame-troubleshoot"),
        ("Accessibility features", "excel-accessibility-features"),
    ]
    for line in (
        topic,
        f"https://www.ibm.com/docs/en/planning-analytics/2.0.0?topic={slug}",
    )
)

# Page furniture: CSS class names, enumerated footer slots, nav chrome.
SCRAPED_CHROME = "\n".join(
    ["cds--link", "cds--link href", "cds--label", "topictitle1", "shortdesc"]
    + [f"ibmdocs-dotcom-footer {n}" for n in range(1, 30)]
    + ["navigation", "All products", "Change version", "Close", "Cancel"]
)

# A real reference page: mostly prose, few URLs, no repetition.
GOOD_REFERENCE = """SUBST

Purpose: SUBST returns a substring of a specified string value.

Syntax: SUBST(string, beginning, length)

Arguments:
string is the source from which the substring is extracted.
beginning is the position of the first character of the substring.
length is the number of characters to return from the source string.

Example: SUBST('Current Month', 9, 5) returns the value 'Month'.

Notes: The first character of a string sits at position 1, not position 0.
If beginning exceeds the length of string, an empty string is returned.
If length runs past the end of string, the remainder is returned instead.
See also SCAN, which locates a substring within a larger string value.
"""


def test_scraped_table_of_contents_is_rejected():
    problems = quality.assess(SCRAPED_TOC)

    assert problems
    assert any("bare URLs" in p for p in problems)


def test_page_furniture_is_rejected():
    problems = quality.assess(SCRAPED_CHROME)

    assert problems
    assert any("prose" in p or "repetition" in p for p in problems)


def test_mojibake_is_rejected():
    text = GOOD_REFERENCE + "\n" + "\n".join(
        [
            "IBMÂ® CognosÂ® Planning Analytics is a registered product name.",
            "The TM1Â® server exposes a REST API for automation purposes.",
            "Ð ÑÑÑÐºÐ¸Ð¹ and ÎÎ»Î»Î·Î½Î¹ÎºÎ¬ appear in the language selector.",
            "CatalÃ  and TÃ¼rkÃ§e also appear in that same list of options.",
        ]
    )

    problems = quality.assess(text)

    assert any("encoding is damaged" in p for p in problems)


def test_a_real_reference_page_passes():
    assert quality.assess(GOOD_REFERENCE) == []


def test_a_ti_process_passes():
    process = """#Section Prolog
# Set up the source file and temporary objects for this load run.
sCube = 'Sales';
sTempView = 'zTmp_' | sCube;
nRecords = 0;

#Section Data
# Reject rows whose account is not present in the Account dimension.
IF(DIMIX('Account', v1) = 0);
  ITEMSKIP;
ENDIF;
CELLPUTN(v3, sCube, v1, v2);

#Section Epilog
# Report how many rows were loaded, then clean up the temporary view.
LogOutput('INFO', 'Loaded rows into the target cube successfully.');
IF(ViewExists(sCube, sTempView) = 1);
  ViewDestroy(sCube, sTempView);
ENDIF;
"""

    assert quality.assess(process) == []


def test_short_documents_are_never_judged():
    # Four lines is not enough to compute a meaningful ratio, and a short
    # document is not a junk document.
    assert quality.assess("Naming standard\nhttps://example.com/a\nhttps://example.com/b") == []


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_input_is_not_a_quality_problem(text):
    # Empty extraction is caught downstream with its own message.
    assert quality.assess(text) == []
