"""Paritetsverktyget: kör två implementationer av samma beslut på exakt samma indata och visar var de skiljer sig.

Det är skyddsnätet för uppdelningen (docs/uppdelning/PLAN.md): innan en del flyttas till en egen process körs den gamla (i processen)
och den nya sida vid sida på samma scenarier, och bytet sker först när skillnaderna är noll. Beslutet är tillståndsfullt (motorn minns
mellan varven), så ett scenario är en FÖLJD av indata som matas till en ny instans av varje implementation.

    report = parity.compare(scenarios, make_old, make_new, normalize=contracts.decision_to_wire)
    assert report.ok, report.summary()

`make_*()` returnerar en funktion indata -> beslut för ett nytt scenario. Tal jämförs med toleransen `tol`.
"""
from dataclasses import dataclass, field


def diff(a, b, path="", tol=1e-9):
    """Alla skillnader mellan två JSON-lika strukturer som (sökväg, a, b). Saknade nycklar och olika längd syns som skillnader."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                out.append((p, "<saknas>", b[k]))
            elif k not in b:
                out.append((p, a[k], "<saknas>"))
            else:
                out += diff(a[k], b[k], p, tol)
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            out.append((f"{path}[len]", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]", tol)
        return out
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return [] if a == b and type(a) is type(b) else [(path, a, b)]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) <= tol else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


@dataclass
class Report:
    scenarios: int = 0
    steps: int = 0
    diffs: list = field(default_factory=list)       # (scenario, steg, sökväg, gammalt, nytt)
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.diffs

    def summary(self, limit: int = 10) -> str:
        if self.ok:
            return f"paritet: {self.steps} steg i {self.scenarios} scenarier, inga skillnader"
        lines = [f"paritet: {len(self.diffs)}{'+' if self.truncated else ''} skillnader i {self.steps} steg i {self.scenarios} scenarier"]
        lines += [f"  scenario {s} steg {k}: {p}: {a!r} != {b!r}" for s, k, p, a, b in self.diffs[:limit]]
        return "\n".join(lines)


def compare(scenarios, make_a, make_b, normalize=None, tol=1e-9, max_diffs=200) -> Report:
    """Matar varje scenario (en följd av indata) genom en ny instans av a och b och samlar skillnaderna. Stannar efter max_diffs."""
    rep = Report()
    for si, seq in enumerate(scenarios):
        a, b = make_a(), make_b()
        rep.scenarios += 1
        for k, st in enumerate(seq):
            ra, rb = a(dict(st)), b(dict(st))
            if normalize:
                ra, rb = normalize(ra), normalize(rb)
            rep.steps += 1
            for p, x, y in diff(ra, rb, tol=tol):
                rep.diffs.append((si, k, p, x, y))
                if len(rep.diffs) >= max_diffs:
                    rep.truncated = True
                    return rep
    return rep
