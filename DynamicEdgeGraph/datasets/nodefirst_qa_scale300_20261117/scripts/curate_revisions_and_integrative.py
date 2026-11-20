#!/usr/bin/env python3
"""Revise snapshot-B drafts and add manually grounded integrative candidates.

All outputs are additive.  The original generated JSONL and canonical snapshot
remain untouched.
"""

import copy
import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
SOURCE = OUT / "qa_candidate_drafts_snapshot_B_short.jsonl"
NODE_SOURCE = OUT / "snapshot_B_short_canonical_nodes.jsonl"


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_jsonl(path, values):
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


NODES = {node["canonical_node_id"]: node for node in load_jsonl(NODE_SOURCE)}


def corrected_node(node_id, replacements, reason):
    node = copy.deepcopy(NODES[node_id])
    before = node["content_text"]
    after = before
    for old, new in replacements:
        if old not in after:
            raise ValueError(f"Correction source text not found in {node_id}: {old}")
        after = after.replace(old, new)
    node["content_text"] = after
    node["source_integrity_status"] = "SOURCE_INTEGRITY_PASS_PAGE_IMAGE_CORRECTED"
    node["correction"] = {
        "method": "PAGE_IMAGE_VISUAL_TRANSCRIPTION",
        "reason": reason,
        "original_content_text": before,
        "page_image": node["page_image"],
    }
    return node


CORRECTIONS = {
    "short_014_getty_magazine_winter_2024_page_0017_EU_007": corrected_node(
        "short_014_getty_magazine_winter_2024_page_0017_EU_007",
        [("First Come a Friendship", "First Came a Friendship"), ("Naoka Takahate", "Naoko Takahatake")],
        "Dolphin OCR omitted letters in the exhibition title and curator name; both are legible on the page image.",
    ),
    "short_014_getty_magazine_winter_2024_page_0022_EU_008": corrected_node(
        "short_014_getty_magazine_winter_2024_page_0022_EU_008",
        [("HBCCU", "HBCU"), ("photo- graphs", "photograph")],
        "Dolphin OCR inserted a duplicated C and retained line-break hyphenation; the page image reads HBCU and photograph.",
    ),
}


def node(node_id):
    return CORRECTIONS.get(node_id, NODES[node_id])


def evidence(node_ids):
    result = []
    for index, node_id in enumerate(node_ids):
        source = node(node_id)
        result.append(
            {
                "evidence_index": index,
                "canonical_node_id": source["canonical_node_id"],
                "evidence_unit_id": source["evidence_unit_id"],
                "document_id": source["document_id"],
                "page_id": source["page_id"],
                "page_number": source["page_number"],
                "node_type": source["node_type"],
                "evidence_text": source["content_text"],
                "bbox": source.get("bbox"),
                "source_json": source.get("source_json"),
                "page_image": source.get("page_image"),
                "source_corpus": source["source_corpus"],
                "source_integrity_status": source["source_integrity_status"],
            }
        )
    return result


def claims(node_ids, specifications):
    output = []
    for claim_index, specification in enumerate(specifications, 1):
        claim_text, supports = specification
        spans = []
        support_indices = []
        for evidence_index, texts in supports:
            support_indices.append(evidence_index)
            content = node(node_ids[evidence_index])["content_text"]
            for text in texts:
                start = content.find(text)
                if start < 0:
                    raise ValueError(f"Literal span not found in {node_ids[evidence_index]}: {text}")
                spans.append(
                    {
                        "evidence_index": evidence_index,
                        "canonical_node_id": node_ids[evidence_index],
                        "text": text,
                        "char_start": start,
                        "char_end": start + len(text),
                    }
                )
        output.append(
            {
                "claim_id": f"c{claim_index}",
                "claim_text": claim_text,
                "supporting_evidence_indices": sorted(set(support_indices)),
                "evidence_spans": spans,
            }
        )
    return output


def replace_draft(originals, draft_id, question, answer, node_ids, claim_specs, reasoning, bridge, reason):
    revised = copy.deepcopy(originals[draft_id])
    revised["question"] = question
    revised["gold_answer_draft"] = answer
    revised["gold_evidence_draft"] = evidence(node_ids)
    revised["answer_claims"] = claims(node_ids, claim_specs)
    revised["reasoning_type"] = reasoning
    revised["bridge_relation"] = bridge
    revised["revision"] = {
        "version": 2,
        "supersedes": "qa_candidate_drafts_snapshot_B_short.jsonl",
        "reason": reason,
        "preserved_full_draft_id": True,
    }
    revised["review"] = {"status": "PENDING_INDEPENDENT_MODEL_REVIEW_V2"}
    revised["generation_node_necessity"] = [
        {
            "evidence_index": index,
            "canonical_node_id": node_id,
            "missing_claim_ids": [
                claim["claim_id"]
                for claim in revised["answer_claims"]
                if index in claim["supporting_evidence_indices"]
            ],
            "why_answer_incomplete_without_node": "The listed claim support would be unavailable after deleting this node.",
        }
        for index, node_id in enumerate(node_ids)
    ]
    return revised


