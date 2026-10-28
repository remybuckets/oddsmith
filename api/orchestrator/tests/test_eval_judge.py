import json
from datetime import UTC, datetime
from types import SimpleNamespace

from orchestrator.eval.judge import judge_finding, judged
from orchestrator.tests.test_eval_figures import ODDS_CALL

NOW = datetime(2026, 10, 10, 19, 0, tzinfo=UTC)
RECORD = {
    "id": "o01",
    "question": "Best price on Liverpool?",
    "history": [{"role": "user", "content": "Who do Liverpool play?"}],
    "text": "Liverpool are 2.45 with 888sport.",
    "tool_calls": [
        {**ODDS_CALL, "skipped": False},
        {"name": "get_odds", "input": {}, "result": {"ok": False}, "skipped": True},
    ],
}


class FakeClient:
    """Stands in for AsyncAnthropic: returns one canned reply and keeps the request."""

    def __init__(self, claims=None, stop_reason="end_turn", error=None):
        self._reply = SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps({"claims": claims or []}))],
        )
        self._error = error
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **request):
        self.requests.append(request)
        if self._error:
            raise self._error
        return self._reply


def claim(verdict):
    return {"claim": "Liverpool 2.45", "verdict": verdict, "reason": "best_price 2.45"}


def test_wrong_and_unsupported_claims_fail_the_judge_check():
    assert judge_finding([claim("supported"), claim("derived")]).ok
    assert not judge_finding([claim("supported"), claim("wrong")]).ok
    assert "unsupported: Liverpool 2.45" in judge_finding([claim("unsupported")]).detail


async def test_the_judge_reads_the_answer_against_what_claude_was_shown():
    client = FakeClient([claim("supported")])

    claims, finding = await judged(client, "claude-opus-5-5", RECORD, NOW)

    assert finding.ok and claims == [claim("supported")]
    (request,) = client.requests
    prompt = request["messages"][0]["content"]
    assert request["model"] == "claude-opus-5-5"
    assert "Liverpool are 2.45 with 888sport." in prompt
    assert "Sun 11 Oct 2026, 16:30" in prompt  # kick-off in UK time, as Claude saw it
    assert "2026-10-11T15:30:00Z" not in prompt
    assert "Who do Liverpool play?" in prompt
    assert prompt.count('"tool": "get_odds"') == 1  # the skipped call is left out


async def test_a_judge_that_cannot_answer_is_a_failed_check_not_a_pass():
    refused = FakeClient(stop_reason="refusal")
    broken = FakeClient(error=ValueError("bad reply"))

    for client in (refused, broken):
        claims, finding = await judged(client, "claude-opus-5-5", RECORD, NOW)
        assert claims == []
        assert not finding.ok
        assert "judge call failed" in finding.detail


async def test_an_empty_answer_is_not_sent_to_the_judge():
    client = FakeClient()

    _, finding = await judged(client, "claude-opus-5-5", {**RECORD, "text": ""}, NOW)

    assert finding.ok
    assert client.requests == []


def test_judge_takes_premier_league_coverage_as_a_product_fact():
    # Run 3 false alarm (g06): "two Premier League meetings" was marked unsupported because
    # the results don't name the competition; every match in the data is Premier League.
    from orchestrator.eval.judge import INSTRUCTIONS

    facts = INSTRUCTIONS.split("fixed facts about the product")[1].split("\n- ")[0]
    assert "every match in the data being Premier League" in " ".join(facts.split())


def test_judge_knows_stats_are_stale_only_when_a_result_is_missing():
    from orchestrator.eval.judge import INSTRUCTIONS

    facts = " ".join(INSTRUCTIONS.split())
    assert "stats 48h" not in facts
    assert "stats when a result is still missing 3h after kick-off" in facts
