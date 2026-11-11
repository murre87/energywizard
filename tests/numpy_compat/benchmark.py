"""Small deterministic native workloads; timings are evidence, not a release gate."""
import json
import platform
from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.linear_model import LinearRegression

rng = np.random.default_rng(280)
a = rng.normal(size=(256, 256))
positive = a[:80, :80].T @ a[:80, :80] + np.eye(80)
b = rng.normal(size=80)
signal = rng.normal(size=8192)
frame = pd.DataFrame({'group': np.arange(2000) % 12, 'value': rng.normal(size=2000)})
x = rng.normal(size=(512, 8))
y = x @ np.arange(8.) + 1.
np.testing.assert_allclose(positive @ np.linalg.solve(positive, b), b, atol=1e-10)
np.testing.assert_allclose(LinearRegression().fit(x, y).predict(x), y, atol=1e-10)

workloads = {
    'matrix_multiply_256': lambda: a @ a.T,
    'linear_solve_80': lambda: np.linalg.solve(positive, b),
    'fft_8192': lambda: np.fft.fft(signal),
    'pandas_groupby_2000': lambda: frame.groupby('group').value.mean(),
    'sklearn_fit_512x8': lambda: LinearRegression().fit(x, y),
}
timings = {}
for name, operation in workloads.items():
    operation()  # Warm up dispatch and loaded libraries.
    samples = []
    for _ in range(5):
        start = perf_counter()
        for _ in range(10):
            operation()
        samples.append((perf_counter() - start) / 10)
    timings[name] = {'median_seconds': median(samples), 'samples_seconds': samples}

print(json.dumps({
    'architecture': platform.machine(), 'python': platform.python_version(),
    'versions': {'numpy': np.__version__, 'pandas': pd.__version__,
                 'scipy': scipy.__version__, 'scikit-learn': sklearn.__version__},
    'numpy_config': np.show_config(mode='dicts'), 'timings': timings,
}, default=str))