def revise_existing():
    rows = load_jsonl(SOURCE)
    originals = {row["draft_id"]: row for row in rows}
    changes = {}

    def revise(short_id, *args):
        full_id = f"scale300_snapshot_b::{short_id}"
        changes[full_id] = replace_draft(originals, full_id, *args)

    revise(
        "0002",
        "What did photographer Charles Williamson and the Brooklyn Atlantics do in 1865 to produce what is considered the earliest known baseball card?",
        "Charles Williamson made the Atlantics' team portrait in 1865; the team mounted the image on cards and handed them to fans and opposing teams. The resulting card is considered the earliest known baseball card in existence.",
        ["short_012_library_of_congress_magazine_jul_aug_2024_page_0012_EU_006"],
        [
            ("Charles Williamson made the team portrait in 1865.", [(0, ["Photographer Charles Williamson made this team portrait in 1865"])]),
            ("The Atlantics mounted the image on cards and distributed them to fans and opposing teams.", [(0, ["The Atlantics mounted the image on cards and handed them out to fans and to opposing teams"])]),
            ("The card is considered the earliest known baseball card in existence.", [(0, ["The card today is considered the earliest known baseball card in existence"])]),
        ],
        "single_node_chronological_causal_chain",
        "portrait_creation_to_card_distribution_to_historical_status",
        "Added missing claim-level support for the photographer and year.",
    )
    revise(
        "0008",
        "What is the title of the Getty Research Institute exhibition featuring Sidney B. Felsen's photographs, and who curated it?",
        "The exhibition is titled “First Came a Friendship: Sidney B. Felsen and the Artists at Gemini G.E.L.” and was curated by Naoko Takahatake.",
        ["short_014_getty_magazine_winter_2024_page_0017_EU_007"],
        [
            ("The exhibition is titled First Came a Friendship: Sidney B. Felsen and the Artists at Gemini G.E.L.", [(0, ["First Came a Friendship: Sidney B. Felsen and the Artists at Gemini G.E.L."])]),
            ("Naoko Takahatake curated the exhibition.", [(0, ["curated by Naoko Takahatake"])]),
        ],
        "single_node_entity_extraction",
        "page_image_corrected_title_and_curator",
        "Corrected two OCR errors against the page image.",
    )
    revise(
        "0011",
        "What is the title of the USGS project concerning peat rewetting with saltwater at Duck Harbor, Massachusetts?",
        "The project is titled “Geochemical Changes from Peat Rewetting with Saltwater at Duck Harbor, MA.”",
        ["short_007_usgs_woods_hole_coastal_annual_report_2024_page_0011_EU_020"],
        [("The project title is Geochemical Changes from Peat Rewetting with Saltwater at Duck Harbor, MA.", [(0, ["Project title: Geochemical Changes from Peat Rewetting with Saltwater at Duck Harbor, MA"])])],
        "single_node_entity_extraction",
        "topic_specific_project_title",
        "Made the question self-contained instead of referring generically to the document.",
    )
    revise(
        "0019",
        "After 56 years of writing songs with Bernie Taupin, how did Elton John characterize the recognition bestowed on them as a songwriting partnership?",
        "He called it extraordinary, incredible and overwhelming, and said it was probably the biggest honor they had ever received as a songwriting partnership.",
        ["short_008_library_of_congress_magazine_mar_apr_2024_page_0030_EU_003"],
        [
            ("Elton John described the recognition as extraordinary, incredible and overwhelming.", [(0, ["Quite extraordinary!", "It's an incredible honor", "It's quite overwhelming"])]),
            ("He called it probably their biggest honor as a songwriting partnership.", [(0, ["probably the biggest honor we've ever been given as a songwriting partnership"])]),
        ],
        "single_node_attitude_summary",
        "long_partnership_to_characterization_of_recognition",
        "Specified the subject and removed the vague phrase 'being recognized'.",
    )
    revise(
        "0023",
        "How was “Fear of a Black Planet” characterized in relation to Public Enemy's touring experience and its musical form?",
        "It was described as a statement about the hip-hop the group saw and heard around the world while touring, and as their dissertation of rap words and beats.",
        ["short_012_library_of_congress_magazine_jul_aug_2024_page_0030_EU_007"],
        [
            ("The album was a statement about hip-hop encountered around the world while touring.", [(0, ["“Fear of a Black Planet” was our statement about the hip-hop we saw and heard around the world when we toured"])]),
            ("The album was described as a dissertation of rap words and beats.", [(0, ["It’s our dissertation of rap words and beats"])]),
        ],
        "single_node_characterization",
        "touring_observation_to_album_statement",
        "Removed the unidentified 'artist' reference while retaining the album-specific question.",
    )
    revise(
        "0026",
        "What conservation skills do undergraduate HBCU students practice during Getty's five-day Johnson Publishing Company archive workshop?",
        "They learn to identify photographic processes, assess photograph condition and perform entry-level treatments such as surface cleaning, under the guidance of expert photograph conservators.",
        ["short_014_getty_magazine_winter_2024_page_0022_EU_008"],
        [
            ("Students learn to identify photographic processes.", [(0, ["how to identify photographic processes"])]),
            ("Students learn to assess the condition of photographs.", [(0, ["assess the condition of photographs"])]),
            ("Students perform entry-level treatments such as surface cleaning.", [(0, ["perform entry-level treatments such as surface cleaning"])]),
            ("Expert photograph conservators guide the work.", [(0, ["under the guidance of expert photograph conservators"])]),
        ],
        "single_node_procedural_summary",
        "workshop_to_specific_conservation_skills",
        "Corrected HBCU and line-break OCR errors against the page image.",
    )
    revise(
        "0028",
        "What did the organizers of the photographic display at the 1900 Paris fair want international visitors to understand about Black Americans?",
        "They wanted visitors to understand that, roughly three decades after gaining freedom, Black Americans were making vast intellectual and social gains.",
        ["short_013_library_of_congress_magazine_nov_dec_2024_page_0023_EU_006"],
        [
            ("The organizers wanted international visitors to see the display's message.", [(0, ["They wanted to show the world – or at least the international visitors to the fair"])]),
            ("The message was that Black Americans were making vast intellectual and social gains after gaining freedom.", [(0, ["three decades and change after gaining their freedom. Black Americans were making vast intellectual and social gains"])]),
        ],
        "single_node_intent_and_message",
        "organizers_intent_to_historical_claim",
        "Replaced the unidentified exhibition fragment with a self-contained node and question.",
    )
    revise(
        "0044",
        "Who created the rare portolan depicting the East Coast of North America, approximately when was it made, and when did the Library acquire it?",
        "Portuguese cartographer Bartolomeu Velho created it around 1560, and the Library acquired it the year before the article was published.",
        ["short_013_library_of_congress_magazine_nov_dec_2024_page_0008_EU_005"],
        [
            ("Bartolomeu Velho created the portolan around 1560.", [(0, ["Portuguese cartographer Bartolomeu Velho created the map – an early nautical chart, or portolan – around 1560"])]),
            ("The Library acquired it the previous year.", [(0, ["the Library acquired it last year"])]),
        ],
        "single_node_provenance",
        "creator_date_and_acquisition",
        "Replaced an unresolved pronoun with a self-contained provenance question.",
    )
    revise(
        "0045",
        "What activities does support from Friends of the Library fund, and what is Peter Durkin's favorite benefit of membership?",
        "It funds free public programming, new collections and innovations such as an online civic-engagement game; Durkin's favorite benefit is the special events.",
        ["short_008_library_of_congress_magazine_mar_apr_2024_page_0029_EU_006"],
        [
            ("Friends support funds public programming, collections and innovative ideas.", [(0, ["goes to free public programming, new collections and innovative ideas like a new online game to encourage civic engagement"])]),
            ("Peter Durkin's favorite membership benefit is special events.", [(0, ["Durkin's favorite part of being a Library Friend is the special events"])]),
        ],
        "single_node_membership_benefits",
        "funding_uses_and_member_benefit",
        "Replaced the unidentified individual with a node that names Durkin and gives a complete answer.",
    )
    revise(
        "0047",
        "Which responsibilities does the lead writer-editor directly oversee, and what additional production work is shared by the six-person Publishing Office?",
        "The lead directly oversees editorial output by developing production schedules, ensuring deadlines and reviewing prepublication text. The six-person staff collectively develops ideas and proposals, conducts archival research, edits text, secures permissions, arranges scanning and works with designers and marketing.",
        ["short_013_library_of_congress_magazine_nov_dec_2024_page_0011_EU_003"],
        [
            ("The lead oversees schedules, deadlines and prepublication review.", [(0, ["I oversee our editorial output, such as developing production schedules, ensuring we meet deadlines and reviewing all prepublication text"])]),
            ("The six-person staff collectively handles the broader production tasks.", [(0, ["With just six staff members, we all contribute", "This includes developing ideas, writing proposals, conducting archival research, editing text, securing permissions, arranging scanning, working with designers and marketing"])]),
        ],
        "single_node_role_partition",
        "individual_oversight_vs_team_work",
        "Corrected the prior answer's attribution of team-wide tasks to one role.",
    )
    revise(
        "0053",
        "What is the Edith Book of Hours?",
        "It is a handwritten 14th-century volume of prayers and a remarkably small object.",
        ["short_008_library_of_congress_magazine_mar_apr_2024_page_0010_EU_006"],
        [
            ("The Edith Book of Hours is a handwritten 14th-century volume of prayers.", [(0, ["The Edith Book of Hours, a handwritten 14th-century volume of prayers"])]),
            ("Its small size prompts viewers to wonder how it was made.", [(0, ["How could anyone create something that small?"])]),
        ],
        "single_node_definition",
        "named_object_to_description",
        "Replaced the unidentified 'book' reference with a fully named object.",
    )
    revise(
        "0057",
        "What two benefits can come from selecting workshop staff who are located near the meeting site?",
        "It can reduce the budget, and nearby staff may be more aware of local needs and concerns.",
        ["short_011_participatory_mapping_ocean_uses_noaa_page_0013_EU_001"],
        [
            ("Selecting nearby staff can reduce the budget.", [(0, ["cut back on the budget"])]),
            ("Nearby staff may be more aware of local needs and concerns.", [(0, ["may be more aware of local needs and concerns"])]),
        ],
        "single_node_benefit_summary",
        "proximity_to_cost_and_local_knowledge",
        "Restored the source's uncertainty instead of changing 'may' to 'ensures'.",
    )

    revised_rows = []
    diffs = []
    for row in rows:
        revised = changes.get(row["draft_id"], copy.deepcopy(row))
        if row["draft_id"] not in changes:
            revised["revision"] = {"version": 2, "change": "UNCHANGED_AFTER_CONTENT_AUDIT"}
            revised["review"] = {"status": "PENDING_INDEPENDENT_MODEL_REVIEW_V2"}
        else:
            diffs.append(
                {
                    "draft_id": row["draft_id"],
                    "old_question": row["question"],
                    "new_question": revised["question"],
                    "old_answer": row["gold_answer_draft"],
                    "new_answer": revised["gold_answer_draft"],
                    "reason": revised["revision"]["reason"],
                }
            )
        revised_rows.append(revised)
    return revised_rows, diffs


