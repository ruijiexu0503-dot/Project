import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from representations import edge_representation, invert_middiff, l2_normalize
def test_mid_diff_and_invertibility():
    a = np.array([[1., 2.], [3., 4.]]); b = np.array([[2., 5.], [3., 4.]])
    assert np.allclose(edge_representation(a,b,"mid"), edge_representation(b,a,"mid"))
    assert np.allclose(edge_representation(a,b,"diff"), -edge_representation(b,a,"diff"))
    x, y = invert_middiff(edge_representation(a,b,"middiff")); assert np.allclose(x,a) and np.allclose(y,b)
def test_zero_difference_is_safe():
    value, zero = l2_normalize(np.array([[0.,0.], [3.,4.]])); assert zero.tolist() == [True, False] and np.isfinite(value).all()
