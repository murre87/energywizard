# Published notice verification — issue #231

Checked on 2026-11-12 against repository base `bca59e3`. This completes the
previously unverified AMD64 published-image artifact check recorded in the local
Tier 1 review. It is not a legal determination or confirmation of reporter
acceptance.

The four published `latest` references were resolved to immutable index digests
before pulling their `linux/amd64` images. Each image was inspected using a
stopped container with no network; no application was started. Copied file
contents matched the repository after CRLF/LF normalization:

| Image | Verified artifacts |
| --- | --- |
| `ghcr.io/murre87/energywizard` | `/LICENSE`, `/smartbox/LICENSE` and four `UPSTREAM-*` notices under `/smartbox/ftw_drivers/` |
| `ghcr.io/murre87/energywizard-smartbox` | `/app/LICENSE` and four `UPSTREAM-*` notices under `/app/ftw_drivers/` |
| `ghcr.io/murre87/energywizard-ewapp` | `/ew/LICENSE` |
| `ghcr.io/murre87/energywizard-webdashboard` | `/wd/LICENSE` |

[Digest and normalized file-hash evidence](231-published-notices-2026-11-12.json)
records all 13 checked files. Temporary containers, their anonymous volumes and
newly pulled digest references were removed; pre-existing image references were
preserved. No image was published or deployed.

The repository's three licensing-artifact regression tests also pass. These
checks establish file presence and content for the recorded images, not every
distribution obligation or the ARM64 filesystem. Upstream
[srcfl/device-drivers PR #224](https://github.com/srcfl/device-drivers/pull/224)
was still open and draft when checked; no upstream merge or acceptance is
claimed. Issue #231 remains open for reporter/upstream follow-up.
