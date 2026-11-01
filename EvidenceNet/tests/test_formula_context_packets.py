import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from formula_context_packets import build_packet, literal_symbols


def fixture():
    texts = [
        ("intro", "para", r"The input $X$ is projected to latent subspaces. The query $Q$, key $K$ and value $V$ subspaces are trained for each node."),
        ("q", "equ", r"$$Q=XW_q$$"),
        ("k", "equ", r"$$K=XW_k$$"),
        ("v", "equ", r"$$V=XW_v$$"),
        ("definition", "para", r"Here, $W_q$, $W_k$ and $W_v$ are the weight matrices for $Q$, $K$ and $V$, respectively. Table 11 shows the prediction scores."),
    ]
    nodes = {nid: dict(id=nid, article_id="doc::paper", document="doc", page=1,
                      members=[dict(id="m", kind="atom", role=role, text=text)]) for nid, role, text in texts}
    policies = {nid: dict(members=[dict(member_id="m", kind="atom", eligible=True)]) for nid in nodes}
    reading = [dict(source=a[0], target=b[0], type="NEXT") for a, b in zip(texts, texts[1:])]
    return nodes, policies, reading


def assert_source_spans(packet, nodes):
    for span in packet["formula_sources"] + packet["contexts"]:
        member = next(m for m in nodes[span["source_node_id"]]["members"] if m["id"] == span["member_id"])
        assert span["quote"] == member["text"][span["char_start"]:span["char_end"]]
        assert span["member_sha256"] == hashlib.sha256(member["text"].encode()).hexdigest()


def test_formula_group_collects_actual_key_definitions_without_qv_as_context():
    nodes, policies, reading = fixture()
    packet = build_packet("k", nodes, policies, reading)
    assert packet["status"] == "ready"
    assert {s["source_node_id"] for s in packet["contexts"]} == {"intro", "definition"}
    assert any(s["path"] == ["k", "q", "intro"] for s in packet["contexts"])
    assert any(s["path"] == ["k", "v", "definition"] for s in packet["contexts"])
    assert all("Table 11" not in s["quote"] for s in packet["contexts"])
    assert_source_spans(packet, nodes)


def test_branch_is_not_resolved_by_arbitrary_sort_order():
    nodes, policies, reading = fixture()
    reading.append(dict(source="definition", target="k", type="NEXT"))
    packet = build_packet("k", nodes, policies, reading)
    assert not any(s["route"] == "group_previous_definition" for s in packet["contexts"])
    assert any(o["reason"] == "ambiguous_next" for o in packet["omissions"])


def test_cross_page_article_and_non_next_links_are_not_used():
    nodes, policies, reading = fixture()
    nodes["intro"]["page"] = 0
    nodes["definition"]["article_id"] = "different"
    reading += [dict(source="intro", target="k", type="RELATED"), dict(source="k", target="definition", type="PREVIOUS")]
    packet = build_packet("k", nodes, policies, reading)
    assert packet["contexts"] == []
    assert {o["reason"] for o in packet["omissions"]} >= {"page_boundary", "document_or_article_boundary"}


def test_other_formulas_are_not_borrowed_and_where_ends_before_background():
    nodes, policies, reading = fixture()
    nodes["k"]["members"][0]["text"] = r"$$MAPE=|y-\hat y|/y$$"
    nodes["q"]["members"][0]["text"] = r"$$MAE=|y-\hat y|$$"
    nodes["definition"]["members"][0]["text"] = r"where $y$ denotes the true values. A lower RMSE indicates better prediction. Table 11 presents results."
    packet = build_packet("k", nodes, policies, reading)
    assert [s["quote"] for s in packet["contexts"]] == [r"where $y$ denotes the true values."]
    assert_source_spans(packet, nodes)


def test_raw_crlf_and_symbols_are_preserved_and_budget_never_cuts_a_sentence():
    nodes, policies, reading = fixture()
    nodes["definition"]["members"][0]["text"] = "  Here, $W_k$ is the learnable\r\nweight matrix for $K$."
    packet = build_packet("k", nodes, policies, reading, max_context_records=1)
    span = packet["contexts"][0]
    assert "\r\n" in span["quote"] and span["char_start"] == 2
    assert_source_spans(packet, nodes)
    tiny = build_packet("k", nodes, policies, reading, max_context_chars=10)
    assert tiny["contexts"] == []
    assert any(o["reason"] == "context_budget_stop_no_truncation" for o in tiny["omissions"])


def test_unknown_article_half_paragraph_and_skipped_formula_budget_stop():
    nodes, policies, reading = fixture()
    nodes["definition"]["members"][0]["role"] = "half_para"
    packet = build_packet("k", nodes, policies, reading, max_formula_steps=0)
    assert packet["contexts"] == []
    assert any(o["reason"] == "formula_group_step_budget" for o in packet["omissions"])
    packet = build_packet("k", nodes, policies, reading)
    assert not any(s["source_node_id"] == "definition" for s in packet["contexts"])
    assert any(o["reason"] == "incomplete_member_no_cross_page_repair" for o in packet["omissions"])
    nodes["k"]["article_id"] = "UNRESOLVED_PAGE_BUCKET"
    assert build_packet("k", nodes, policies, reading)["status"] == "unresolved_article"


def test_tex_array_alignment_is_not_a_variable():
    assert literal_symbols(r"$$\begin{array} { r l } & K=X W_k\end{array}$$", formula=True) == ["K", "W", "X", "k"]


def test_same_node_definition_remains_endpoint_owned():
    nodes, policies, reading = fixture()
    nodes['k']['members'].append(dict(id='definition',kind='atom',role='para',text=r'Here, $W_k$ is the weight matrix for $K$.'))
    policies['k']['members'].append(dict(member_id='definition',kind='atom',eligible=True))
    packet=build_packet('k',nodes,policies,reading)
    own=next(s for s in packet['contexts'] if s['route']=='same_node_definition')
    assert own['context_is_endpoint_content'] and own['kind']=='ORIGINAL_TEXT'
