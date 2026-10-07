"""Opsætning for fordeling-af-genoptraeningsplaner."""

# ------------------------------------------------------------
# CURA-MILJØ
# ------------------------------------------------------------
CURA_CREDENTIAL_NAME = "API_CURA"

# ------------------------------------------------------------
# BESKEDTYPE
# ------------------------------------------------------------
# Vi henter genoptræningsplanbeskeder.
# "rehabilitation_plan" er beskedtypens tekniske navn i q-cura-api.
#
# Denne proces filtrerer efterfølgende på blank undertype.
# Processens øvrige logik er derfor lavet til genoptræningsplaner.
MESSAGE_TYPE = "rehabilitation_plan"

# ------------------------------------------------------------
# SØGEPERIODE
# ------------------------------------------------------------
SEARCH_TIMEZONE = "Europe/Copenhagen"

# Fra starten af dagen 30 dage tilbage
# til slutningen af dagen 0 dage tilbage (i dag).
SEARCH_START_DAYS_AGO = 30
SEARCH_END_DAYS_AGO = 0

# ------------------------------------------------------------
# OPGAVEOPSLAG
# ------------------------------------------------------------
TASK_SEARCH_COUNT = 1000