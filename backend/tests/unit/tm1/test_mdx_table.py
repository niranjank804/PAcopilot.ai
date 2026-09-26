"""MDX results as a table: unique names parsed, dimensions kept apart."""

from src.tm1.services.mdx_table import flat_cells, parse_unique_name, to_table


def test_unique_names_in_every_form():
    assert parse_unique_name("[Period].[Period].[Jan]") == ("Period", "Jan")
    assert parse_unique_name("[Period].[Jan]") == ("Period", "Jan")
    # A hierarchy other than the dimension's own is named.
    assert parse_unique_name("[Region].[ByCountry].[France]") == ("Region:ByCountry", "France")
    # "]]" is an escaped "]".
    assert parse_unique_name("[Account].[Account].[Other [a]]]") == ("Account", "Other [a]")
    # Anything unparseable is kept whole rather than lost.
    assert parse_unique_name("Jan") == ("", "Jan")


def test_rows_keep_each_dimension():
    table = to_table(
        {
            ("[Period].[Jan]", "[Version].[Actual]"): {"Value": 10.0},
            ("[Period].[Feb]", "[Version].[Actual]"): {"Value": None},
        }
    )

    assert table["dimensions"] == ["Period", "Version"]
    assert table["rows"][0] == {"members": {"Period": "Jan", "Version": "Actual"}, "value": 10.0}
    assert table["rows"][1]["value"] is None
    assert table["truncated"] is False


def test_the_cap_is_reported():
    cellset = {(f"[Period].[P{i}]",): {"Value": i} for i in range(5)}

    table = to_table(cellset, limit=3)

    assert len(table["rows"]) == 3
    assert table["truncated"] is True


def test_flat_cells_keep_the_old_shape():
    table = to_table({("[Period].[Jan]", "[Version].[Actual]"): {"Value": 1.0}})

    assert flat_cells(table) == {"Jan|Actual": 1.0}
