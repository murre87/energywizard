"""Exercise NumPy and its consumers without application startup or devices."""
import json
import sys


def stage(name):
    print(json.dumps({'stage':name}),file=sys.stderr,flush=True)

stage('imports')
import numpy as np
import pandas as pd
from scipy import linalg
from sklearn.linear_model import LinearRegression
from threadpoolctl import threadpool_info

a = np.array([[3., 1.], [1., 2.]])
b = np.array([9., 8.])
stage('numpy_solve')
np.testing.assert_allclose(np.linalg.solve(a, b), [2., 3.])
stage('scipy_solve')
np.testing.assert_allclose(linalg.solve(a, b), [2., 3.])
stage('numpy_inverse')
np.testing.assert_allclose(a @ np.linalg.inv(a), np.eye(2), atol=1e-12)
stage('numpy_fft')
np.testing.assert_allclose(np.fft.ifft(np.fft.fft(b)).real, b)
stage('pandas')
assert pd.DataFrame({'value': [1., 2., 3.]}).value.mean() == 2.
x = np.arange(10.).reshape(-1, 1)
stage('sklearn_fit')
model = LinearRegression().fit(x, 2. * x[:, 0] + 1.)
stage('sklearn_prediction')
np.testing.assert_allclose(model.predict([[10.]]), [21.])
libraries=[{key:lib.get(key) for key in ('internal_api','version','architecture','num_threads')}
           for lib in threadpool_info() if lib.get('user_api')=='blas']
print(json.dumps({'numpy': np.__version__, 'pandas': pd.__version__, 'status': 'passed',
                  'blas_libraries':libraries}))
