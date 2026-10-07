"""Opsætning. Ingen states eller proceslogik."""
CURA_CREDENTIAL_NAME = "API_CURA"
MESSAGE_TYPE = "rehabilitation_plan"
REHABILITATION_TYPE = "GENERALIZED"
SEARCH_TIMEZONE = "Europe/Copenhagen"
SEARCH_START_DAYS_AGO = 2
SEARCH_END_DAYS_AGO = 0
COMMUNICATION_SEARCH_COUNT = 1000
TASK_SEARCH_COUNT = 1000

# Kun test: Hver worker-start henter alt igen, også efter retry til NEW.
TEST_REFRESH_ON_START = True
COPILOT_SITE = "Automatisering"
CONFIDENCE_THRESHOLD = 80
PROMPT_VERSION = "model-b-test-1"

# Udfyld med fagligt godkendte kriterier, når de foreligger.
APPROVED_CRITERIA = ""

# Foreløbig statusafgrænsning til test. Kontrollér mod jeres CURA-data.
SERVICE_INCLUDED_STATUSES = ("active", "requested")
SERVICE_EXCLUDED_STATUSES = ("completed", "cancelled", "entered-in-error")

# Navn -> privat/kommunal/ikke_relevant. Ingen opdigtede leverandører.
# Ukendte navne giver manuel kandidat i P4, ikke automatisk Træning.
PROVIDER_TYPES = {}
PROVIDER_LIST_COMPLETE = False

PROVIDER_DOGN = "Døgnrehabilitering"
PROVIDER_AFKLARING = "Afklaringsteamet"
TARGET_AFKLARING = "Afklaringsteamet"
TARGET_DOGN = "Myndighed - Træning"
TARGET_SPECIAL = "Patient- og Borgerrettet Team"
TARGET_MUNICIPAL = "Teamterapeuterne"
TARGET_DEFAULT = "Træning"

STARTUP_SERVICES = {
    "Ortopædisk": "Opstartssamtale §140, Ortopædisk",
    "Neurologisk": "Opstartssamtale §140, Neurologisk",
    "Medicinsk": "Opstartssamtale §140, Medicinsk",
    "Psykiatrisk": "Opstartssamtale §140, Psykiatrisk",
    "Kræft": "Opstartssamtale §140, Kræft",
}

LEVEL_CODES = {"A": "ADVANCED", "B": "BASIC"}
LEVEL_NAMES = {"A": "Avanceret niveau", "B": "Basalt niveau"}