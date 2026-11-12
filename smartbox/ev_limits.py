"""ev_limits.py - lär sig varje bils faser och maxström av laddningarna (roadmap: "Max laddström och faser känns av själv").

Mätning från laddboxens fasströmmar medan bilen laddar:
  - faser: drar bara en fas ström (> 2 A) medan de andra står still (< 0,7 A) i minst MIN_SAMPLES minuter är bilen
    enfasig; drar två eller tre faser är den trefasig.
  - maxström: laddar bilen stadigt under det motorn beordrat (minst 1,5 A under) är det bilens egen gräns - den högsta
    sådana strömmen (avrundad nedåt) blir bilens maxström.

Används bara där installationen inte själv anger phases/max_a (evs[].charger). Sparas i /data/energywizard.json
("learned_ev") så att det överlever omstart. Startguiden visar det inlärda och skriver en kommentar i den
nedladdade konfigurationen, men aldrig phases/max_a själva - då skulle värdet frysas. Ren logik i LimitLearner,
testas i tests/test_ev_limits.py.
"""
MIN_SAMPLES = 10
ON_A, OFF_A = 2.0, 0.7


class LimitLearner:
    def __init__(self, saved=None):
        self.data = {k: dict(v) for k, v in (saved or {}).items() if isinstance(v, dict)}

    def observe(self, car, currents, commanded_a):
        """currents = [l1, l2, l3] (A) medan bilen laddar, commanded_a = strömmen motorn beordrat."""
        cs = [float(c) for c in (currents or []) if isinstance(c, (int, float))]
        if len(cs) < 2 or max(cs) < ON_A:
            return False
        d = self.data.setdefault(car, {"one": 0, "multi": 0, "max_a": None})
        on = sum(1 for c in cs if c > ON_A)
        if on == 1 and sum(1 for c in cs if c < OFF_A) == len(cs) - 1:
            d["one"] += 1
        elif on >= 2:
            d["multi"] += 1
        top = max(cs)
        if commanded_a and top < float(commanded_a) - 1.5:          # bilen tar mindre än den får: bilens egen gräns
            seen = int(top)
            if seen >= 6 and (d["max_a"] is None or seen > d["max_a"]):
                d["max_a"] = seen
                return True
        return False

    def phases(self, car):
        d = self.data.get(car) or {}
        if d.get("one", 0) >= MIN_SAMPLES and d.get("one", 0) > 4 * d.get("multi", 0):
            return "1"
        if d.get("multi", 0) >= MIN_SAMPLES and d.get("multi", 0) > 4 * d.get("one", 0):
            return "3"
        return None

    def max_a(self, car):
        return (self.data.get(car) or {}).get("max_a")

    def for_guide(self):
        """Det startguiden får visa: säkra faser, och maxström bara när motorn själv skulle använda den (under 16 A)."""
        rows = []
        for car in self.data:
            if not isinstance(car, str) or not car or len(car) > 80 or "\n" in car or "\r" in car:
                continue
            ph = self.phases(car)
            if ph not in ("1", "3"):
                ph = None
            ma = self.max_a(car)
            if isinstance(ma, bool) or not isinstance(ma, (int, float)) or not (6 <= float(ma) < 16):
                ma = None
            else:
                ma = int(ma)
            if ph or ma is not None:
                rows.append({"id": car, "phases": ph, "max_a": ma})
        return rows

    def guide_yaml_line(self, car_id):
        """En YAML-kommentar under bilen. Innehåller inte bil-id, och skriver inte phases eller max_a."""
        row = next((r for r in self.for_guide() if r["id"] == car_id), None)
        if not row:
            return None
        bits = []
        if row["phases"]:
            bits.append(f"{row['phases']}-fas")
        if row["max_a"] is not None:
            bits.append(f"max {row['max_a']} A")
        return "    # Inlärt av laddningarna: " + ", ".join(bits) + ". Lämna phases och max_a tomma så det följer med."

    def apply(self, specs, explicit):
        """Fyller i inlärda faser/maxström där installationen inte själv anger dem. explicit = {bil: {"phases", "max_a"}}."""
        changed = {}
        for car, sp in specs.items():
            ex = explicit.get(car) or {}
            ph = self.phases(car)
            if ph and not ex.get("phases") and sp.get("phases") != ph:
                sp["phases"] = ph
                changed[car] = changed.get(car, {}) | {"phases": ph}
            ma = self.max_a(car)
            if ma and not ex.get("max_a") and ma < sp.get("max_a", 16):
                sp["max_a"] = ma
                changed[car] = changed.get(car, {}) | {"max_a": ma}
        return changed
