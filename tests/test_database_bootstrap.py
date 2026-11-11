"""Integration tests must bootstrap settings before exercising learned profiles."""
import learning


def test_learning_profiles_have_settings_storage(smartbox, db, capsys, monkeypatch):
    assert db.execute('SELECT id FROM system_settings WHERE id = 1').fetchone() == (1,)
    for name in ('_cached_solar_profile', '_cached_solar_time',
                 '_cached_base_load_profile', '_cached_base_load_time'):
        monkeypatch.setattr(learning, name, None)

    learning.get_solar_profile(force_recalculation=True)
    learning.get_base_load_profile(force_recalculation=True)

    # Both loaders lazily add storage columns; a missing settings table used to
    # be swallowed and leave these paths untested even when planning tests passed.
    assert db.execute('''SELECT solar_profile, solar_profile_time,
                               base_load_profile, base_load_profile_time
                        FROM system_settings WHERE id = 1''').fetchone() is not None
    captured = capsys.readouterr()
    assert 'UndefinedTable' not in captured.err
    assert 'DB-fel' not in captured.out
