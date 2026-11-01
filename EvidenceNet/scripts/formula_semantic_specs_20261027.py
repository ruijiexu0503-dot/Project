"""Frozen, synthetic development challenge for formula edge verification.

These are invented examples, not paper annotations or held-out evaluation data.
Diagnostic labels are not new production edge types.  Never expose ``expected``
or ``rationale`` to an inference prompt.

``structure_match`` describes the written expression tree under a consistent
renaming of variables, retaining operators, operand order and repeated-variable
patterns.  It is independent of parser coverage and mathematical equivalence.
Thus AB and BA have the same freely renamed shape, while ABA and AAB do not.

``same_definition`` requires the same bounded mathematical quantity or function
with matching operand roles and sufficient assumptions. ``shared_operation``
requires a useful, identified common computation (such as absolute prediction
error), but does not assert equality of the complete formulas. Pure operator
shape with unrelated physical meanings is ``different_meaning``. Missing
information needed to decide is ``insufficient_information``. These labels
deliberately test whether a verifier distinguishes a local mathematical link
from a claim about the complete research result.

``same_research_claim`` means that the supplied contexts explicitly describe the
same empirical claim about the same invented study; it is not inferred from
sharing a mathematical definition. All study names and results below are fake.
"""

DATASET_ID = "synthetic_formula_semantics_20261027_v1"
SCHEMA_VERSION = 1
PROVENANCE = "assistant-authored synthetic development fixtures; no real paper claims"


def _case(case_id, category, a, ac, b, bc, structure, semantic, rationale,
          contrast_group=None, same_research_claim=False):
    result = {
        "id": case_id,
        "category": category,
        "A": {"latex": a, "context": ac},
        "B": {"latex": b, "context": bc},
        "expected": {
            "structure_match": structure,
            "semantic_relation": semantic,
            "same_research_claim": same_research_claim,
        },
        "rationale": rationale,
        "provenance": "synthetic",
    }
    if contrast_group:
        result["contrast_group"] = contrast_group
    return result


