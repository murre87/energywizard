"""get_optimal_pi_params ska falla tillbaka på standardvärdena och inte fråga databasen igen vid varje anrop när frågan misslyckas
(sensor_log har ingen kolumn solar_limit_pct; felet skrevs tidigare ~var minut)."""
import learning


def test_standardvarden_cachas_vid_fel(monkeypatch):
    anrop = []

    class Trasig:
        def __enter__(self):
            anrop.append(1)
            raise RuntimeError('column "solar_limit_pct" does not exist')

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(learning.sm_logger, "get_db", lambda: Trasig())
    monkeypatch.setattr(learning, "_cached_pi_params", None)
    monkeypatch.setattr(learning, "_cached_pi_time", None)
    assert learning.get_optimal_pi_params() == (0.005, 0.0005)
    assert learning.get_optimal_pi_params() == (0.005, 0.0005)
    assert len(anrop) == 1
