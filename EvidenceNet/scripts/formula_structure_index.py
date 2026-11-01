"""Conservative, query-free formula candidate signatures (not equivalence proofs).

The small ordered syntax tree intentionally does not simplify, commute products,
infer scalar/matrix types, or parse binders such as sums and integrals. Unknown
syntax has no index key. Consistent variable renaming is only a retrieval hint:
AB and BA are isomorphic until context anchors A and B to their semantic roles.
"""
import hashlib
import json
import re
from bisect import bisect_left
from collections import defaultdict


VERSION = "ordered-tex-subset-v1"
_FUNCTIONS = {"sin", "cos", "tan", "log", "ln", "exp", "softmax", "sigmoid", "ReLU", "relu", "max", "min", "det"}
_GREEK = set("alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi omicron pi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split())
_STYLES = {"mathbf", "boldsymbol", "mathbb", "mathcal", "mathsf", "mathit", "vec", "hat", "widehat", "bar", "tilde", "widetilde"}
_COMMAND_OPS = {"cdot": "cdot", "times": "times", "div": "/", "le": "<=", "leq": "<=", "ge": ">=", "geq": ">=", "neq": "!=", "approx": "approx", "equiv": "equiv"}
_RELATIONS = {"=", "<", ">", "<=", ">=", "!=", "approx", "equiv"}
_TOKEN = re.compile(r"\\[A-Za-z]+|\\[^A-Za-z]|(?:\d+(?:\.\d+)?|\.\d+)|[A-Za-z]|[{}()\[\]+\-*/=<>^_|,]")


class Unsupported(ValueError):
    pass


def _tokens(latex):
    if not isinstance(latex, str) or not latex.strip():
        raise Unsupported("empty_or_non_string_formula")
    source = latex.strip()
    for opening, closing in (("$$", "$$"), ("$", "$"), (r"\[", r"\]"), (r"\(", r"\)")):
        if source.startswith(opening) and source.endswith(closing):
            source = source[len(opening):-len(closing)].strip()
            break
    # Equation labels are not mathematical factors. Do not guess whether an
    # OCR trailing '(8)' after a spacing command is an annotation or an operand.
    if re.search(r"\\(?:quad|qquad)\s*\(\s*\d[\d\s.]*\)\s*$", source):
        raise Unsupported("ambiguous_trailing_equation_number")
    # OCR often prints 's o f t m a x' as bare letters. Treating that as seven
    # multiplied variables would produce a misleading supported signature.
    # Explicit supported TeX function commands/roman labels are exempt.
    visible = re.sub(r"\\(?:operatorname|mathrm)\s*\{[^{}]*\}|\\[A-Za-z]+", " ", source)
    word_labels = {"attention", "head", "RMSE", "MAPE", "MAE", "MHSA", "MSE",
                   "accuracy", "precision", "recall", "NDVI", "NDWI", "EVI",
                   "TP", "TN", "FP", "FN", "spring", "damping", "res"}
    for word in sorted(_FUNCTIONS | word_labels):
        pattern = r"(?<![A-Za-z\\])" + r"\s*".join(word) + r"(?![A-Za-z])"
        flags = 0 if word in {"TP", "TN", "FP", "FN"} else re.IGNORECASE
        if re.search(pattern, visible, flags=flags):
            raise Unsupported("ambiguous_unmarked_word_%s" % word)
    source = re.sub(r"\\(?:left|right)\b", "", source)
    source = re.sub(r"\\(?:quad|qquad)\b|\\[,!;: ]", " ", source)
    source = source.replace(r"\lVert", "‖").replace(r"\rVert", "‖").replace(r"\Vert", "‖").replace(r"\|", "‖")
    source = source.replace(r"\lvert", "|").replace(r"\rvert", "|").replace(r"\vert", "|")
    # Norm delimiters have an explicit token, distinct from absolute-value bars.
    result = []
    at = 0
    while at < len(source):
        if source[at].isspace():
            at += 1
            continue
        if source[at] == "‖":
            result.append("norm_bar")
            at += 1
            continue
        match = _TOKEN.match(source, at)
        if not match:
            raise Unsupported("unsupported_character_at_%d" % at)
        result.append(match.group())
        at = match.end()
    if len(result) > 2048:
        raise Unsupported("token_budget_exceeded")
    return result


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.at = 0

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise Unsupported("expected_%s_got_%s" % (expected or "token", token))
        self.at += 1
        return token

    def op(self):
        token = self.peek()
        if token and token.startswith("\\"):
            return _COMMAND_OPS.get(token[1:], token)
        return token

    def parse(self):
        value = self.relation(set())
        if self.peek() is not None:
            raise Unsupported("unconsumed_token_%s" % self.peek())
        return value

    def relation(self, stops):
        value = self.add(stops)
        while self.op() in _RELATIONS and self.peek() not in stops:
            operator = self.op()
            self.take()
            value = [operator, value, self.add(stops)]
        return value

    def add(self, stops):
        value = self.product(stops)
        while self.peek() in {"+", "-"} and self.peek() not in stops:
            operator = self.take()
            value = [operator, value, self.product(stops)]
        return value

    def product(self, stops):
        value = self.unary(stops)
        while self.peek() is not None and self.peek() not in stops:
            operator = self.op()
            if operator in {"*", "/", "cdot", "times"}:
                self.take()
                value = [operator, value, self.unary(stops)]
            elif self._starts_atom(self.peek()):
                value = ["juxtapose", value, self.unary(stops)]
            else:
                break
        return value

    @staticmethod
    def _starts_atom(token):
        return bool(token and (token in {"{", "(", "[", "|", "norm_bar"} or token[0].isalpha() or token[0].isdigit() or token.startswith(".") or token.startswith("\\") and token[1:] not in _COMMAND_OPS))

    def unary(self, stops):
        if self.peek() in {"+", "-"}:
            return ["unary" + self.take(), self.unary(stops)]
        value = self.atom(stops)
        seen = set()
        while self.peek() in {"^", "_"}:
            operator = self.take()
            if operator in seen:
                raise Unsupported("repeated_ungrouped_script")
            seen.add(operator)
            script = self.atom(stops)
            # Preserve the conventional superscript T syntax without asserting
            # its semantic role; explicit \top remains a distinct fixed token.
            if operator == "^" and script == ["symbol", "T"]:
                script = ["fixed_script", "T"]
            value = [operator, value, script]
        return value

    def _raw_group(self):
        self.take("{")
        parts = []
        while self.peek() not in {None, "}"}:
            part = self.take()
            if not re.fullmatch(r"[A-Za-z]|\d+(?:\.\d+)?", part):
                raise Unsupported("unsupported_text_label")
            parts.append(part)
        self.take("}")
        if not parts:
            raise Unsupported("empty_text_label")
        return "".join(parts)

    def atom(self, stops):
        token = self.take()
        if token in stops:
            raise Unsupported("missing_operand")
        if token in {"{", "(", "["}:
            closing = {"{": "}", "(": ")", "[": "]"}[token]
            value = self.relation({closing})
            self.take(closing)
            return value
        if token in {"|", "norm_bar"}:
            value = self.relation({token})
            self.take(token)
            return ["abs" if token == "|" else "norm", value]
        if re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)", token):
            return ["number", token]
        if re.fullmatch("[A-Za-z]", token):
            return ["symbol", token]
        if token.startswith("\\"):
            name = token[1:]
            if name in {"sum", "prod", "int", "oint", "lim", "forall", "exists"}:
                raise Unsupported("unsupported_binding_operator_%s" % name)
            if name in _GREEK:
                return ["symbol", token]
            if name in {"top", "perp", "infty"}:
                return ["fixed", name]
            if name in {"frac", "dfrac", "tfrac"}:
                self.take("{")
                numerator = self.relation({"}"})
                self.take("}")
                self.take("{")
                denominator = self.relation({"}"})
                self.take("}")
                return ["fraction", numerator, denominator]
            if name == "sqrt":
                if self.peek() != "{":
                    raise Unsupported("sqrt_requires_braced_argument")
                return ["sqrt", self.atom(stops)]
            if name in _STYLES:
                if self.peek() != "{":
                    raise Unsupported("style_requires_braced_argument")
                return ["style", name, self.atom(stops)]
            if name == "mathrm":
                return ["label", name, self._raw_group()]
            if name == "operatorname":
                name = self._raw_group()
                if name not in _FUNCTIONS:
                    raise Unsupported("unsupported_named_operator_%s" % name)
            if name in _FUNCTIONS:
                if self.peek() not in {"{", "(", "["}:
                    raise Unsupported("function_requires_grouped_argument_%s" % name)
                return ["function", name, self.atom(stops)]
            raise Unsupported("unsupported_command_%s" % name)
        raise Unsupported("unsupported_atom_%s" % token)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def explain_structure(latex):
    """Return an ordered literal AST and a consistent-renaming candidate key."""
    base = {"version": VERSION, "latex": latex, "status": "unknown", "reason": None,
            "literal_signature": None, "structure_signature": None, "symbol_map": {}, "operators": []}
    try:
        ast = _Parser(_tokens(latex)).parse()
    except (Unsupported, RecursionError) as error:
        base["reason"] = str(error) if isinstance(error, Unsupported) else "nesting_budget_exceeded"
        return base
    symbols = {}
    operators = set()

    def rename(tree):
        if not isinstance(tree, list):
            return tree
        kind = tree[0]
        if kind == "symbol":
            symbols.setdefault(tree[1], "v%d" % len(symbols))
            return [kind, symbols[tree[1]]]
        if kind not in {"number", "label", "fixed", "fixed_script"}:
            operators.add(kind if kind not in {"function", "style"} else kind + ":" + tree[1])
        return [kind] + [rename(child) for child in tree[1:]]

    renamed = rename(ast)
    base.update(status="supported", ast=ast, renamed_ast=renamed, symbol_map=symbols,
                operators=sorted(operators),
                literal_signature=hashlib.sha256(_json(ast).encode()).hexdigest(),
                structure_signature=hashlib.sha256(_json(renamed).encode()).hexdigest())
    return base


