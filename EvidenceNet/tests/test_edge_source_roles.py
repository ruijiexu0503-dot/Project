import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from edge_source_roles import attach_source_roles, audit_edge, classify_node


WANG = "[31] Wang, Z., Bovik, A.C., Sheikh, H.R., Simoncelli, E.P.:\nImage quality assessment: from error visibility to\nstructural similarity. IEEE transactions on image\nprocessing 13 (4), 600–612 (2004)"
HORE = "Hore, A. & Ziou, D.\nImage quality metrics: Psnr vs. ssim.\nIn 2010 20th international conference on pattern\nrecognition, 2366–2369 (IEEE, 2010)."


def node(text, **kwargs):
    return {"id": "n", "node_type": "TEXT", "members": [{"id": "m", "kind": "atom", "role": "text", "text": text}], **kwargs}


def test_actual_failed_pair_is_routed_for_reference_review():
    # Quotes and atom roles from the frozen VL-DocIR failed pair, not model guesses.
    nodes = {"A": node(WANG, source_atom_ids=["D0003"]), "B": node(HORE, source_atom_ids=["D0025"])}
    for key, atom_id in (("A", "D0003"), ("B", "D0025")):
        nodes[key] = attach_source_roles(nodes[key], {"atoms": [{"atom_id": atom_id, "atom_type": "text", "layout_role": "reference"}]})
    result = audit_edge({"task_id": "REL_af7b78060a02bd79", "source": "A", "target": "B"}, nodes)
    assert result["route"] == "reference_review"
    assert all(e["role"] == "bibliography" for e in result["endpoints"].values())


@pytest.mark.parametrize("text", [WANG, HORE])
def test_text_only_is_suspicion_not_confirmed_bibliography(text):
    assert classify_node(node(text))["role"] == "suspected_bibliography"


@pytest.mark.parametrize("text", [
    "We use SSIM [31] to evaluate structural similarity and report PSNR in Table 2.",
    "[31] introduced SSIM in 2004. Our model improves its score by 0.02.",
    "LightDiff and MIRNetv2 are compared using FPS and PSNR on the same images.",
    "Wang et al. (2004) introduced SSIM; we apply it to low-light images.",
    "The paper Image quality metrics: Psnr vs. ssim motivates our choice of metrics.",
])
def test_citations_titles_models_and_body_not_removed(text):
    assert classify_node(node(text))["route"] == "semantic"


def test_table_and_generated_visual_description_are_not_reference_signature():
    assert classify_node(node(WANG, node_type="TABLE"))["route"] == "semantic"
    visual = {"members": [{"kind": "visual", "type": "description", "text": WANG}]}
    assert classify_node(visual)["route"] == "semantic"


def test_explicit_body_role_takes_precedence_over_text_guess():
    assert classify_node(node(WANG, layout_role="body_text"))["route"] == "semantic"


def test_exact_atom_mapping_and_mixed_content_are_auditable_without_mutation():
    original = node("Text with citation", source_atom_ids=["body"])
    before = copy.deepcopy(original)
    rep = {"atoms": [{"atom_id": "body", "layout_role": "body_text"}, {"atom_id": "ref", "layout_role": "reference"}]}
    assert classify_node(attach_source_roles(original, rep))["route"] == "semantic"
    assert original == before
    mixed = attach_source_roles(node("mixed", source_atom_ids=["body", "ref"]), rep)
    assert classify_node(mixed)["role"] == "mixed_bibliography"


def test_both_endpoint_orders_and_missing_node_are_checked():
    nodes = {"A": node("model description"), "B": node(HORE)}
    for a, b in [("A", "B"), ("B", "A"), ("A", "unknown")]:
        assert audit_edge({"source": a, "target": b}, nodes)["route"] == "reference_review"
    assert audit_edge({"source": "A", "target": "A"}, nodes)["route"] == "semantic"


