"""Claim-level faithfulness check (app/guardrails/verify.py) with a scripted judge."""

import asyncio
import re

from app.guardrails.verify import carried_figures, statements, verify_answer
from app.llm.base import LLMError, LLMProvider, StreamEvent, Usage

SOURCES = [
    {"n": 1, "page": 11, "text": "Should the Policy Owner be made redundant, premiums can be suspended for 365 days."},
    {
        "n": 2,
        "page": 14,
        "text": "If no premiums are paid before the end of the 31-day Grace Period, the Policy will lapse.",
    },
]
ANSWER = (
    "You can suspend premiums for up to 365 days [1].\n\n"
    "- **Lapse:** If you do not pay after the 365-day period ends, the policy terminates [2].\n"
    "- The normal Grace Period is 31 days [2]."
)


class Judge(LLMProvider):
    provider, model, router_model = "fake", "fake", "fake"

    def __init__(self, unsupported=(), fail=False):
        self.unsupported, self.fail, self.prompts = set(unsupported), fail, []

    async def complete_json(self, system, messages, schema, *, max_tokens=1024):
        self.prompts.append(messages[-1]["content"])
        if self.fail:
            raise LLMError("RateLimitError: 429")
        ids = re.findall(r"^### (S\d+)$", messages[-1]["content"], re.M)
        return {"verdicts": [{"id": i, "supported": i not in self.unsupported, "reason": "r"} for i in ids]}, Usage(
            9, 3
        )

    async def stream(self, system, messages):
        yield StreamEvent(done=True)


def test_statements_are_cited_sentences_and_bullets():
    st = statements(ANSWER + "\n\nThis plan is long-term. 本计划只可行使两次 [1]。另外费用为 5% [2]。")
    assert [s.cites for s in st] == [[1], [2], [2], [1], [2]]
    assert st[1].text.startswith("- **Lapse:**") and st[3].text == "本计划只可行使两次 [1]。"


def test_figure_carried_over_from_another_passage_is_caught_without_the_judge():
    st = statements(ANSWER)
    assert carried_figures(st[1], SOURCES) == ["365"]  # 365 is on page 11; the statement cites page 14
    assert carried_figures(st[0], SOURCES) == [] and carried_figures(st[2], SOURCES) == []
    assert carried_figures(st[1], SOURCES, allowed_text="What if I stop paying after 365 days?") == []
    r = asyncio.run(verify_answer(Judge(), ANSWER, SOURCES))  # the judge passes everything
    assert r.removed == [st[1].text]
    assert "terminates" not in r.text and "31 days [2]" in r.text and "**Lapse:**" not in r.text


def test_judge_sees_each_statement_with_only_its_own_passages():
    answer = "Premiums can be suspended [1]. The policy lapses without payment [2]."
    judge = Judge(unsupported={"S2"})
    r = asyncio.run(verify_answer(judge, answer, SOURCES))
    s1, s2 = judge.prompts[0].split("### S2")
    assert "page 11" in s1 and "page 14" not in s1 and "page 14" in s2 and "page 11" not in s2
    assert r.text == "Premiums can be suspended [1]."


def test_judge_that_rejects_most_statements_is_outvoted():
    r = asyncio.run(verify_answer(Judge(unsupported={"S1", "S3"}), ANSWER, SOURCES))
    assert r.text == ANSWER and not r.removed and len(r.kept_disputed) == 3


def test_judge_failure_keeps_the_answer():
    answer = "You can suspend premiums for up to 365 days [1]. The Grace Period is 31 days [2]."
    r = asyncio.run(verify_answer(Judge(fail=True), answer, SOURCES))
    assert r.text == answer and r.error == "LLMError"


def test_answer_without_citations_is_not_sent_to_the_judge():
    judge = Judge()
    r = asyncio.run(verify_answer(judge, "Hello! Ask me about the plan.", SOURCES))
    assert r.checked == 0 and judge.prompts == []
