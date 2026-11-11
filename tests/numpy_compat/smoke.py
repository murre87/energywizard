"""Exercise NumPy and its consumers without application startup or devices."""
import json

import numpy as np
import pandas as pd
from scipy import linalg
from sklearn.linear_model import LinearRegression

a = np.array([[3., 1.], [1., 2.]])
b = np.array([9., 8.])
np.testing.assert_allclose(np.linalg.solve(a, b), [2., 3.])
np.testing.assert_allclose(linalg.solve(a, b), [2., 3.])
np.testing.assert_allclose(a @ np.linalg.inv(a), np.eye(2), atol=1e-12)
np.testing.assert_allclose(np.fft.ifft(np.fft.fft(b)).real, b)
assert pd.DataFrame({'value': [1., 2., 3.]}).value.mean() == 2.
x = np.arange(10.).reshape(-1, 1)
model = LinearRegression().fit(x, 2. * x[:, 0] + 1.)
np.testing.assert_allclose(model.predict([[10.]]), [21.])
print(json.dumps({'numpy': np.__version__, 'pandas': pd.__version__, 'status': 'passed'}))
