"""The memo generator's guard against invented numbers: write_memo and main with a fake Anthropic client."""

import json
import sys
from types import SimpleNamespace

import pytest

from fintwin import memo

SHEET = {"revenue": 1000}


def _reply(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details="policy",
        content=[SimpleNamespace(type="text", text=text)],
        model="fake-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeClient:
    def __init__(self, texts):
        self.texts, self.prompts = list(texts), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return _reply(self.texts.pop(0))


def _memo(summary: str) -> str:
    return json.dumps({"verdict": "Watch", "summary": summary})


@pytest.fixture
def data(tmp_path, monkeypatch):
    (tmp_path / "companies").mkdir()
    (tmp_path / "companies" / "TST.json").write_text(json.dumps({"params": {"last_quarter": "2025-12-31"}}))
    (tmp_path / "index.json").write_text(json.dumps({"meta": {}}))
    monkeypatch.setattr(memo, "DATA", tmp_path)
    monkeypatch.setattr(memo, "fact_sheet", lambda c, meta: SHEET)

    def generate(*texts):
        client = FakeClient(texts)
        monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda: client))  # not installed here
        memo.main(["TST"])
        return client, json.loads((tmp_path / "memos" / "TST.json").read_text())

    return generate


def test_a_clean_memo_is_accepted_on_the_first_call(data):
    client, out = data(_memo("revenue 1000"))
    assert len(client.prompts) == 1 and out["attempts"] == 1 and out["unverified_numbers"] == []


def test_an_invented_number_triggers_one_retry_with_feedback(data):
    client, out = data(_memo("revenue 777"), _memo("revenue 1000"))
    assert len(client.prompts) == 2
    assert "previous draft" not in client.prompts[0] and "777" in client.prompts[1]
    assert out["attempts"] == 2 and out["unverified_numbers"] == [] and out["summary"] == "revenue 1000"


def test_a_memo_that_is_still_wrong_after_the_retry_is_recorded_as_unverified(data):
    client, out = data(_memo("revenue 777"), _memo("revenue 888"))
    assert len(client.prompts) == 2  # no third attempt
    assert out["attempts"] == 2 and out["unverified_numbers"] == [888.0]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_write_memo_raises_on_refusal_and_truncation(stop):
    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: _reply("{}", stop_reason=stop)))
    )
    with pytest.raises(RuntimeError):
        memo.write_memo(client, SHEET)
