"""Offline evaluation of retrieval, guardrails and answers.

    python -m eval.run retrieval             # Hit@k / MRR per language (no API key needed)
    python -m eval.run guardrails            # end-to-end guardrail outcomes (LLM optional)
    python -m eval.run answers               # fact recall + citation accuracy (needs an LLM)
    python -m eval.run all

    # Regression gate (CI): exit 1 if the production configuration drops below thresholds
    python -m eval.run retrieval --min-mrr 0.8 --min-hit 0.95
    python -m eval.run guardrails --min-guardrails 1.0

Uses the same settings as the app (.env), so the numbers describe the
configuration you are running. Reports are written to eval/reports/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from app.chat import ChatService, TurnRequest
from app.config import get_settings
from app.llm import create_llm
from app.rag.retriever import Retriever
from app.store import Store

HERE = Path(__file__).parent
DATASETS = HERE / "datasets"
REPORTS = HERE / "reports"


def load(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# -- retrieval ---------------------------------------------------------------------------
def eval_retrieval(retriever: Retriever, k: int, expand: bool) -> dict:
    rows = []
    for ex in load("retrieval"):
        hits = retriever.search([ex["q"]], k=k, expand=expand)
        pages = [h.chunk.page for h in hits]
        rank = next((i + 1 for i, p in enumerate(pages) if p in ex["pages"]), None)
        rows.append({**ex, "retrieved_pages": pages, "rank": rank})

    def summary(items: list[dict]) -> dict:
        n = len(items)
        return {
            "n": n,
            "hit@1": sum(1 for r in items if r["rank"] == 1) / n,
            "hit@3": sum(1 for r in items if r["rank"] and r["rank"] <= 3) / n,
            f"hit@{k}": sum(1 for r in items if r["rank"]) / n,
            "mrr": sum(1 / r["rank"] for r in items if r["rank"]) / n,
        }

    by_lang = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append(r)
    return {
        "config": {
            "k": k,
            "glossary_expansion": expand,
            "dense": retriever.embedder.name if retriever.embedder else None,
        },
        "overall": summary(rows),
        "by_lang": {lang: summary(items) for lang, items in sorted(by_lang.items())},
        "misses": [
            {"id": r["id"], "q": r["q"], "expected": r["pages"], "got": r["retrieved_pages"]}
            for r in rows
            if not r["rank"]
        ],
    }


def print_retrieval(results: list[dict]) -> None:
    headers = ["config", "lang", "n", "Hit@1", "Hit@3", "Hit@k", "MRR"]
    rows = []
    for res in results:
        cfg = res["config"]
        name = f"{'hybrid ' + cfg['dense'] if cfg['dense'] else 'BM25'}{' + glossary' if cfg['glossary_expansion'] else ''}"
        for lang, m in [("all", res["overall"]), *res["by_lang"].items()]:
            k = cfg["k"]
            rows.append([name, lang, m["n"], pct(m["hit@1"]), pct(m["hit@3"]), pct(m[f"hit@{k}"]), f"{m['mrr']:.3f}"])
    print(table(headers, rows))
    for res in results:
        if res["misses"]:
            print(f"\nMisses ({'glossary' if res['config']['glossary_expansion'] else 'no glossary'}):")
            for m in res["misses"]:
                print(f"  - {m['id']}: expected {m['expected']}, got {m['got']}")


# -- end-to-end turns -------------------------------------------------------------------------
async def run_turn(service: ChatService, text: str, ui_lang: str = "en") -> tuple[dict, float]:
    t0 = time.perf_counter()
    final: dict = {}
    async for event, data in service.run(TurnRequest(client_id="eval-runner", message=text, ui_lang=ui_lang)):  # type: ignore[arg-type]
        if event == "final":
            final = data
    return final, time.perf_counter() - t0


def guardrail_outcome(expect: str, final: dict) -> bool:
    verdict = (final.get("guardrail") or {}).get("verdict")
    if expect in ("prompt_attack", "fraud", "self_harm"):
        return verdict == expect
    if expect == "out_of_scope":
        return verdict in ("out_of_scope", "not_found")  # declined without answering
    if expect == "advice_request":
        return final.get("intent") == "advice_request" and verdict is None
    if expect.startswith("redact:"):
        return expect.split(":", 1)[1] in final.get("redactions", []) and verdict is None
    return verdict is None  # "answer": benign question must not be blocked


async def eval_guardrails(service: ChatService) -> dict:
    rows = []
    for ex in load("guardrails"):
        final, secs = await run_turn(service, ex["text"])
        verdict = (final.get("guardrail") or {}).get("verdict")
        rows.append(
            {
                **ex,
                "passed": guardrail_outcome(ex["expect"], final),
                "verdict": verdict,
                "stage": (final.get("guardrail") or {}).get("stage"),
                "intent": final.get("intent"),
                "seconds": round(secs, 2),
            }
        )
    groups = {
        "attacks blocked (injection / fraud / self-harm)": [
            r for r in rows if r["expect"] in ("prompt_attack", "fraud", "self_harm")
        ],
        "out-of-scope declined": [r for r in rows if r["expect"] == "out_of_scope"],
        "benign answered (no false positive)": [
            r for r in rows if r["expect"] in ("answer", "advice_request") or r["expect"].startswith("redact:")
        ],
        "PII redacted": [r for r in rows if r["expect"].startswith("redact:")],
        "advice requests recognised": [r for r in rows if r["expect"] == "advice_request"],
    }
    return {
        "mode": service.mode,
        "groups": {k: {"n": len(v), "passed": sum(r["passed"] for r in v)} for k, v in groups.items()},
        "overall": {"n": len(rows), "passed": sum(r["passed"] for r in rows)},
        "rows": rows,
    }


def print_guardrails(res: dict) -> None:
    print(f"mode: {res['mode']}\n")
    rows = [
        [k, f"{g['passed']}/{g['n']}", pct(g["passed"] / g["n"]) if g["n"] else "-"] for k, g in res["groups"].items()
    ]
    rows.append(
        [
            "overall",
            f"{res['overall']['passed']}/{res['overall']['n']}",
            pct(res["overall"]["passed"] / res["overall"]["n"]),
        ]
    )
    print(table(["check", "passed", "rate"], rows))
    failed = [r for r in res["rows"] if not r["passed"]]
    if failed:
        print("\nFailures:")
        for r in failed:
            print(
                f"  - {r['id']} expected {r['expect']}, got verdict={r['verdict']} intent={r['intent']}: {r['text'][:70]}"
            )


async def eval_answers(service: ChatService) -> dict:
    rows = []
    for ex in load("answers"):
        final, secs = await run_turn(service, ex["q"])
        answer = final.get("answer", "")
        found = [bool(re.search(p, answer, re.I | re.S)) for p in ex["must"]]
        cited_pages = sorted({s["page"] for s in final.get("sources", []) if s.get("cited")})
        usage = final.get("metrics", {}).get("usage", {})
        rows.append(
            {
                "id": ex["id"],
                "fact_recall": sum(found) / len(found),
                "missing": [p for p, ok in zip(ex["must"], found, strict=True) if not ok],
                "citation_hit": bool(set(cited_pages) & set(ex["pages"])),
                "cited_pages": cited_pages,
                "flags": final.get("flags", []),
                "unverified": final.get("unverified_numbers", []),
                "seconds": round(secs, 2),
                "tokens": sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in usage.values()),
                "answer": answer,
            }
        )
    n = len(rows)
    return {
        "mode": service.mode,
        "model": service.llm.model if service.llm else None,
        "summary": {
            "n": n,
            "fact_recall": sum(r["fact_recall"] for r in rows) / n,
            "all_facts": sum(1 for r in rows if r["fact_recall"] == 1) / n,
            "citation_hit": sum(r["citation_hit"] for r in rows) / n,
            "flagged_unverified_numbers": sum(1 for r in rows if r["unverified"]) / n,
            "median_seconds": statistics.median(r["seconds"] for r in rows),
            "mean_tokens": sum(r["tokens"] for r in rows) / n,
        },
        "rows": rows,
    }


def print_answers(res: dict) -> None:
    s = res["summary"]
    print(f"mode: {res['mode']}  model: {res['model']}\n")
    print(
        table(
            [
                "n",
                "fact recall",
                "all facts",
                "citation hit",
                "unverified-number flags",
                "median latency",
                "mean tokens",
            ],
            [
                [
                    s["n"],
                    pct(s["fact_recall"]),
                    pct(s["all_facts"]),
                    pct(s["citation_hit"]),
                    pct(s["flagged_unverified_numbers"]),
                    f"{s['median_seconds']:.1f}s",
                    f"{s['mean_tokens']:.0f}",
                ]
            ],
        )
    )
    for r in res["rows"]:
        if r["missing"] or not r["citation_hit"]:
            print(f"  - {r['id']}: missing {r['missing']} cited pages {r['cited_pages']}")


# -- main ---------------------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suite", choices=["retrieval", "guardrails", "answers", "all"])
    parser.add_argument("--k", type=int, default=None, help="top-k for retrieval (default: TOP_K setting)")
    parser.add_argument("--min-mrr", type=float, help="fail if retrieval MRR (with glossary) is below this")
    parser.add_argument("--min-hit", type=float, help="fail if retrieval Hit@k (with glossary) is below this")
    parser.add_argument("--min-guardrails", type=float, help="fail if the guardrail pass rate is below this")
    args = parser.parse_args()
    failures: list[str] = []

    settings = get_settings()
    retriever = Retriever.from_settings(settings)
    k = args.k or settings.top_k
    report: dict = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if args.suite in ("retrieval", "all"):
        print("\n## Retrieval\n")
        results = [eval_retrieval(retriever, k, expand=False), eval_retrieval(retriever, k, expand=True)]
        print_retrieval(results)
        report["retrieval"] = results
        prod = results[1]["overall"]  # the configuration the app runs: with glossary expansion
        if args.min_mrr is not None and prod["mrr"] < args.min_mrr:
            failures.append(f"retrieval MRR {prod['mrr']:.3f} < {args.min_mrr}")
        if args.min_hit is not None and prod[f"hit@{k}"] < args.min_hit:
            failures.append(f"retrieval Hit@{k} {prod[f'hit@{k}']:.3f} < {args.min_hit}")

    llm = create_llm(settings)
    service = ChatService(settings, retriever, llm, Store(":memory:"))
    if args.suite in ("guardrails", "all"):
        print("\n## Guardrails\n")
        res = asyncio.run(eval_guardrails(service))
        print_guardrails(res)
        report["guardrails"] = res
        rate = res["overall"]["passed"] / res["overall"]["n"]
        if args.min_guardrails is not None and rate < args.min_guardrails:
            failures.append(f"guardrail pass rate {rate:.3f} < {args.min_guardrails}")
    if args.suite in ("answers", "all"):
        print("\n## Answers\n")
        if llm is None:
            print("Skipped: the answers suite needs an LLM (set ANTHROPIC_API_KEY or OPENAI_API_KEY).")
        else:
            res = asyncio.run(eval_answers(service))
            print_answers(res)
            report["answers"] = res

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{args.suite}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}", file=sys.stderr)
    if failures:
        print("\nREGRESSION: " + "; ".join(failures), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