CASES = [
    _case("FS001", "renamed_roles", r"v=d/t",
          "Average speed v is distance d in metres divided by elapsed time t in seconds; t is positive.",
          r"u=s/r", "Average speed u is distance s in metres divided by elapsed time r in seconds; r is positive.",
          "same", "same_definition", "Consistent renaming preserves distance/time roles and units.", "rate_roles"),
    _case("FS002", "same_letters_different_units", r"v=d/t",
          "Average speed v is distance d in metres divided by elapsed time t in seconds; t is positive.",
          r"v=d/t", "Revenue rate v is revenue d in dollars divided by campaign duration t in days; t is positive.",
          "same", "different_meaning", "Identical letters and division do not equate speed with revenue rate.", "rate_roles"),
    _case("FS003", "repeated_variable", r"x+x",
          "x is the integer number of red tokens in one box. The expression counts the tokens in two identical copies of that box.",
          r"u+u", "u is the integer number of red tokens in one box. The expression counts the tokens in two identical copies of that box.",
          "same", "same_definition", "The same input occurs twice on each side.", "repetition"),
    _case("FS004", "repeated_variable", r"x+x",
          "x is the number of red tokens in one box; this counts two copies of that box.",
          r"u+v", "u and v count red tokens in two different boxes, with u unequal to v. This counts their combined contents.",
          "different", "different_meaning", "A repeated operand cannot be independently renamed into two distinct operands.", "repetition"),
    _case("FS005", "same_shape_unrelated_quantities", r"y=ax^2",
          "y is painted area in square metres, x is the side length of a square panel in metres, and a is the dimensionless fraction painted.",
          r"E=mc^2", "E is rest energy in joules, m is rest mass in kilograms, and c is the speed of light in metres per second.",
          "same", "different_meaning", "A coefficient times a square is not sufficient semantic evidence linking area and rest energy.", "square_roles"),
    _case("FS006", "renamed_roles", r"y=ax^2",
          "y is painted area in square metres, x is the side length of a square panel in metres, and a is the dimensionless fraction painted.",
          r"z=bu^2", "z is painted area in square metres, u is the side length of a square panel in metres, and b is the dimensionless fraction painted.",
          "same", "same_definition", "The same expression template is accompanied by matching quantity roles.", "square_roles"),
    _case("FS007", "domain_conditions", r"\sqrt{x^2}",
          "x is a real, nonnegative scalar length. This expression returns its magnitude.",
          r"x", "x is a real, nonnegative scalar length. This expression returns its magnitude.",
          "different", "same_definition", "For real x greater than or equal to zero, square-root-of-square equals x.", "sqrt_domain"),
    _case("FS008", "domain_conditions", r"\sqrt{x^2}",
          "x is a signed real displacement and may be negative. This expression returns displacement magnitude.",
          r"x", "x is a signed real displacement and may be negative. This expression returns signed displacement.",
          "different", "different_meaning", "For x=-2, the outputs are 2 and -2; magnitude and signed displacement differ.", "sqrt_domain"),
    _case("FS009", "domain_conditions", r"\sqrt{x^2}",
          "x is a signed real displacement. This expression returns its nonnegative magnitude.",
          r"|x|", "x is a signed real displacement. This expression returns its nonnegative magnitude.",
          "different", "same_definition", "Absolute value and the principal square root of the square agree on real inputs.", "sqrt_domain"),
    _case("FS010", "matrix_order", r"AB",
          "A is the matrix [[1,0],[0,0]] and B is [[0,-1],[1,0]], acting on column vectors. AB applies B then A.",
          r"BA", "A is the matrix [[1,0],[0,0]] and B is [[0,-1],[1,0]], acting on column vectors. BA applies A then B.",
          "same", "different_meaning", "Free renaming hides order at the shape level, but fixed matrix roles give unequal linear maps.", "product_order"),
    _case("FS011", "matrix_renaming", r"AB",
          "A is the matrix [[1,0],[0,0]] and B is [[0,-1],[1,0]], acting on column vectors. AB applies B then A.",
          r"CD", "C is the matrix [[1,0],[0,0]] and D is [[0,-1],[1,0]], acting on column vectors. CD applies D then C.",
          "same", "same_definition", "A maps to C and B maps to D with the same values, dimensions and composition order.", "product_order"),
    _case("FS012", "matrix_repetition", r"ABA",
          "A=[[1,1],[0,1]] and B=[[0,-1],[1,0]] act on column vectors. The expression composes these fixed linear maps in the written order.",
          r"AAB", "A=[[1,1],[0,1]] and B=[[0,-1],[1,0]] act on column vectors. The expression composes these fixed linear maps in the written order.",
          "different", "different_meaning", "The repeated-variable position changes, and these specific matrix products are unequal."),
    _case("FS013", "transpose_output_type", r"X^T y",
          "X is an n-by-d real feature matrix and y an n-by-1 label column, with d greater than 1. The result is a d-by-1 column of feature-label dot products.",
          r"y^T X", "X is an n-by-d real feature matrix and y an n-by-1 label column, with d greater than 1. The result is a 1-by-d row of feature-label dot products.",
          "same", "shared_operation", "Free X/y renaming preserves the printed shape, but fixed feature/label roles yield transposed output layouts, not identical typed expressions.", "transpose_roles"),
    _case("FS014", "transpose_renaming", r"X^T y",
          "X is an n-by-d real feature matrix and y an n-by-1 label column. This returns the d-by-1 column of feature-label dot products.",
          r"Z^T u", "Z is an n-by-d real feature matrix and u an n-by-1 label column. This returns the d-by-1 column of feature-label dot products.",
          "same", "same_definition", "Transpose and operand roles are preserved under X-to-Z and y-to-u renaming.", "transpose_roles"),
    _case("FS015", "transpose_dimensions", r"qk^T",
          "q and k are 1-by-d real row vectors with d greater than 1. This expression is their scalar inner-product attention score.",
          r"q^T k", "q and k are 1-by-d real row vectors with d greater than 1. This expression is the d-by-d outer-product matrix.",
          "different", "different_meaning", "Moving the transpose changes contraction and output dimension; inner and outer products cannot be conflated.", "transpose_roles"),
    _case("FS016", "normalization", r"L=\sum_{i=1}^{n}|y_i-p_i|",
          "y_i is observed demand and p_i predicted demand for n greater than 1 observations. L is total absolute prediction error.",
          r"M=\frac{1}{n}\sum_{i=1}^{n}|y_i-p_i|", "y_i is observed demand and p_i predicted demand for n greater than 1 observations. M is mean absolute prediction error.",
          "different", "shared_operation", "Both compute absolute residuals, but division by n changes the complete metric.", "absolute_error"),
    _case("FS017", "common_definition", r"L=|y-p|",
          "In invented study Alder, y is observed hourly demand and p its prediction. L is single-observation absolute error. No performance result is stated.",
          r"E=|t-q|", "In invented study Birch, t is observed hourly demand and q its prediction. E is single-observation absolute error. No performance result is stated.",
          "same", "same_definition", "The bounded metric definition is the same; different studies do not imply the same research result.", "absolute_error"),
    _case("FS018", "subexpression_vs_objective", r"L=C+\lambda|b-p|",
          "C is classification loss; b is a target box coordinate; p is its prediction; lambda is a positive weight. L is the complete classification-plus-localization objective.",
          r"E=|y-q|", "y is observed traffic flow and q predicted traffic flow. E is the complete single-observation absolute forecast error objective.",
          "different", "shared_operation", "Only the absolute prediction-error sub-operation is shared; classification and weighting belong only to the first full objective.", "absolute_error"),
    _case("FS019", "same_purpose_different_metric", r"L=-\log p",
          "For the observed correct class, p is its predicted probability in (0,1). L is negative log-likelihood training loss.",
          r"L=|y-p|", "y is a target real-valued measurement and p is its real-valued prediction. L is absolute-error training loss.",
          "different", "different_meaning", "Being training losses does not make probability log loss the same definition as absolute regression error."),
    _case("FS020", "same_purpose_different_metric", r"M=\frac{1}{n}\sum_{i=1}^{n}|(y_i-p_i)/y_i|",
          "All y_i are nonzero observed flows, p_i are predictions, and n is the observation count. M is mean absolute relative error, reported as a fraction.",
          r"R=\sqrt{\frac{1}{n}\sum_{i=1}^{n}(y_i-p_i)^2}", "y_i are observed flows, p_i are predictions, and n is the observation count. R is root mean squared error in flow units.",
          "different", "different_meaning", "Relative absolute error and root mean squared error differ in normalization, aggregation and units."),
    _case("FS021", "missing_roles", r"f=x/y", "No definitions, units, domain or operand roles were supplied.",
          r"g=u/v", "No definitions, units, domain or operand roles were supplied.",
          "same", "insufficient_information", "Syntactic similarity supplies no grounded semantic alignment.", "missing_context"),
    _case("FS022", "missing_roles", r"v=d/t",
          "v is average speed in metres per second, d distance in metres, and t a positive elapsed time in seconds.",
          r"v=d/t", "No definitions, units, domain or operand roles were supplied.",
          "same", "insufficient_information", "Identical printed letters cannot fill the missing definitions on the second side.", "missing_context"),
    _case("FS023", "incomplete_extraction", r"v=\frac{d}{",
          "The extracted formula is truncated after the denominator opening brace. No usable definition was recovered.",
          r"u=s/r", "u is average speed, s distance, and r positive elapsed time.",
          "unknown", "insufficient_information", "A malformed formula must be reported as unknown rather than repaired from its partner."),
    _case("FS024", "common_formula_different_study", r"m=\frac{1}{n}\sum_{i=1}^{n}x_i",
          "Invented study Cedar defines m as the arithmetic mean of n observed temperatures x_i. It reports m=12 degrees for its Cedar trial.",
          r"a=\frac{1}{k}\sum_{j=1}^{k}z_j", "Invented study Dune defines a as the arithmetic mean of k observed temperatures z_j. It reports a=19 degrees for its independent Dune trial.",
          "same", "same_definition", "A common mean definition does not equate two independently measured research results.", "common_mean_claim"),
    _case("FS025", "same_explicit_study_claim", r"m=\frac{1}{n}\sum_{i=1}^{n}x_i",
          "In the invented Cedar trial C1, x_i are its ten registered temperature observations and m their arithmetic mean. The stated finding is: C1 mean temperature was 12 degrees.",
          r"a=\frac{1}{k}\sum_{j=1}^{k}z_j", "This is a second description of the same invented Cedar trial C1. z_j are exactly its same ten registered temperature observations and a their arithmetic mean. The stated finding is: C1 mean temperature was 12 degrees.",
          "same", "same_definition", "Both the definition and explicit trial identity, observations and stated empirical finding agree.", "common_mean_claim", True),
    _case("FS026", "same_study_different_claim", r"m=\frac{1}{n}\sum_{i=1}^{n}x_i",
          "In invented Cedar study, x_i are temperature observations from treatment arm C1; m is their arithmetic mean. The finding concerns C1 only: its mean was 12 degrees.",
          r"a=\frac{1}{k}\sum_{j=1}^{k}z_j", "In invented Cedar study, z_j are temperature observations from distinct control arm C2; a is their arithmetic mean. The finding concerns C2 only: its mean was 19 degrees.",
          "same", "same_definition", "Sharing a study and metric does not equate findings about different experimental arms.", "common_mean_claim"),
    _case("FS027", "power_changes_function", r"y=ax+b",
          "x is a real input, a is a nonzero fixed scalar and b a fixed offset. y is the output of an affine calibration function.",
          r"y=ax^2+b", "x is a real input, a is a nonzero fixed scalar and b a fixed offset. y is the output of a quadratic calibration function.",
          "different", "different_meaning", "Exponent changes cannot be removed by renaming and change the function on real inputs."),
    _case("FS028", "indexed_repetition", r"x_i+x_j",
          "x is an array of counts; i and j are distinct positions whose values are unequal. The expression adds those two distinct entries.",
          r"y_k+y_k", "y is an array of counts and k one position. The expression adds that one entry to itself.",
          "different", "different_meaning", "Renaming must preserve repeated indices as well as repeated base symbols."),
    _case("FS029", "bound_index_renaming", r"\sum_{i=1}^{n}x_i",
          "x contains n scalar observed counts. The summation runs over every array position once and returns the total count.",
          r"\sum_{j=1}^{m}y_j", "y contains m scalar observed counts. The summation runs over every array position once and returns the total count.",
          "same", "same_definition", "Bound dummy-index renaming preserves scope; an unsupported binder parser must report coverage separately."),
    _case("FS030", "scalar_order", r"ab",
          "a and b are real scalar gains. Their product is the combined scalar gain of two stages.",
          r"ba", "a and b are the same real scalar gains. Their product is the combined scalar gain of the same two stages.",
          "same", "same_definition", "Real scalar multiplication commutes; this conclusion cannot be transferred to the matrix-order counterexample.", "product_order"),
]
