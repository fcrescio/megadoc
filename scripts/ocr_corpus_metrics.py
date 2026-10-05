"""Concordance metrics, not accuracy against an annotated gold transcript."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import random
import re
import statistics
import unicodedata

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt


def canonical_text(value):
    html = MarkdownIt("commonmark", {"html": True}).enable("table").render(value or "")
    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img"):
        image.decompose()
    return " ".join(unicodedata.normalize("NFKC", soup.get_text(" ")).casefold().split())


def numbers(value):
    return Counter(re.findall(r"(?<!\w)\d+(?:[.,/]\d+)*(?!\w)", canonical_text(value)))


def concordance(reference, candidate):
    left, right = canonical_text(reference), canonical_text(candidate)
    words_left = re.findall(r"\w+", left)
    words_right = re.findall(r"\w+", right)
    left_bag, right_bag = Counter(words_left), Counter(words_right)
    left_nums, right_nums = numbers(reference), numbers(candidate)
    shared_nums = sum((left_nums & right_nums).values())
    denominator = len(words_left) + len(words_right)
    return {
        "word_sequence_agreement_not_accuracy": SequenceMatcher(
            None, words_left, words_right, autojunk=False).ratio(),
        "word_bag_f1_not_accuracy": 2 * sum((left_bag & right_bag).values()) / denominator
        if denominator else None,
        "reference_numeric_occurrences": sum(left_nums.values()),
        "candidate_numeric_occurrences": sum(right_nums.values()),
        "shared_numeric_occurrences": shared_nums,
        "numeric_retention_not_accuracy": shared_nums / sum(left_nums.values()) if left_nums else None,
        "numeric_candidate_overlap_not_accuracy": shared_nums / sum(right_nums.values()) if right_nums else None,
        "reference_words": len(words_left), "candidate_words": len(words_right),
        "canonical_text_identical": left == right,
        "numeric_multiset_identical": left_nums == right_nums,
    }


def table_profile(page):
    tables = page.get("tables") or []
    rows, cells = 0, 0
    for table in tables:
        html = " ".join(cell.get("html", "") for cell in table.get("cells") or [])
        if html:
            soup = BeautifulSoup(html, "html.parser")
            rows += len(soup.find_all("tr"))
            cells += len(soup.find_all(["td", "th"]))
        else:
            cells += len(table.get("cells") or [])
    return {"tables": len(tables), "rows": rows, "physical_cells": cells}


def distribution(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": statistics.mean(values),
            "median": statistics.median(values), "min": values[0], "max": values[-1]}


def bootstrap_mean_ci(values, seed=17, iterations=2000):
    """Resample document-level means, never treat pages as independent samples."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return [means[int(iterations * 0.025)], means[min(iterations - 1, int(iterations * 0.975))]]


def summarize(rows, expected, total_documents, state, current=None, variants=("fp16", "int8")):
    summary = {"state": state, "current": current, "expected_page_pairs": expected,
               "total_distinct_documents": total_documents, "attempted_pages": len(rows),
               "warning": "Dots is not gold; all scores measure concordance, not accuracy.",
               "variants": {}, "paired": {}}
    for variant in variants:
        attempted = [row[variant] for row in rows if variant in row]
        ok = [result for result in attempted if result["status"] == "ok"]
        summary["variants"][variant] = {
            "attempted": len(attempted), "successful": len(ok), "failed": len(attempted) - len(ok),
            "latency_s": distribution([r["seconds"] for r in ok]),
            "word_agreement": distribution([r["concordance"]["word_sequence_agreement_not_accuracy"] for r in ok]),
            "numeric_retention": distribution([r["concordance"]["numeric_retention_not_accuracy"] for r in ok]),
            "tables": sum(r["table_profile"]["tables"] for r in ok),
        }
        document_values = defaultdict(list)
        for row in rows:
            if row.get(variant, {}).get("status") == "ok":
                document_values[row["document_id"]].append(
                    row[variant]["concordance"]["word_sequence_agreement_not_accuracy"])
        means = [statistics.mean(values) for values in document_values.values()]
        summary["variants"][variant]["document_word_agreement"] = {
            "distribution": distribution(means), "document_bootstrap_95_ci": bootstrap_mean_ci(means)}
    if len(variants) == 1:
        variant = variants[0]
        summary["paired"] = {"not_applicable": "Single-variant experiment"}
        summary["strata"] = {}
        for group, has_tables in (("dots_table", True), ("dots_no_table", False)):
            group_rows = [r for r in rows if r.get(variant, {}).get("status") == "ok"
                          and bool(r["dots_table_profile"]["tables"]) == has_tables]
            summary["strata"][group] = {"pages": len(group_rows), variant: {
                "word_agreement": distribution([r[variant]["concordance"]["word_sequence_agreement_not_accuracy"] for r in group_rows]),
                "numeric_retention": distribution([r[variant]["concordance"]["numeric_retention_not_accuracy"] for r in group_rows])}}
        return summary
    paired = [row for row in rows if all(row.get(v, {}).get("status") == "ok" for v in variants)]
    summary["paired"]["successful_page_pairs"] = len(paired)
    summary["paired"]["canonical_text_identical_pages"] = sum(row["fp16_int8"]["canonical_text_identical"] for row in paired)
    summary["paired"]["numeric_multiset_identical_pages"] = sum(row["fp16_int8"]["numeric_multiset_identical"] for row in paired)
    docs = defaultdict(list)
    for row in paired:
        docs[row["document_id"]].append(row)
    summary["paired"]["distinct_documents_observed"] = len(docs)
    for metric in ("word_sequence_agreement_not_accuracy", "numeric_retention_not_accuracy"):
        means = []
        for document_rows in docs.values():
            deltas = [r["int8"]["concordance"][metric] - r["fp16"]["concordance"][metric]
                      for r in document_rows if all(r[v]["concordance"][metric] is not None for v in variants)]
            if deltas:
                means.append(statistics.mean(deltas))
        summary["paired"][metric + "_int8_minus_fp16"] = {
            "document_means": distribution(means), "document_bootstrap_95_ci": bootstrap_mean_ci(means)}
    summary["paired"]["int8_over_fp16_time_ratio"] = distribution(
        [r["int8"]["seconds"] / r["fp16"]["seconds"] for r in paired if r["fp16"]["seconds"] > 0])
    strata = defaultdict(list)
    for row in paired:
        group = "dots_table" if row["dots_table_profile"]["tables"] else "dots_no_table"
        strata[group].append(row)
    summary["strata"] = {group: {"page_pairs": len(group_rows),
        **{v: {"word_agreement": distribution([r[v]["concordance"]["word_sequence_agreement_not_accuracy"] for r in group_rows]),
               "numeric_retention": distribution([r[v]["concordance"]["numeric_retention_not_accuracy"] for r in group_rows])}
           for v in variants}} for group, group_rows in strata.items()}
    return summary
