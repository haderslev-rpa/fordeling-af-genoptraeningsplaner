"""Opsætning. Ingen states eller proceslogik."""


# CURA
# False: Gem kun vurderingen i ATS.
# True: Tillad opdatering af undertypen efter alle kontroller.
CURA_SUBTYPE_UPDATE_ENABLED = False

CURA_CREDENTIAL_NAME = "API_CURA"
MESSAGE_TYPE = "rehabilitation_plan"
REHABILITATION_TYPE = "GENERALIZED"


# Søgeperiode
SEARCH_TIMEZONE = "Europe/Copenhagen"
SEARCH_START_DAYS_AGO = 1
SEARCH_END_DAYS_AGO = 0
COMMUNICATION_SEARCH_COUNT = 1000
TASK_SEARCH_COUNT = 1000


# Udvikling
# Hver worker-start henter og vurderer sagen igen.
TEST_REFRESH_ON_START = True


# AI
COPILOT_SITE = "Automatisering"
PROMPT_VERSION = "model-b-test-4"
CONFIDENCE_THRESHOLD = 80

# Maksimum pr. tekstværdi, inklusive mellemrum.
# For lister gælder grænsen hvert listepunkt.
AI_MAX_TEXT_CHARS = 200

# False: Rå svar bevares kun ved valideringsfejl.
# True: Rå svar bevares også ved gyldige resultater.
AI_SAVE_RAW_RESPONSE = False

# Udfyld med fagligt godkendte kriterier, når de foreligger.
APPROVED_CRITERIA = ""


# Organisationskatalog
ORGANISATIONS_SITE = "Automatisering"

ORGANISATIONS_FILE_PATH = (
    "RPA - Processer/fordeling-af-genoptraeningsplaner/"
    "Organisationer.xlsx"
)

ORGANISATIONS_SHEET_2026 = "2026"
ORGANISATIONS_SHEET_OTHER = "2027 og frem"

# True betyder, at inaktive organisationer også kommer med i kataloget.
# Det sikrer, at underliggende organisationer kan findes gennem hierarkiet.
ORGANISATIONS_INCLUDE_INACTIVE = True

ORGANISATIONS_MAX_PAGES = 1000


# P4-organisationstyper
# Nøglerne skal svare præcist til Excel-kolonnen "Type".
# Værdierne er processens interne klassifikation.
P4_ORGANISATION_TYPES = {
    "Kommunale leverandører af Hjemmepleje": "kommunal",
    "Private leverandører af Hjemmepleje": "privat",
    "Kommunale leverandører af Plejehjem": "kommunal",
    "Private leverandører af Plejehjem": "privat",
}


# Ydelser
SERVICE_INCLUDED_STATUSES = (
    "active",
    "requested",
)

SERVICE_EXCLUDED_STATUSES = (
    "completed",
    "cancelled",
    "entered-in-error",
)


# Leverandørnavne til P1 og P3
# Disse kontroller udføres på alle aktive og fremtidige ydelser.
PROVIDER_DOGN = "Døgnrehabilitering"
PROVIDER_AFKLARING = "Afklaringsteamet"


# Resultatleverandører
TARGET_AFKLARING = "Afklaringsteamet"
TARGET_DOGN = "Myndighed - Træning"
TARGET_SPECIAL = "Patient- og Borgerrettet Team"
TARGET_MUNICIPAL = "Teamterapeuterne"
TARGET_DEFAULT = "Træning"


# Fagområder og opstartsydelser
STARTUP_SERVICES = {
    "Ortopædisk": "Opstartssamtale §140, Ortopædisk",
    "Neurologisk": "Opstartssamtale §140, Neurologisk",
    "Medicinsk": "Opstartssamtale §140, Medicinsk",
    "Psykiatrisk": "Opstartssamtale §140, Psykiatrisk",
    "Kræft": "Opstartssamtale §140, Kræft",
}


# Genoptræningsniveau
LEVEL_CODES = {
    "A": "ADVANCED",
    "B": "BASIC",
}

LEVEL_NAMES = {
    "A": "Avanceret niveau",
    "B": "Basalt niveau",
}