def build_index(records):
    """Build occurrence buckets, counting frequency by distinct source document.

    A bucket is a syntactic candidate family, not a merged semantic concept.
    The index stores no pairwise edges and does not infer labels or equivalence.
    """
    indexed = []
    buckets = defaultdict(list)
    ids = set()
    node_documents = {}
    for source in records:
        record = {key: source[key] for key in ("id", "node_id", "document", "latex")}
        for key in ("id", "node_id", "document"):
            if not isinstance(record[key], str) or not record[key]:
                raise ValueError("%s must be a nonempty string" % key)
        if record["id"] in ids:
            raise ValueError("duplicate formula record id: %s" % record["id"])
        ids.add(record["id"])
        previous = node_documents.setdefault(record["node_id"], record["document"])
        if previous != record["document"]:
            raise ValueError("one node_id cannot belong to multiple documents")
        record["structure"] = explain_structure(record["latex"])
        indexed.append(record)
        if record["structure"]["status"] == "supported":
            buckets[record["structure"]["structure_signature"]].append(record)
    result_buckets = []
    for key, members in sorted(buckets.items()):
        result_buckets.append({"id": key, "record_ids": sorted(r["id"] for r in members),
                               "node_count": len({r["node_id"] for r in members}),
                               "document_frequency": len({r["document"] for r in members})})
    supported = sum(r["structure"]["status"] == "supported" for r in indexed)
    return {"version": VERSION, "records": sorted(indexed, key=lambda r: r["id"]),
            "buckets": result_buckets,
            "coverage": {"total": len(indexed), "supported": supported, "unknown": len(indexed) - supported},
            "document_count": len(set(node_documents.values()))}