def integrative_candidate(candidate_id, category, node_ids, question, answer, claim_specs, reasoning, bridge, necessity):
    documents = {node(node_id)["document_id"] for node_id in node_ids}
    pages = {(node(node_id)["document_id"], node(node_id)["page_id"]) for node_id in node_ids}
    if category == "cross_page" and not (len(documents) == 1 and len(pages) > 1):
        raise ValueError(f"Bad cross-page category: {candidate_id}")
    if category == "cross_document" and len(documents) < 2:
        raise ValueError(f"Bad cross-document category: {candidate_id}")
    answer_claims = claims(node_ids, claim_specs)
    deletion = []
    for index, node_id in enumerate(node_ids):
        missing = [claim["claim_id"] for claim in answer_claims if index in claim["supporting_evidence_indices"]]
        if not missing:
            raise ValueError(f"Node is not claim-necessary in {candidate_id}: {node_id}")
        deletion.append(
            {
                "evidence_index": index,
                "canonical_node_id": node_id,
                "node_required": True,
                "missing_claim_ids": missing,
                "why_answer_incomplete_without_node": necessity[index],
            }
        )
    return {
        "draft_id": candidate_id,
        "snapshot_id": "snapshot_B_short_job135007_20261117",
        "qa_category": category,
        "cross_document_subtype": (
            "three_plus_doc" if category == "cross_document" and len(documents) >= 3 else "two_doc" if category == "cross_document" else None
        ),
        "question": question,
        "gold_answer_draft": answer,
        "reasoning_type": reasoning,
        "bridge_relation": bridge,
        "gold_evidence_draft": evidence(node_ids),
        "answer_claims": answer_claims,
        "generation_node_necessity": deletion,
        "discovery": {
            "method": "MANUAL_ENTITY_PROCESS_AND_DECISION_DIMENSION_SEARCH",
            "lexical_overlap_alone_sufficient": False,
        },
        "review": {"status": "PENDING_INDEPENDENT_MODEL_REVIEW"},
    }


