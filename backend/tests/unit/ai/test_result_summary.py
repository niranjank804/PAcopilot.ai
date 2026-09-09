"""The tool-result summary shown in the chat timeline.

QA saw `\\u2014` printed where an em dash belonged. Tools serialise with
`json.dumps`, which escapes non-ASCII by default; the model decodes that
without noticing, but the UI showed the first 500 characters of the raw
string. The summary is now re-serialised with escapes off before it is
truncated — and it has to stay valid JSON for short results, because the
chat page parses `draft_change_id` out of it.
"""

import json

from src.ai.orchestrator import _summarise_result


class TestReadableCharacters:

    def test_an_em_dash_is_a_dash_not_an_escape(self):
        raw = json.dumps({"description": "Sales — EMEA"})

        assert "\\u2014" in raw  # what the tool actually produced
        assert "—" in _summarise_result(raw)
        assert "\\u2014" not in _summarise_result(raw)

    def test_other_non_ascii_survives_too(self):
        raw = json.dumps({"cube": "Ventes — région Île-de-France €"})

        summary = _summarise_result(raw)

        assert "Île-de-France €" in summary


class TestStillParseable:

    def test_a_short_result_remains_valid_json(self):
        """The chat page reads draft_change_id out of this field."""

        raw = json.dumps({"draft_change_id": "abc-123", "note": "ok — done"})

        parsed = json.loads(_summarise_result(raw))

        assert parsed["draft_change_id"] == "abc-123"

    def test_truncation_happens_after_decoding(self):
        """Decode first, cut second.

        Cutting the escaped string and then decoding could split a
        `\\uXXXX` sequence in half; decoding first means the 500-character
        window is measured in real characters.
        """

        raw = json.dumps({"text": "— " * 400})

        summary = _summarise_result(raw)

        assert len(summary) == 500
        assert "\\u" not in summary


class TestNonJson:

    def test_plain_text_passes_through(self):
        assert _summarise_result("Process ran — 12 rows.") == "Process ran — 12 rows."

    def test_plain_text_is_still_truncated(self):
        assert len(_summarise_result("x" * 900)) == 500

    def test_the_limit_is_configurable(self):
        assert _summarise_result(json.dumps({"a": "b"}), limit=4) == '{"a"'
