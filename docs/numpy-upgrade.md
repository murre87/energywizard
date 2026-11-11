# NumPy security and legacy CPU upgrade review

Review date: 2026-11-11. Tracked in [#280](https://github.com/murre87/energywizard/issues/280),
following [#279](https://github.com/murre87/energywizard/pull/279) and the security
review in [#273](https://github.com/murre87/energywizard/issues/273).

## Security coverage

Fresh PyPI metadata identifies 2.3.5, 2.4.6 and 2.5.4 as the latest published,
non-yanked patches in their respective series. OSV queries for those exact
versions return no advisories; pip-audit 2.10.1 also reports none for 2.3.5.
This establishes known-advisory scan results at the review date, not an absence
of bugs, exploitability or future vulnerabilities.

The reviewed [upstream security policy](https://github.com/numpy/numpy/security/policy)
and [security guidance](https://numpy.org/doc/stable/reference/security.html)
do not establish a guaranteed security-backport lifetime for 2.3.x. Do not infer
such a guarantee from a third-party lifecycle website or from a clean scan.

`numpy<2.4` permits 2.3.x patch updates and currently resolves to 2.3.5. Keep the
cap temporarily while qualifying the replacement, with another maintenance
review by 2026-12-11 (a project review date, not an upstream support deadline).
The existing daily image audits reject Python advisories regardless of the cap.
If a required security fix is unavailable below 2.4, keep releases blocked until
a compatible build or an explicitly reviewed change to supported CPUs is ready.
Do not suppress that advisory or weaken the compatibility test to make CI green.

## Tested upgrade approach

NumPy 2.4.6 supports Python >=3.11. NumPy 2.5.4 requires Python >=3.12, so adopting
2.5 also requires a separately tested Python/dependency upgrade.

Upstream documents [cpu-baseline=none](https://numpy.org/doc/2.4/reference/simd/build-options.html#targeting-older-cpus)
for older x86 CPUs. The evaluation Dockerfile builds 2.4.6 from its SHA256-pinned
PyPI source archive with that flag and explicitly selects Debian's reference
[BLAS/LAPACK](https://numpy.org/doc/2.4/building/blas_lapack.html). It does not use
native-CPU tuning or silently fall back to NumPy's internal BLAS replacement.
Reference BLAS may change performance; production workloads must be benchmarked.

Run from an amd64 Docker host:

```sh
python3 scripts/check_numpy_compat.py
```

The check builds three evaluation images and runs them without network access
under QEMU's `qemu64` CPU model. Python startup must succeed first. The upstream
2.4.6 wheel must then fail with a CPU-baseline error or a reported SIGILL; any
other failure is rejected. The capped 2.3.5 wheel and source-built 2.4.6 must pass
linear solves, inversion, FFT, pandas aggregation and scikit-learn regression.
This also exercises SciPy and the libraries installed from smartbox requirements.
The local amd64 run passed this three-way comparison: 2.3.5 and the source-built
2.4.6 passed, while the official 2.4.6 wheel reported SIGILL. Python itself
started successfully under the same CPU model.
All Docker builds run `pip check`. On WSL a piped crash handler can hang after
QEMU reports SIGILL; the harness bounds that negative control and removes its
uniquely named container. A timeout without CPU-fault evidence never passes.

The `numpy-compatibility-evaluation` workflow runs the same check for changes to
the evaluation tooling, or manually. These images are never published. The
`regression` Docker target additionally supplies pytest for application tests
against a disposable PostgreSQL instance.

## Adoption requirements

This evaluation does not change production requirements or Dockerfiles. Before
removing the cap:

1. Build and install the reviewed wheel in each affected image, including the
   optional DHI images, and supply its BLAS/LAPACK runtime libraries. Verify
   dependency resolution cannot replace it with an incompatible upstream wheel.
2. Update the requirements and every image together. Replace the literal-cap
   regression assertion with verified artifact/CPU compatibility coverage.
3. Run full application regression, image security and startup checks for amd64
   and arm64, plus performance checks and validation on actual older hardware.
   Emulation and a native amd64 test run do not establish all of these.
4. Review wheel provenance, build dependencies and maintenance ownership. The
   pinned source/base do not make apt and isolated build dependencies hermetic.

PR #279 only loosens a requirements cap; it does not implement this build or
validation path. It must not be treated as an automatically safe upgrade, nor
should its failure become justification for freezing NumPy indefinitely.
