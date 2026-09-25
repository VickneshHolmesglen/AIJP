"""Structure checks for the evaluation datasets (no database, no model).

The runners also verify every label against real chunks before spending time on a run; these
tests catch the cheaper mistakes earlier: a duplicated id, a label naming a file that does not
exist, a seeded-patch overlay that changes more (or less) than its dataset says it does.
"""

import difflib
import json
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
DATASETS = EVAL / "datasets"
CORPUS = EVAL / "corpus"
CORPUS_PATHS = {p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob("*") if p.is_file()}


def load(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("suffix", ["", "_v2", "_v3", "_v4", "_v5", "_v6"])
def test_retrieval_and_qa_sets_are_consistent(suffix: str) -> None:
    retrieval, qa = load(f"retrieval{suffix}.json"), load(f"qa{suffix}.json")
    ids = [q["id"] for q in retrieval["questions"]]
    assert len(ids) == len(set(ids)), "duplicate retrieval question ids"
    for q in retrieval["questions"]:
        assert q["kind"] in retrieval["kinds"], q["id"]
        assert q["expected"], q["id"]
        for e in q["expected"]:
            assert e["path"] in CORPUS_PATHS, f"{q['id']}: no such corpus file {e['path']}"
        if q.get("require_all"):
            assert len(q["expected"]) > 1, f"{q['id']}: require_all needs several sources"
    # every answerable QA entry points at a real question and has non-empty keyword groups
    assert set(qa["answerable"]) <= set(ids)
    for qid, groups in qa["answerable"].items():
        assert groups and all(group and all(alt.strip() for alt in group) for group in groups), qid
    un = [u["id"] for u in qa["unanswerable"]]
    assert len(un) == len(set(un)) and not set(un) & set(ids)
    assert {u["kind"] for u in qa["unanswerable"]} <= {"far", "near"}


def test_v2_is_disjoint_from_v1_and_harder_kinds_are_present() -> None:
    v1, v2 = load("retrieval.json"), load("retrieval_v2.json")
    q1 = {q["question"].lower() for q in v1["questions"]}
    q2 = {q["question"].lower() for q in v2["questions"]}
    assert not q1 & q2, "a v2 question repeats a v1 question"
    assert {q["id"] for q in v1["questions"]}.isdisjoint(q["id"] for q in v2["questions"])
    kinds = {q["kind"] for q in v2["questions"]}
    assert {"multi_hop", "negation", "paraphrase_hard", "code_reasoning"} <= kinds
    unanswerable = load("qa_v2.json")["unanswerable"]
    near = sum(u["kind"] == "near" for u in unanswerable)
    assert near > len(unanswerable) / 2, "v2 should lean on the hard, near-miss refusals"


@pytest.mark.parametrize("name", ["judge_validation.json", "judge_validation_v2.json"])
def test_judge_validation_sets_are_balanced_enough_to_mean_something(name: str) -> None:
    cases = load(name)["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    supported = sum(c["supported"] for c in cases)
    assert 0.25 <= supported / len(cases) <= 0.75, "a judge that always says one thing would pass"
    for c in cases:
        assert all(c[k].strip() for k in ("sources", "question", "answer")), c["id"]


@pytest.mark.parametrize(
    ("dataset", "overlay"),
    [
        ("consistency.json", "seeded_patches"),
        ("consistency_v2.json", "seeded_patches_v2"),
        ("consistency_v3.json", "seeded_patches_v3"),
    ],
)
def test_seeded_overlay_changes_exactly_what_the_dataset_documents(
    dataset: str, overlay: str
) -> None:
    data = load(dataset)
    assert data.get("patches_dir", "seeded_patches") == overlay
    changed_lines = 0
    for patched in (EVAL / overlay).rglob("*"):
        if not patched.is_file():
            continue
        rel = patched.relative_to(EVAL / overlay).as_posix()
        assert rel in CORPUS_PATHS, f"{rel} is not a corpus file"
        diff = difflib.unified_diff(
            (CORPUS / rel).read_text(encoding="utf-8").splitlines(),
            patched.read_text(encoding="utf-8").splitlines(),
            lineterm="",
            n=0,
        )
        changed_lines += sum(
            1 for line in diff if line.startswith("+") and not line.startswith("+++")
        )
    assert changed_lines == len(data["seeded_changes"]), "overlay and its documentation disagree"

    claims = data["claims"]
    assert len({c["id"] for c in claims}) == len(claims)
    kinds = {c["kind"]: c["expected"] for c in claims}
    assert kinds == {
        "seeded": "potential_discrepancy",
        "consistent": "consistent",
        "unsupported": "insufficient_evidence",
    }
    for c in claims:
        for path in c["design"] + c["implementation"]:
            assert path in CORPUS_PATHS, f"{c['id']}: no such file {path}"


def test_v3_test_set_is_disjoint_from_the_earlier_sets_and_answers_are_whole_numbers() -> None:
    earlier = {
        q["question"].lower()
        for name in ("retrieval.json", "retrieval_v2.json")
        for q in load(name)["questions"]
    }
    v3 = load("retrieval_v3.json")["questions"]
    assert not earlier & {q["question"].lower() for q in v3}
    qa = load("qa_v3.json")
    for qid, groups in qa["answerable"].items():
        (group,) = groups
        assert len(group) == 1 and group[0].startswith("#"), f"{qid}: expected one whole number"
        assert qid in qa["derivations"]


def test_v4_test_set_is_new_and_mixes_computation_with_plain_lookups() -> None:
    earlier = {
        q["question"].lower()
        for name in ("retrieval.json", "retrieval_v2.json", "retrieval_v3.json")
        for q in load(name)["questions"]
    }
    v4 = load("retrieval_v4.json")["questions"]
    assert not earlier & {q["question"].lower() for q in v4}
    kinds = [q["kind"] for q in v4]
    # The escalation idea only pays off on a MIX: enough of each kind to see both effects.
    assert kinds.count("computation") >= 15 and kinds.count("lookup") >= 10
    qa = load("qa_v4.json")
    computed = set(qa["derivations"]) & {q["id"] for q in v4 if q["kind"] == "computation"}
    assert computed == {q["id"] for q in v4 if q["kind"] == "computation"}


def test_v5_test_set_is_new_and_has_lookalike_lookups_to_expose_wasted_escalation() -> None:
    earlier = {
        q["question"].lower()
        for name in (
            "retrieval.json",
            "retrieval_v2.json",
            "retrieval_v3.json",
            "retrieval_v4.json",
        )
        for q in load(name)["questions"]
    }
    v5 = load("retrieval_v5.json")["questions"]
    assert not earlier & {q["question"].lower() for q in v5}
    kinds = [q["kind"] for q in v5]
    assert kinds.count("computation") >= 15 and kinds.count("lookup") >= 10
    lookups = [q["question"].lower() for q in v5 if q["kind"] == "lookup"]
    # A trigger that fires on quantity WORDING must be tested against lookups that use it.
    assert sum(("how much" in q or "how many" in q) for q in lookups) >= 6


def test_v6_test_set_is_new_and_every_bridge_needs_two_sources() -> None:
    earlier = {
        q["question"].lower()
        for suffix in ("", "_v2", "_v3", "_v4", "_v5")
        for q in load(f"retrieval{suffix}.json")["questions"]
    }
    v6 = load("retrieval_v6.json")["questions"]
    assert not earlier & {q["question"].lower() for q in v6}
    bridges = [q for q in v6 if q["kind"].startswith("bridge_")]
    assert len(bridges) >= 15 and sum(q["kind"] == "lookup" for q in v6) >= 10
    # A bridge is only a bridge if the answer needs BOTH chunks, from different sections.
    for q in bridges:
        assert q.get("require_all"), q["id"]
        places = {(e["path"], e.get("section") or e.get("section_prefix")) for e in q["expected"]}
        assert len(places) >= 2, q["id"]
    # '#4' would also match a citation marker like [4]: no group may rely on a bare 1-5 alone.
    for qid, groups in load("qa_v6.json")["answerable"].items():
        for group in groups:
            assert not all(alt in {"#1", "#2", "#3", "#4", "#5"} for alt in group), qid