def build_integrative():
    candidates = []
    add = candidates.append
    add(integrative_candidate(
        "scale300_integrative_v1::cp001", "cross_page",
        ["short_011_participatory_mapping_ocean_uses_noaa_page_0009_EU_003", "short_011_participatory_mapping_ocean_uses_noaa_page_0010_EU_001"],
        "How does NOAA's participatory GIS process turn use areas mapped during workshops into reviewed and published final products?",
        "During workshops, participants map use-area polygons in facilitated groups and refine the patterns through discussion. Afterwards, the breakout-group data are compiled and processed into a layer for each use, checked against workshop notes, returned to participants for review, revised in response to comments, and published as final GIS data, metadata, maps and analytical products.",
        [
            ("Participants map use-area polygons in facilitated workshop groups and refine them through discussion.", [(0, ["participants are briefed on the objectives and equipment, separated into groups, and assigned the task of mapping ocean uses as a team", "participants are asked to draw use-area polygons directly onto the projected map", "refine ocean use patterns through group discussion and deliberation"])]),
            ("After the workshops, data are compiled and processed into a layer for each use.", [(1, ["the data from the breakout groups are compiled, reviewed, and processed to create a unique data layer for each use"])]),
            ("Participants review draft maps before final products are published.", [(1, ["draft data and maps are returned to the workshop participants for review and feedback", "The final versions of the GIS data, metadata, maps, and related analytical products are then compiled and published online"])]),
        ],
        "process_chain_across_pages", "workshop_capture_to_validation_and_publication",
        ["The answer would omit how use areas are initially mapped and refined.", "The answer would omit validation, participant review and final publication."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cp002", "cross_page",
        ["short_004_healthy_brain_planning_guide_cdc_2024_page_0005_EU_013", "short_004_healthy_brain_planning_guide_cdc_2024_page_0017_EU_001"],
        "In the dementia action-planning guide, how are partners distinguished from stakeholders, and how does the guide suggest prioritizing partner engagement over time?",
        "Partners are people or organizations likely to participate directly or supply support such as funding, venues, airtime or materials, whereas stakeholders may be affected by dementia without direct involvement. The Stakeholder Analysis Matrix is then used to prioritize whom to engage during planning and whom to mobilize later.",
        [
            ("Partners are likely to participate directly or provide concrete support.", [(1, ["Partners would be organizations or persons who would likely be involved or provide other support, such as funding, a venue, radio show, or supplies"])]),
            ("Stakeholders may be affected without being directly involved.", [(1, ["Stakeholders would be organizations, groups of people, or influential persons who may be affected by Alzheimer's and dementia, but may not be directly involved"])]),
            ("The matrix prioritizes engagement now versus later mobilization.", [(0, ["may help you prioritize partners to engage now in the planning stage and others to mobilize at a later stage"])]),
        ],
        "definition_to_planning_action_across_pages", "role_distinction_to_staged_engagement",
        ["The answer would lose the operational use of the prioritization matrix.", "The answer would lose the distinction between partners and stakeholders."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cp003", "cross_page",
        ["short_016_biodiversity_data_standards_arxiv_2024_page_0017_EU_001", "short_016_biodiversity_data_standards_arxiv_2024_page_0018_EU_001"],
        "What two mechanisms can expand the information supported by an existing biodiversity-data core, and at what governance level does each operate?",
        "One mechanism updates the standard core itself through standards governance and ratification, increasing its terms for all adopters. The other leaves the ratified core unchanged and adds an optional extension at the individual database or infrastructure level, allowing additional data to integrate with the original core.",
        [
            ("A standards-governance update expands the ratified core itself.", [(0, ["at the level of the data standards governance", "The number of terms in a standard core can be increased through an update of the existing standard core"])]),
            ("A database-level extension adds optional standards without modifying the ratified core.", [(1, ["does not modify a ratified data standard", "applied at the level of an individual database or data infrastructure", "including a new optional set of data standards to the existing database, which is referred to as an extension"])]),
        ],
        "alternative_mechanism_comparison_across_pages", "governance_update_vs_database_extension",
        ["The answer would omit the governance-level option that changes the standard core.", "The answer would omit the database-level extension that preserves the ratified core."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cp004", "cross_page",
        ["short_013_library_of_congress_magazine_nov_dec_2024_page_0008_EU_005", "short_013_library_of_congress_magazine_nov_dec_2024_page_0008_EU_007", "short_013_library_of_congress_magazine_nov_dec_2024_page_0009_EU_004"],
        "How did the physical condition of Bartolomeu Velho's circa-1560 portolan at rediscovery contrast with the way the Library later made its hidden details accessible?",
        "Bartolomeu Velho created the portolan around 1560. When it was found in 1961, it had been cut into quarters and repurposed for its vellum. Later, Preservation Research and Testing specialists used innovative imaging to uncover chart details, and the Geography and Map Division published the enhanced high-resolution image online.",
        [
            ("Bartolomeu Velho created the portolan around 1560.", [(0, ["Portuguese cartographer Bartolomeu Velho created the map – an early nautical chart, or portolan – around 1560"])]),
            ("The rediscovered portolan was no longer intact because it had been quartered and repurposed.", [(1, ["It was found in 1961 at Rye Castle Museum in Sussex, England", "the portolan no longer was intact: It had been cut into quarters and repurposed for its vellum"])]),
            ("Imaging uncovered details and an enhanced high-resolution version was made available online.", [(2, ["PRTD specialists employed innovative imaging techniques to uncover details in the chart", "Geography and Map enabled access to the work on loc.gov", "a high-resolution image enhanced by PRTD has been shared on the public website"])]),
        ],
        "condition_to_preservation_access_across_pages", "damaged_artifact_to_noninvasive_digital_access",
        ["The answer would not establish which portolan the question concerns or its date and creator.", "The answer would omit the artifact's damaged physical state at rediscovery.", "The answer would omit the imaging and public-access response."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cp005", "cross_page",
        ["short_003_governing_with_ai_oecd_2024_page_0007_EU_001", "short_003_governing_with_ai_oecd_2024_page_0019_EU_004"],
        "Why is continuing impact monitoring necessary for public-sector AI, and what institutional gap makes that requirement difficult to implement?",
        "Public-sector AI failures show that governments need to assess, test and monitor impacts, including unequal effects on marginalized groups, so that risks and harms can be managed. Yet most countries still find it difficult to establish transparency, monitoring and oversight mechanisms, even though monitoring policy effectiveness is crucial for trust and long-term sustainability.",
        [
            ("Failures create a need to assess, test and monitor public impacts and distributional risks.", [(0, ["AI failures in the public sector have highlighted the need for governments to assess, test, and monitor AI’s impacts on the public", "consider how AI systems may affect men, women or marginalized communities differently"])]),
            ("Monitoring policy effectiveness supports trust and sustainability, but mechanisms remain difficult to establish.", [(1, ["monitoring the effectiveness of policies for AI in the public sector and assessing their implementation and impact is crucial to foster trust, and ensure their long-term sustainability", "setting-up transparency, monitoring and oversight mechanisms on AI in the public sector remains a challenge in most countries"])]),
        ],
        "risk_rationale_to_implementation_gap_across_pages", "observed_failures_to_monitoring_capacity_gap",
        ["The answer would omit why impact monitoring is substantively necessary.", "The answer would omit the institutional implementation gap and policy-level purpose."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cp006", "cross_page",
        ["short_006_tcfd_reporting_guide_2024_25_uk_treasury_page_0026_EU_004", "short_006_tcfd_reporting_guide_2024_25_uk_treasury_page_0027_EU_008"],
        "What two requirements connect an organization's greenhouse-gas disclosures to its material climate-risk management?",
        "The organization should disclose Scope 1 and Scope 2 emissions, and Scope 3 where appropriate, together with the related risks; its climate metrics should also be clearly traceable to the most material risks and opportunities identified in strategy and risk management.",
        [
            ("The disclosure covers Scope 1, Scope 2 and, where appropriate, Scope 3 emissions plus related risks.", [(0, ["Disclose Scope 1, Scope 2, if appropriate, Scope 3 greenhouse gas (GHG) emissions, and the related risks"])]),
            ("Climate metrics must be traceable to material risks and opportunities in strategy and risk management.", [(1, ["Climate-related metrics are clearly traceable to the most material climate-related risks and opportunities identified in strategy and risk management"])]),
        ],
        "reporting_requirement_synthesis_across_pages", "emissions_scope_to_material_risk_traceability",
        ["The answer would omit which emissions and associated risks must be disclosed.", "The answer would omit the required traceability from metrics to material risks and opportunities."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd001", "cross_document",
        ["short_009_preparing_strategic_plan_noaa_page_0005_EU_002", "short_010_writing_strategic_plan_noaa_page_0002_EU_003"],
        "How do NOAA's companion strategic-planning workbooks divide the work between gathering a foundation and turning it into a plan?",
        "Preparing to Write Your Strategic Plan supplies tools for gathering and analyzing the foundational information needed to understand direction and priorities. Writing Your Strategic Plan then uses that information to articulate a meaningful vision, focused goals and achievable objectives.",
        [
            ("The Preparing workbook gathers foundational information for direction and priorities.", [(0, ["provides tools to gather the information needed for the initial, or foundational, components of a strategic plan", "gathering and analyzing data and trends, setting direction"])]),
            ("The Writing workbook turns the foundation into vision, goals and objectives.", [(1, ["Writing Your Strategic Plan shows how to use this information to articulate meaningful vision statements, focused goals, and achievable objectives"])]),
        ],
        "sequential_companion_document_synthesis", "foundational_information_to_plan_articulation",
        ["The answer would omit what the first workbook gathers and why it is foundational.", "The answer would omit how the companion workbook converts the foundation into plan components."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd002", "cross_document",
        ["short_009_preparing_strategic_plan_noaa_page_0011_EU_007", "short_010_writing_strategic_plan_noaa_page_0013_EU_002"],
        "Which NOAA resource supports evaluation of a strategic plan, and why does the companion guidance say evaluation should be designed alongside implementation?",
        "NOAA's Planning for Meaningful Evaluation course is recommended for evaluating strategic-plan effectiveness. The companion guidance says evaluation and implementation planning should occur together because this makes both more efficient and effective and ensures performance measures are considered before implementation rather than added reactively.",
        [
            ("Planning for Meaningful Evaluation is the recommended course.", [(0, ["To evaluate the effectiveness of the strategic plan", "Planning for Meaningful Evaluation"])]),
            ("Evaluation should be designed with implementation to improve both and establish measures in advance.", [(1, ["Developing an evaluation plan in conjunction with implementation planning", "make both efforts more efficient and effective", "ensuring that performance measures are considered before implementation"])]),
        ],
        "resource_to_method_rationale_across_companion_documents", "named_evaluation_support_to_early_measure_design",
        ["The answer would omit the concrete NOAA evaluation resource.", "The answer would omit why evaluation must be planned before implementation."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd003", "cross_document",
        ["short_006_tcfd_reporting_guide_2024_25_uk_treasury_page_0005_EU_010", "short_015_economics_of_climate_adaptation_arxiv_2024_page_0007_EU_004"],
        "When reporting quantitative climate impacts under scenarios, what scenario context should be supplied and what limitation should qualify the estimates?",
        "The report should explain delivery and financial impacts under at least two climate scenarios, link them to programme prioritization and quantify where appropriate. The estimates should be qualified because the range of possible climate impacts exceeds what models can adequately quantify, and limitations in assumptions and data availability can make severe-impact estimates underestimates.",
        [
            ("Reporting should cover at least two scenarios, delivery and financial impacts, prioritization and appropriate quantification.", [(0, ["Explain impacts on delivery and finances under at least two climate scenarios; linking to programme prioritisation, and quantifying where appropriate"])]),
            ("Model estimates cannot capture the full range of impacts and may underestimate severe effects.", [(1, ["there is a wider range of possible impacts of climate change than are possible to adequately quantify and thus to incorporate into the model", "because of the limitations of models, with respect to assumptions and data availability, these are likely underestimates"])]),
        ],
        "reporting_guidance_to_evidence_limitation", "scenario_quantification_to_model_uncertainty",
        ["The answer would omit the required scenario and programme context for reporting.", "The answer would omit why numerical estimates require an uncertainty caveat."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd004", "cross_document",
        ["short_001_booster_seat_planning_guide_cdc_2024_page_0025_EU_005", "short_004_healthy_brain_planning_guide_cdc_2024_page_0005_EU_013"],
        "What complementary practices do two CDC planning guides recommend for building a diverse public-health coalition and deciding when to engage its members?",
        "The booster-seat guide recommends bringing together diverse groups around a consistent, data-driven message reinforced by personal stories. The dementia guide recommends including traditional and nontraditional partners and using a Stakeholder Analysis Matrix to prioritize partners for engagement during planning versus later mobilization.",
        [
            ("The booster-seat coalition should unite diverse groups around a consistent data-driven message and personal stories.", [(0, ["strong, collaborative partnerships with many diverse groups", "uniting behind a consistent message that is data driven and coupled with personal stories"])]),
            ("The dementia coalition should include traditional and nontraditional partners and stage their engagement.", [(1, ["Consider traditional and nontraditional partners so that engagement is inclusive", "prioritize partners to engage now in the planning stage and others to mobilize at a later stage"])]),
        ],
        "cross_program_planning_practice_synthesis", "coalition_message_alignment_to_staged_partner_engagement",
        ["The answer would omit how a diverse coalition aligns around evidence and messaging.", "The answer would omit inclusivity and the method for staging partner engagement."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd005", "cross_document",
        ["short_009_preparing_strategic_plan_noaa_page_0013_EU_003", "short_004_healthy_brain_planning_guide_cdc_2024_page_0005_EU_014", "short_001_booster_seat_planning_guide_cdc_2024_page_0035_EU_000"],
        "What combined checklist do the three planning guides provide for turning a public-health goal into an accountable action plan?",
        "First, express the objective in SMART terms: specific, measurable, audience- or issue-directed, realistic and ambitious, and time-bound. Next, set measurable goals, assign accountable people and partners, measure success and identify champions. Finally, list the concrete steps, who will perform each one, when it should be completed and what resources are needed.",
        [
            ("Objectives should satisfy the SMART criteria.", [(0, ["Objectives are SMART (specific, measurable, audience- or issue-directed, realistic and ambitious, and time-bound)"])]),
            ("The plan should assign accountability, measurement and champions.", [(1, ["identify some measurable goals. Assign accountable people, partners, and measure success. Identify champions"])]),
            ("The action plan should record steps, responsibility, completion timing and resources.", [(2, ["list each step, who is responsible, and a projected completion date", "Who will do this?", "When can this be completed?", "Resources needed?"])]),
        ],
        "three_document_operationalization_synthesis", "smart_objective_to_accountability_to_execution_fields",
        ["The answer would omit the quality criteria for the objective.", "The answer would omit accountability, success measurement and champions.", "The answer would omit the concrete execution fields required by the action-plan template."],
    ))
    add(integrative_candidate(
        "scale300_integrative_v1::cd006", "cross_document",
        ["short_006_tcfd_reporting_guide_2024_25_uk_treasury_page_0005_EU_008", "short_015_economics_of_climate_adaptation_arxiv_2024_page_0006_EU_003"],
        "Which operational metrics can help track adaptation exposure and spending, and what economic estimate illustrates why such investment may be worthwhile?",
        "The reporting guidance suggests metrics such as adaptation capital expenditure and estate flood-risk exposure. The economics review cites an estimate that investing $1.8 trillion globally in five adaptation domains could generate more than $7 trillion in net benefits, with reported cost-benefit ratios from 2:1 to 10:1.",
        [
            ("Operational reporting can track adaptation capital expenditure and estate flood-risk exposure.", [(0, ["adaptation capital expenditure, estate flood risk exposure"])]),
            ("A global adaptation estimate reported $1.8 trillion of investment and more than $7 trillion of net benefits.", [(1, ["calculates cost-benefit ratios from 2:1 to 10:1", "investing $1.8 trillion globally in just five domains", "could generate more than $7 trillion in net benefits"])]),
        ],
        "metric_to_investment_case_synthesis", "organizational_tracking_to_economic_rationale",
        ["The answer would omit the concrete operational metrics used to monitor adaptation exposure and spending.", "The answer would omit the quantitative economic evidence motivating adaptation investment."],
    ))
    return candidates


def validate(rows):
    audits = []
    seen_questions = set()
    for row in rows:
        reasons = []
        question_key = " ".join(row["question"].lower().split())
        if question_key in seen_questions:
            reasons.append("DUPLICATE_QUESTION")
        seen_questions.add(question_key)
        evidence_rows = row["gold_evidence_draft"]
        evidence_ids = {item["canonical_node_id"] for item in evidence_rows}
        covered = set()
        for item in evidence_rows:
            if item["canonical_node_id"] not in NODES and item["canonical_node_id"] not in CORRECTIONS:
                reasons.append("MISSING_CANONICAL_NODE")
        for claim in row["answer_claims"]:
            for span in claim["evidence_spans"]:
                source = node(span["canonical_node_id"])["content_text"]
                if source[span["char_start"] : span["char_end"]] != span["text"]:
                    reasons.append("LITERAL_OFFSET_MISMATCH")
                covered.add(span["canonical_node_id"])
        if covered != evidence_ids:
            reasons.append("NOT_ALL_EVIDENCE_CLAIM_COVERED")
        deletion = row.get("generation_node_necessity", [])
        if len(deletion) != len(evidence_rows) or any(not item.get("missing_claim_ids") for item in deletion):
            reasons.append("NODE_DELETION_TEST_INCOMPLETE")
        audits.append(
            {
                "draft_id": row["draft_id"],
                "source_mapping_gate": "PASS" if not reasons else "FAIL",
                "deterministic_claim_grounding_gate": "PASS" if not reasons else "FAIL",
                "reasons": reasons,
            }
        )
    return audits


def main():
    revised, diffs = revise_existing()
    integrative = build_integrative()
    audits = validate(revised + integrative)
    failed = [audit for audit in audits if audit["source_mapping_gate"] != "PASS"]
    if failed:
        raise RuntimeError(f"Deterministic validation failed: {failed}")
    save_jsonl(OUT / "snapshot_B_canonical_node_corrections_v2.jsonl", CORRECTIONS.values())
    save_jsonl(OUT / "qa_candidate_drafts_snapshot_B_short_revised_v2.jsonl", revised)
    save_jsonl(OUT / "qa_revision_diff_v2.jsonl", diffs)
    save_jsonl(OUT / "qa_integrative_candidates_curated_v1.jsonl", integrative)
    save_jsonl(OUT / "qa_revised_and_integrative_source_mapping_audit.jsonl", audits)
    summary = {
        "revised_dataset_count": len(revised),
        "changed_drafts": len(diffs),
        "unchanged_drafts": len(revised) - len(diffs),
        "canonical_node_page_image_corrections": len(CORRECTIONS),
        "integrative_candidate_count": len(integrative),
        "integrative_by_category": dict(Counter(row["qa_category"] for row in integrative)),
        "cross_document_subtypes": dict(Counter(row.get("cross_document_subtype") for row in integrative if row["qa_category"] == "cross_document")),
        "deterministic_source_mapping_pass": sum(audit["source_mapping_gate"] == "PASS" for audit in audits),
        "independent_model_review_status": "PENDING",
        "gold_export_status": "NOT_EXPORTED",
    }
    save_json(OUT / "qa_revision_and_integrative_summary_v1.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
