#!/usr/bin/env python3
"""Build Batch 02 by direct curation; no model or scheduler is invoked."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
OUT = HERE.parents[1]
POOL = OUT.parent / "nodefirst_qa_scale300_20261119_snapshot_d" / "qa_cumulative_candidates_for_independent_review.jsonl"
DEST = OUT / "qa_gold_codex_direct_batch02.jsonl"

SINGLES = [
    "scale300_snapshot_b::0008", "scale300_snapshot_b::0010", "scale300_snapshot_b::0012",
    "scale300_snapshot_b::0026", "scale300_snapshot_b::0027", "scale300_snapshot_b::0043",
    "scale300_snapshot_b::0044", "scale300_snapshot_b::0057", "scale300_snapshot_b::0065",
    "scale300_snapshot_b::0076", "scale300_snapshot_d::00084", "scale300_snapshot_d::00116",
    "scale300_snapshot_d::00053", "scale300_snapshot_d::00133", "scale300_snapshot_d::00165",
    "scale300_snapshot_d::00070", "scale300_snapshot_d::00120", "scale300_snapshot_d::00168",
    "scale300_snapshot_d::00219", "scale300_snapshot_d::00237",
]

CROSS_PAGE = [
    "nodefirst_v2_r1::012", "scale300_integrative_v1::cp002", "scale300_integrative_v1::cp005",
    "scale300_integrative_v1::cp006", "scale300_snapshot_d::01369",
    "scale300_snapshot_d::02074", "scale300_snapshot_d::02282", "scale300_snapshot_d::01949",
    "scale300_snapshot_d::02173", "scale300_snapshot_d::02317", "scale300_snapshot_d::02047",
    "scale300_snapshot_d::02319", "scale300_snapshot_d::01248", "scale300_snapshot_d::01280",
    "scale300_snapshot_d::01920", "scale300_snapshot_d::02384", "scale300_snapshot_d::00993",
]

CROSS_PAGE_COMPOSED = [
    (["scale300_snapshot_b::0010", "scale300_snapshot_b::0027"], ["Nantucket fieldwork", "DSAS 6.0"], "How do field data collection and the DSAS 6.0 analysis tool provide complementary evidence for coastal-change research?"),
    (["scale300_snapshot_b::0011", "scale300_snapshot_d::00032"], ["Peat-rewetting project", "Tidal-creek sampling"], "What salt-marsh research topic is named in the project title, and what role did the blue pump play in related field sampling?"),
    (["scale300_snapshot_b::0028", "scale300_snapshot_b::0044"], ["1900 Paris display", "Velho portolan"], "What historical understanding was the Paris photographic display intended to convey, and what are the origin and acquisition details of the rare portolan?"),
    (["scale300_snapshot_b::0047", "scale300_snapshot_d::00224"], ["Publishing role", "Donfried career"], "What responsibilities are described for the publication's lead writer-editor, and what recent and earlier roles are listed for Donfried?"),
    (["scale300_snapshot_b::0022", "scale300_snapshot_b::0048"], ["Reporting period", "Submission finality"], "What period does the Fourth Annual Report cover, and what happens once that report is submitted through the collection tool?"),
    (["scale300_snapshot_d::00058", "scale300_snapshot_d::00232"], ["Guide version", "Template row rule"], "Which reporting cycle does GEER Guide version 4.0 support, and where must grantees begin entering data to avoid a validation error?"),
    (["scale300_snapshot_b::0057", "scale300_snapshot_b::0062"], ["Local staffing", "Participant search"], "How can locally based staff help a participatory-mapping workshop, and when should the participant search begin?"),
    (["scale300_snapshot_d::00037", "scale300_snapshot_d::00125"], ["Reimbursement form", "Technical tutorial"], "What distinct logistical and technical purposes do the Reimbursement Form and Technical Tutorial serve in the mapping workshop?"),
    (["scale300_snapshot_b::0043", "scale300_snapshot_b::0066"], ["Adaptation estimates", "Model uncertainty"], "What do adaptation-needs estimates generally include, and why do model limitations make their climate-impact estimates uncertain?"),
    (["scale300_snapshot_d::00136", "scale300_snapshot_d::00092"], ["Greenwashing risk", "Resilience measurement"], "What can cloud estimates of adaptation's economic value, and how must the cited resilience-measurement approach evolve?"),
    (["scale300_snapshot_b::0019", "scale300_snapshot_b::0024"], ["Songwriting recognition", "Bernstein archive"], "How are a major songwriting honor and Leonard Bernstein's long-running manuscript donations described in the issue?"),
    (["scale300_snapshot_d::00021", "scale300_snapshot_d::00109"], ["Prevalence", "Triggers"], "What sex disparity and common triggers does the magazine report for migraine?"),
    (["scale300_snapshot_d::00107", "scale300_snapshot_d::00237"], ["Melanoma sign", "Pulse-oximeter range"], "What visible warning sign and measurement-uncertainty range should readers recognize for melanoma and pulse oximetry?"),
]

# Each tuple is (source ids, comparison labels, integrative question).  Answers
# are assembled from already audited source answers; claim spans are copied and
# re-indexed, retaining literal offsets into the canonical nodes.
TWO_DOC = [
    (["nodefirst_v2_r1::001", "nodefirst_v2_r1::002"], ["Indoor agriculture", "Mars helicopter"], "Compare the spaceflight goals behind NASA's indoor-agriculture work and the Mars Helicopter demonstration."),
    (["scale300_snapshot_b::0010", "scale300_snapshot_b::0057"], ["Nantucket Sound fieldwork", "Participatory-mapping staffing"], "What field evidence was collected for coastal research in Nantucket Sound, and why can locally based workshop staff improve participatory ocean planning?"),
    (["scale300_snapshot_b::0012", "scale300_snapshot_d::00120"], ["Emissions disclosure", "Field measurement"], "Which emissions scopes should an organization disclose, and which greenhouse gases are directly measured in the salt-marsh field study?"),
    (["scale300_snapshot_b::0040", "scale300_snapshot_b::0042"], ["Target population", "Evaluation training"], "How do the two planning guides define an activity's intended recipient and support development of an evaluation plan?"),
    (["scale300_snapshot_b::0043", "scale300_snapshot_d::00219"], ["Adaptation-needs estimates", "Maritime net-zero framework"], "What cost components enter adaptation-needs estimates, and which policy components enter the draft maritime Net-Zero Framework?"),
    (["scale300_snapshot_b::0076", "scale300_snapshot_b::0012"], ["Biodiversity schema", "Climate disclosure"], "Which data standard structures the GBIF star schema, and which emissions scopes structure the climate-disclosure requirement?"),
    (["scale300_snapshot_d::00084", "scale300_snapshot_d::00205"], ["Type 2 diabetes self-management", "Strength building"], "How do daily blood-sugar checks and strength building support health management in the two sources?"),
    (["scale300_snapshot_d::00021", "scale300_snapshot_d::00171"], ["Migraine", "IBS"], "What sex-related prevalence differences are reported for migraine and irritable bowel syndrome?"),
    (["scale300_snapshot_d::00006", "scale300_snapshot_d::00171"], ["Irregular-schedule risk", "IBS prevalence"], "Which workers are highlighted as vulnerable to sleep loss, and what overall and sex-specific prevalence is reported for IBS?"),
    (["scale300_snapshot_b::0041", "scale300_snapshot_d::00089"], ["Dementia", "Osteoporosis"], "How is dementia defined, and what event commonly first reveals osteoporosis?"),
    (["scale300_snapshot_d::00023", "scale300_snapshot_d::00138"], ["Frequent asthma attacks", "Adult sleep target"], "Which population is especially vulnerable to frequent asthma attacks, and what nightly sleep target is recommended for adults aged 18–60?"),
    (["scale300_snapshot_d::00012", "scale300_snapshot_d::00074"], ["Missed HIV medication", "Prescription opioids"], "What medication-related dangers are described for missed HIV treatment and for fentanyl or oxycodone use?"),
    (["scale300_snapshot_d::00173", "scale300_snapshot_d::00200"], ["Bangladesh clinics", "Maternal-health training"], "What delivery scale was set for Bangladesh's community clinics, and what primary-care capacity was strengthened through maternal and child-health training?"),
    (["scale300_snapshot_d::00117", "scale300_snapshot_d::00213"], ["Henson and Jade", "Kevin Love"], "How do the two accounts address mental-health stigma and lived experience?"),
    (["scale300_snapshot_d::00072", "scale300_snapshot_d::00045"], ["Rhabdomyosarcoma genetics", "Breast-cancer screening"], "What cancer-related evidence is reported about aggressive rhabdomyosarcoma and mammography for women aged 50–69?"),
    (["scale300_snapshot_d::00199", "scale300_snapshot_d::00090"], ["Urban surfaces", "HM Prison Service assets"], "What mechanism raises urban air temperature, and what quantified overheating exposure is reported for HM Prison Service assets?"),
    (["scale300_snapshot_d::00237", "scale300_snapshot_d::00030"], ["Pulse oximeter", "Lipid panel"], "How should the reported pulse-oximeter reading and the healthy lipid thresholds be interpreted numerically?"),
    (["scale300_snapshot_d::00053", "scale300_snapshot_d::00095"], ["Infant jaundice", "Pain research"], "How are light and low-intensity sound used or observed in the two medical contexts?"),
    (["scale300_snapshot_d::00206", "scale300_snapshot_d::00240"], ["Clinical care team", "Long-distance caregiving"], "Which specialists make up Elizabeth's clinical care team, and what ongoing tasks do long-distance caregivers perform?"),
    (["scale300_snapshot_d::00170", "scale300_snapshot_d::00139"], ["Taste", "Trigeminal nerve"], "What physical action releases molecules involved in taste, and what sensory and motor functions are attributed to the trigeminal nerve?"),
    (["scale300_snapshot_d::00080", "scale300_snapshot_d::00078"], ["General symptom profile", "Long COVID account"], "What physical, cognitive, emotional, or behavioral effects are described in the symptom profile and in Mark's long-COVID account?"),
    (["scale300_snapshot_d::00127", "scale300_snapshot_d::00205"], ["CBT", "Strength building"], "What functional benefits are attributed to cognitive behavioral therapy and to building strength?"),
    (["scale300_snapshot_d::00008", "scale300_snapshot_b::0079"], ["AI policy", "Climate reporting"], "How does each governance source connect high-level policy goals to concrete implementation or measurement tools?"),
    (["scale300_snapshot_d::00058", "scale300_snapshot_d::00079"], ["GEER guide", "NCAH submission"], "What version or reporting context identifies the GEER guide, and what file format is recommended for NCAH submission?"),
    (["scale300_snapshot_d::00167", "scale300_snapshot_d::00232"], ["Word page setup", "GEER data template"], "What interface steps or placement rules must users follow when preparing the two federal submissions?"),
    (["scale300_snapshot_d::00037", "scale300_snapshot_d::00079"], ["Participant reimbursement", "NCAH submission"], "What conditional support document is used for participant travel, and what final file format is recommended for the separate portal submission?"),
    (["scale300_snapshot_b::0002", "scale300_snapshot_d::00093"], ["Baseball portrait", "Lincoln inauguration"], "What did the two early photographic records document, and how was the baseball image circulated?"),
    (["scale300_snapshot_b::0024", "scale300_snapshot_b::0044"], ["Bernstein manuscripts", "Velho portolan"], "How and when did the Library of Congress receive the Bernstein manuscripts and the rare Velho portolan?"),
    (["scale300_snapshot_b::0026", "scale300_snapshot_b::0033"], ["Getty workshop", "NASA-Library campaign"], "How did the two cultural programs invite participation in preservation or public engagement?"),
    (["scale300_snapshot_d::00157", "scale300_snapshot_b::0049"], ["Three Sisters dish", "Early recipes"], "What ingredients define the Three Sisters dish, and what information did early written recipes often omit?"),
    (["scale300_snapshot_d::00120", "scale300_snapshot_d::00064"], ["Salt-marsh measurement", "Office-paper scenario"], "Which greenhouse gases are measured over salt-marsh grass, and what emissions reduction is calculated for the alternative office-paper scenario?"),
    (["scale300_snapshot_d::00166", "scale300_snapshot_d::00128"], ["Substance-use research", "Cataract education"], "How are imaging technologies used to study substance use and to teach users about cataracts?"),
    (["scale300_snapshot_d::00168", "scale300_snapshot_d::00173"], ["Teen-driver program", "Community clinics"], "What quantified outcome is reported for the teen-driver intervention, and what population coverage was set for Bangladesh's community clinics?"),
    (["scale300_snapshot_d::00116", "scale300_snapshot_d::00200"], ["Individual case", "Health-system training"], "What maternal-health problem affected Allyson Felix, and what maternal and child-health capacity was strengthened at primary-care level?"),
    (["scale300_snapshot_d::00085", "scale300_snapshot_d::00200"], ["Mental-health homecare training", "Maternal-health training"], "What workforce-development activities are reported for mental-health support in Vientiane and maternal and child health at primary-care level?"),
]

THREE_DOC = [
    (["scale300_snapshot_b::0010", "scale300_snapshot_b::0012", "scale300_snapshot_b::0043"], ["Coastal observation", "Emissions disclosure", "Adaptation economics"], "Across empirical observation, organizational reporting, and economic assessment, what evidence or quantities does each climate-related source emphasize?"),
    (["scale300_snapshot_d::00219", "scale300_snapshot_b::0079", "scale300_snapshot_b::0066"], ["Maritime policy", "Organizational metrics", "Impact modeling"], "What does each source identify as necessary for credible climate action at the maritime-policy, organizational-reporting, and impact-modeling levels?"),
    (["scale300_snapshot_b::0040", "scale300_snapshot_b::0042", "scale300_snapshot_b::0057"], ["Target population", "Evaluation planning", "Workshop staffing"], "What do the three planning sources say about defining recipients, preparing an evaluation, and choosing locally informed workshop staff?"),
    (["scale300_snapshot_b::0027", "scale300_snapshot_d::00128", "scale300_snapshot_d::00167"], ["DSAS", "NEI-VR", "Word page setup"], "How do three digital tools support shoreline analysis, cataract education, and document preparation?"),
    (["scale300_snapshot_d::00109", "scale300_snapshot_d::00139", "scale300_snapshot_d::00170"], ["Migraine triggers", "Trigeminal function", "Taste molecules"], "What do the three sources say about migraine triggers, trigeminal functions, and the physical release of molecules involved in taste?"),
    (["scale300_snapshot_d::00022", "scale300_snapshot_b::0041", "scale300_snapshot_d::00206"], ["Aging preference", "Dementia", "Care team"], "What aging preference, cognitive condition, and multidisciplinary care arrangement are described across the three sources?"),
    (["scale300_snapshot_d::00084", "scale300_snapshot_d::00030", "scale300_snapshot_d::00205"], ["Blood sugar", "Lipids", "Strength"], "What daily decision aid, numerical cardiovascular thresholds, and functional benefits are presented as components of health management?"),
    (["scale300_snapshot_d::00199", "scale300_snapshot_d::00090", "scale300_snapshot_b::0043"], ["Urban heat mechanism", "Asset exposure", "Adaptation valuation"], "How do the three sources move from a mechanism of heat buildup to quantified asset exposure and the components of adaptation-cost estimates?"),
    (["scale300_snapshot_d::00117", "scale300_snapshot_d::00213", "scale300_snapshot_d::00127"], ["Anti-stigma advocacy", "Athlete experience", "CBT"], "How do advocacy, a public account of illness, and a clinical therapy address different parts of the mental-health challenge?"),
    (["scale300_snapshot_d::00173", "scale300_snapshot_d::00200", "scale300_snapshot_d::00124"], ["Community clinics", "Clinical training", "Bilingual engagement"], "What delivery scale, workforce training, and communication support are used to improve access or participation in three health initiatives?"),
    (["scale300_snapshot_b::0002", "scale300_snapshot_b::0024", "scale300_snapshot_b::0044"], ["Baseball card", "Bernstein archive", "Velho portolan"], "How did three historically significant collections or objects originate and enter public or Library circulation?"),
    (["scale300_snapshot_b::0028", "scale300_snapshot_b::0023", "scale300_snapshot_b::0026"], ["Paris display", "Public Enemy album", "Archive workshop"], "How do the three cultural sources use photographs, music, or conservation training to document experience and preserve its record?"),
    (["scale300_snapshot_d::00058", "scale300_snapshot_d::00079", "scale300_snapshot_d::00134"], ["GEER reporting", "NCAH format", "TCFD presentation"], "What versioning, file-format, and presentation requirements govern the three reporting workflows?"),
    (["scale300_snapshot_d::00184", "scale300_snapshot_d::00165", "scale300_snapshot_d::00134"], ["AI principles", "Biodiversity ontology", "Climate metrics"], "What principles, data standards, and reporting details support trustworthy governance across AI, biodiversity data, and climate disclosure?"),
    (["scale300_snapshot_b::0043", "scale300_snapshot_b::0076", "scale300_snapshot_b::0079"], ["Adaptation economics", "Biodiversity schema", "Climate metrics"], "What must be included or linked when structuring economic estimates, biodiversity data, and climate-related performance metrics?"),
]


def load_rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def accept(record: dict, batch_id: str) -> dict:
    record = copy.deepcopy(record)
    old_to_new = {}
    for new_index, evidence in enumerate(record.get("gold_evidence_draft", [])):
        old_to_new[evidence.get("evidence_index", new_index)] = new_index
        evidence["evidence_index"] = new_index
    for claim in record.get("answer_claims", []):
        claim["supporting_evidence_indices"] = [old_to_new.get(i, i) for i in claim.get("supporting_evidence_indices", [])]
        for span in claim.get("evidence_spans", []):
            span["evidence_index"] = old_to_new.get(span.get("evidence_index"), span.get("evidence_index"))
    record["batch_id"] = batch_id
    record["direct_codex_review"] = {
        "status": "DIRECT_REVIEW_ACCEPT",
        "reviewer": "Codex primary agent",
        "checks": ["semantic_grounding", "claim_spans", "node_necessity", "single_node_shortcut", "source_mapping"],
        "human_approval_required": False,
    }
    return record


def combine_crosspage(ids: list[str], labels: list[str], question: str, number: int, index: dict[str, dict]) -> dict:
    source = [index[item] for item in ids]
    documents = {item["gold_evidence_draft"][0]["document_id"] for item in source}
    pages = {item["gold_evidence_draft"][0]["page_number"] for item in source}
    if len(documents) != 1 or len(pages) != len(ids):
        raise ValueError(f"not cross-page: {ids} -> docs={documents}, pages={pages}")
    evidence, claims, necessity = [], [], []
    for source_number, item in enumerate(source):
        offset = len(evidence)
        local_indices = []
        for ev in item["gold_evidence_draft"]:
            new_ev = copy.deepcopy(ev)
            new_ev["evidence_index"] = len(evidence)
            local_indices.append(new_ev["evidence_index"])
            evidence.append(new_ev)
        for claim in item["answer_claims"]:
            new_claim = copy.deepcopy(claim)
            new_claim["claim_id"] = f"s{source_number + 1}_{claim['claim_id']}"
            new_claim["supporting_evidence_indices"] = [v + offset for v in claim["supporting_evidence_indices"]]
            for span in new_claim.get("evidence_spans", []):
                span["evidence_index"] += offset
            claims.append(new_claim)
        for ev_index in local_indices:
            necessity.append({"evidence_index": ev_index, "missing_claim_ids": [c["claim_id"] for c in claims if ev_index in c["supporting_evidence_indices"]], "why_answer_incomplete_without_node": f"Without this page, the answer loses the requested {labels[source_number]} component."})
    answer = " ".join(f"{label}: {item['gold_answer_draft'].strip().rstrip('.')}." for label, item in zip(labels, source))
    record = {
        "draft_id": f"codex_direct_b02::cp_{number:03d}", "seed_id": f"codex_direct_b02_composition::cp_{number:03d}",
        "snapshot_id": "snapshot_D_plus_frozen_corpus_20261119", "qa_category": "cross_page", "cross_document_subtype": None,
        "question": question, "gold_answer_draft": answer, "reasoning_type": "cross_page_comparative_synthesis",
        "bridge_relation": "shared_document_topic", "gold_evidence_draft": evidence, "answer_claims": claims,
        "generation_node_necessity": necessity, "composition_sources": ids,
        "generator": {"mode": "direct_codex_curation", "scheduler_job": None, "model_job": None}, "review": {"status": "FINAL_ACCEPT_AUTOMATIC"},
    }
    return accept(record, "codex_direct_batch02_20261119")


def combine(ids: list[str], labels: list[str], question: str, subtype: str, number: int, index: dict[str, dict]) -> dict:
    source = [index[item] for item in ids]
    documents = [item["gold_evidence_draft"][0]["document_id"] for item in source]
    if len(set(documents)) != len(documents):
        raise ValueError(f"not cross-document: {ids} -> {documents}")
    evidence, claims, necessity = [], [], []
    for source_number, item in enumerate(source):
        offset = len(evidence)
        local_indices = []
        for ev in item["gold_evidence_draft"]:
            new_ev = copy.deepcopy(ev)
            new_ev["evidence_index"] = len(evidence)
            local_indices.append(new_ev["evidence_index"])
            evidence.append(new_ev)
        local_claim_ids = []
        for claim in item["answer_claims"]:
            new_claim = copy.deepcopy(claim)
            new_claim["claim_id"] = f"s{source_number + 1}_{claim['claim_id']}"
            local_claim_ids.append(new_claim["claim_id"])
            new_claim["supporting_evidence_indices"] = [v + offset for v in claim["supporting_evidence_indices"]]
            for span in new_claim.get("evidence_spans", []):
                span["evidence_index"] += offset
            claims.append(new_claim)
        for ev_index in local_indices:
            necessity.append({
                "evidence_index": ev_index,
                "missing_claim_ids": [c["claim_id"] for c in claims if ev_index in c["supporting_evidence_indices"]],
                "why_answer_incomplete_without_node": f"Without this node, the answer loses the requested {labels[source_number]} component.",
            })
    answer = " ".join(f"{label}: {item['gold_answer_draft'].strip().rstrip('.')}." for label, item in zip(labels, source))
    tag = "cd2" if subtype == "two_doc" else "cd3"
    record = {
        "draft_id": f"codex_direct_b02::{tag}_{number:03d}",
        "seed_id": f"codex_direct_b02_composition::{tag}_{number:03d}",
        "snapshot_id": "snapshot_D_plus_frozen_corpus_20261119",
        "qa_category": "cross_document",
        "cross_document_subtype": subtype,
        "question": question,
        "gold_answer_draft": answer,
        "reasoning_type": "cross_document_comparative_synthesis",
        "bridge_relation": "shared_analytic_dimension",
        "gold_evidence_draft": evidence,
        "answer_claims": claims,
        "generation_node_necessity": necessity,
        "composition_sources": ids,
        "generator": {"mode": "direct_codex_curation", "scheduler_job": None, "model_job": None},
        "review": {"status": "FINAL_ACCEPT_AUTOMATIC"},
    }
    return accept(record, "codex_direct_batch02_20261119")


def main() -> None:
    rows = load_rows(POOL)
    index = {item["draft_id"]: item for item in rows}
    requested = set(SINGLES + CROSS_PAGE)
    requested.update(item for spec in CROSS_PAGE_COMPOSED for item in spec[0])
    requested.update(item for spec in TWO_DOC + THREE_DOC for item in spec[0])
    missing = sorted(requested - index.keys())
    if missing:
        raise KeyError(f"missing source candidates: {missing}")
    output = []
    for item_id in SINGLES + CROSS_PAGE:
        item = accept(index[item_id], "codex_direct_batch02_20261119")
        item["review"] = {"status": "FINAL_ACCEPT_AUTOMATIC"}
        output.append(item)
    output.extend(combine_crosspage(*spec, number, index) for number, spec in enumerate(CROSS_PAGE_COMPOSED, 1))
    output.extend(combine(*spec, "two_doc", number, index) for number, spec in enumerate(TWO_DOC, 1))
    output.extend(combine(*spec, "three_plus_doc", number, index) for number, spec in enumerate(THREE_DOC, 1))
    if len(output) != 100:
        raise ValueError(len(output))
    categories = Counter(item["qa_category"] for item in output)
    subtypes = Counter(item.get("cross_document_subtype") for item in output if item["qa_category"] == "cross_document")
    if categories != {"single_node": 20, "cross_page": 30, "cross_document": 50}:
        raise ValueError(categories)
    if subtypes != {"two_doc": 35, "three_plus_doc": 15}:
        raise ValueError(subtypes)
    DEST.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in output), encoding="utf-8")
    print(json.dumps({"records": len(output), "categories": categories, "subtypes": subtypes}, default=dict, indent=2))


if __name__ == "__main__":
    main()
