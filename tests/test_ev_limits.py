"""Faser och maxström per bil lärs in av laddningarna - bara där installationen inte anger dem."""
from ev_limits import LimitLearner, MIN_SAMPLES


def test_enfasbil_och_egen_maxstrom():
    l = LimitLearner()
    for _ in range(MIN_SAMPLES):
        l.observe("leaf", [15.6, 0.1, 0.2], commanded_a=32)
    assert l.phases("leaf") == "1" and l.max_a("leaf") == 15


def test_trefasbil_som_tar_allt_far_ingen_maxgrans():
    l = LimitLearner()
    for _ in range(MIN_SAMPLES):
        l.observe("tesla", [15.9, 16.0, 15.8], commanded_a=16)
    assert l.phases("tesla") == "3" and l.max_a("tesla") is None


def test_bara_utan_installationens_egna_varden():
    l = LimitLearner({"leaf": {"one": 20, "multi": 0, "max_a": 15}, "kona": {"one": 0, "multi": 30, "max_a": 11}})
    specs = {"leaf": {"phases": "3", "max_a": 16}, "kona": {"phases": "auto", "max_a": 16}}
    changed = l.apply(specs, {"leaf": {"phases": True, "max_a": True}, "kona": {}})
    assert specs["leaf"] == {"phases": "3", "max_a": 16}                 # installationen bestämmer
    assert specs["kona"] == {"phases": "3", "max_a": 11} and changed == {"kona": {"phases": "3", "max_a": 11}}


def test_guiden_visar_inlart_utan_att_frysa_det():
    l = LimitLearner({
        "leaf": {"one": 20, "multi": 0, "max_a": 10},
        "kona": {"one": 0, "multi": 30, "max_a": 20},
        "ny": {"one": 3, "multi": 1, "max_a": None},
        "bil\nphases: 1": {"one": 20, "multi": 0, "max_a": 10},
    })
    assert l.for_guide() == [
        {"id": "leaf", "phases": "1", "max_a": 10},
        {"id": "kona", "phases": "3", "max_a": None},
    ]
    line = l.guide_yaml_line("leaf")
    assert line.startswith("    # ") and "1-fas" in line and "max 10 A" in line and "leaf" not in line
    assert "phases:" not in line and "\n" not in line
    kona = l.guide_yaml_line("kona")
    assert "3-fas" in kona and "20" not in kona and "max " not in kona
    assert l.guide_yaml_line("ny") is None and l.guide_yaml_line("saknas") is None
    assert l.guide_yaml_line("bil\nphases: 1") is None


def test_brus_ger_inget():
    l = LimitLearner()
    l.observe("x", [0.3, 0.2, 0.1], 16)
    assert l.phases("x") is None and l.max_a("x") is None


def test_webben_visar_installerat_inlart_eller_standard():
    import sys
    sys.path.insert(0, "webdashboard")
    import importlib
    src = open("webdashboard/app.py", encoding="utf-8").read()
    i = src.index("def _car_limits"); j = src.index("\n\n\n", i)
    ns = {}
    exec(src[i:j], ns)
    f = ns["_car_limits"]
    assert f({"phases": 1, "max_a": 10}, {"phases": "3", "max_a": 13}) == {"phases": "1", "phases_src": "installation", "max_a": 10, "max_a_src": "installation"}
    assert f({}, {"phases": "1", "max_a": 13}) == {"phases": "1", "phases_src": "inlärt", "max_a": 13, "max_a_src": "inlärt"}
    assert f({}, {"phases": None, "max_a": None}) == {"phases": "auto", "phases_src": "standard", "max_a": 16, "max_a_src": "standard"}