def test_parser_para_role_and_partly_unresolved_source_atoms():
    assert classify_node(node(WANG, layout_role="para"))["route"] == "semantic"
    rep = {"atoms": [{"atom_id": "r", "layout_role": "reference"}]}
    attached = attach_source_roles(node("mixed", source_atom_ids=["r", "missing"]), rep)
    assert attached["source_role_unresolved_atom_ids"] == ["missing"]
    assert classify_node(attached)["role"] == "mixed_bibliography"


@pytest.mark.parametrize("text", [
    "The authors declare no competing interests.",
    "Disclosure: The authors have no potential conflicts of interest to disclose.",
    "Financial relationships: All authors have declared that they have no financial relationships at present or within the previous three years\nwith any organizations that might have an interest in the submitted work.",
    "Payment/services info: All authors have declared that no financial support was received from any organization for the submitted work.",
    "Human subjects: Informed consent for treatment and open access publication was obtained or waived by all participants in this study.",
    "The datasets used and/or analysed during the current study are available from the corresponding author on reasonable request.",
    "The authors declare no competing interests. This research did not receive funding.",
])
def test_only_complete_original_administrative_statements_route_to_review(text):
    original = node(text, source_atoms=[{"atom_id": "D1", "layout_role": "para"}])
    before = copy.deepcopy(original)
    result = classify_node(original)
    assert result["role"] == "administrative_boilerplate"
    assert result["route"] == "administrative_review"
    assert original == before


@pytest.mark.parametrize("text", [
    "No competing interests were associated with lower mortality in the study.",
    "Our model detects conflicts of interest in scientific publications.",
    "The authors declare no competing interests. The implant height is 5 mm.",
    "The authors declare no competing interests, and our method improves accuracy.",
    "The authors declare no competing interests; the experiment reached 95% accuracy.",
    "Informed consent was obtained from 95% of participants.",
    "Informed consent was obtained before measuring treatment effects of 15 mg.",
    "Digital informed consent was obtained before accessing the questionnaire. We evaluated a new consent protocol.",
    "The datasets used and/or analysed during the current study are available from the corresponding author on reasonable request. Their median age was 42 years.",
    "The authors declare no competing interests because the intervention was effective.",
    "The authors declare no competing interests. See Figure 3 for our results.",
])
def test_mixed_science_and_keywords_do_not_trigger_administrative_routing(text):
    assert classify_node(node(text, layout_role="para"))["route"] == "semantic"


def test_administrative_requires_every_original_member_and_excludes_generated():
    declaration = "The authors declare no competing interests."
    mixed = node(declaration)
    mixed["members"].append({"id": "result", "kind": "atom", "type": "text", "text": "Our method improved accuracy by 12%."})
    assert classify_node(mixed)["route"] == "semantic"
    for kind, typ in [("visual", "description"), ("atom", "description"), ("generated", "text")]:
        generated = {"members": [{"kind": kind, "type": typ, "text": declaration}]}
        assert classify_node(generated)["route"] == "semantic"
    marked = node(declaration)
    marked["members"][0]["generated"] = True
    assert classify_node(marked)["route"] == "semantic"
    assert classify_node({"text": declaration})["route"] == "semantic"
    for modality in ("TABLE", "FORMULA", "HYBRID"):
        assert classify_node(node(declaration, node_type=modality))["route"] == "semantic"


def test_administrative_edge_routes_are_order_independent_with_reference_priority():
    nodes = {"admin": node("The authors declare no competing interests."),
             "body": node("The implant height is 5 mm."), "ref": node(HORE)}
    for source, target in (("admin", "body"), ("body", "admin"), ("admin", "admin")):
        result = audit_edge({"source": source, "target": target}, nodes)
        assert result["route"] == "administrative_review"
        assert result["role"] == "administrative_related"
        assert "administrative_boilerplate" in " ".join(result["reasons"])
    assert audit_edge({"source": "admin", "target": "ref"}, nodes)["route"] == "reference_review"
    assert audit_edge({"source": "admin", "target": "unknown"}, nodes)["route"] == "reference_review"
    # Exact parser reference provenance outranks the statement-shape heuristic.
    assert classify_node(node("The authors declare no competing interests.", layout_role="reference"))["route"] == "reference_review"
