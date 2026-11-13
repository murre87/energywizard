"""env_errors.py - fel i användarens miljö, inte i EnergyWizard (Emil 2026-11-13: "Diskfull kan väl inte vi göra något
åt hos användarna? Dessa fel ska inte rapporteras").

Full disk och en databas som inte svarar (anslutningspoolen tom, Postgres nere) beror på datorn EnergyWizard körs på.
De rapporteras inte som programfel (telemetry.py), räknas inte som fel i samlaren eller på Installationer, och blir
inga GitHub-ärenden. I stället får användaren veta det hemma: en avisering högst var sjätte timme, så att huset inte
står still utan förklaring.
"""
import time

TYPES = {"DiskFull", "PoolTimeout", "OperationalError", "TooManyConnections", "AdminShutdown", "CannotConnectNow",
         "ConnectionTimeout", "InsufficientResources", "OutOfMemory"}
SQLSTATES = {"53100", "53200", "53300", "57P01", "57P03", "08001", "08006"}
NOTIFY_EVERY_S = 6 * 3600
_last = {"at": 0.0}


def is_env(error_type: str | None, exc=None) -> bool:
    if error_type in TYPES:
        return True
    return getattr(exc, "sqlstate", None) in SQLSTATES


def is_env_key(key: str) -> bool:
    """För samlaren och gränssnitten: 'modul: Feltyp' eller bara 'Feltyp'."""
    return str(key or "").rsplit(":", 1)[-1].strip().split("@")[0] in TYPES


def note(error_type: str) -> None:
    """Säg till användaren (högst var sjätte timme). Aldrig ett fel i sig."""
    now = time.time()
    if now - _last["at"] < NOTIFY_EVERY_S:
        return
    _last["at"] = now
    disk = error_type == "DiskFull"
    title = "💾 Disken är full" if disk else "🗄️ Databasen svarar inte"
    msg = ("EnergyWizards databas kan inte skriva eftersom disken är full. Styrningen fortsätter så gott den kan, men "
           "historik och planer sparas inte. Frigör utrymme på datorn eller minneskortet (t.ex. gamla säkerhetskopior "
           "i Home Assistant)." if disk else
           "EnergyWizards databas svarar inte just nu. Vanligast är att disken är full eller att datorn har för lite "
           "minne. Styrningen fortsätter så gott den kan; kontrollera ledigt utrymme och starta om tillägget om det "
           "inte går över.")
    try:
        import notifier
        notifier.send_emil(title, msg, key="system")
    except Exception:
        pass
