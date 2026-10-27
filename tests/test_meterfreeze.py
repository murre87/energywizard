"""2026-10-27: 'Oförklarad hög last' kom fast ingen var hemma: Tibber-mätaren stod still på 2808,9 W och samma fasströmmar sedan 09:02."""


def test_unchanged_meter_values_for_ten_minutes_are_frozen_and_give_no_alarm():
    import health

    mf = health.MeterFreeze()
    ph = (4.1, 3.1, 4.9)
    assert mf.frozen(2808.9, ph, 0) is False                       # första värdet
    assert mf.frozen(2808.9, ph, 300) is False                     # samma värde i 5 minuter: ännu inte fryst
    assert mf.frozen(2808.9, ph, 600) is True                      # 10 minuter oförändrat: fryst
    assert mf.frozen(2790.0, ph, 660) is False                     # ett nytt värde: mätaren lever
    lc = health.load_check(3400.0, 0.0, 2808.9, ph, False, meter_frozen=True)
    assert lc["alert"] is False and lc["meter_frozen"] is True      # inget larm vid fastfryst mätare
    assert health.load_check(3400.0, 0.0, 2808.9, ph, False, meter_frozen=False)["alert"] is True      # samma siffror med levande mätare larmar som förut


def test_a_quiet_house_is_not_called_frozen():
    import health

    mf = health.MeterFreeze()
    assert mf.frozen(40.0, (0.2, 0.2, 0.2), 0) is False
    assert mf.frozen(40.0, (0.2, 0.2, 0.2), 3600) is False         # under 300 W: ett stilla hus är inte en frusen mätare