def bounded_candidates(index, per_node_k=4):
    """Return at most k directed cross-document proposals per original node.

    Enumeration is bounded by O(records * k) after grouping/sorting; common
    buckets are never expanded into cliques. Direction here means candidate
    retrieval provenance, not a semantic edge direction. Confidence is absent:
    frequency is a specificity hint only, and verifier evidence is still needed.
    """
    if isinstance(per_node_k, bool) or not isinstance(per_node_k, int) or per_node_k < 0:
        raise ValueError("per_node_k must be a nonnegative integer")
    if per_node_k == 0:
        return []
    records = {r["id"]: r for r in index["records"]}
    targets_seen = defaultdict(set)
    proposals = []
    for bucket in index["buckets"]:
        if bucket["document_frequency"] < 2:
            continue
        by_document = defaultdict(dict)
        for record_id in bucket["record_ids"]:
            record = records[record_id]
            # Multiple formula members on one node do not inflate its degree.
            by_document[record["document"]].setdefault(record["node_id"], record)
        documents = sorted(by_document)
        groups = [sorted(by_document[d].values(), key=lambda r: (r["node_id"], r["id"])) for d in documents]
        for source in (r for group in groups for r in group):
            remaining = per_node_k - len(targets_seen[source["node_id"]])
            if remaining <= 0:
                continue
            source_doc = bisect_left(documents, source["document"])
            # Round robin through other documents; limit attempts even when
            # earlier buckets have already proposed the same target nodes.
            attempts = 0
            level = 0
            while remaining and attempts < per_node_k * 2:
                any_target = False
                for offset in range(1, len(groups)):
                    group = groups[(source_doc + offset) % len(groups)]
                    if level >= len(group):
                        continue
                    any_target = True
                    # Vary the representative deterministically by source so
                    # a common bucket does not send every proposal to the
                    # lexically first node of a document.
                    start = int(hashlib.sha256(source["node_id"].encode()).hexdigest()[:16], 16) % len(group)
                    target = group[(start + level) % len(group)]
                    attempts += 1
                    if target["node_id"] not in targets_seen[source["node_id"]]:
                        targets_seen[source["node_id"]].add(target["node_id"])
                        remaining -= 1
                        proposals.append({"source_id": source["id"], "target_id": target["id"],
                                          "source_node_id": source["node_id"], "target_node_id": target["node_id"],
                                          "bucket_id": bucket["id"], "document_frequency": bucket["document_frequency"],
                                          "candidate_only": True})
                    if not remaining or attempts >= per_node_k * 2:
                        break
                if not any_target:
                    break
                level += 1
    return proposals
