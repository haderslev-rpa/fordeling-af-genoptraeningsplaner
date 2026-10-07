"""Validering af grupperede AI-svar og beregning af testbeslutning."""

import json

import configuration as config


GROUP_FIELDS = {
    "niveau": {"kode", "sikkerhed", "begrundelse"},
    "fagomraade": {"navn", "sikkerhed", "begrundelse"},
    "diagnoser": {"sammenhaeng", "begrundelse"},
    "saerlige_forhold": {"hjerte", "kraeft"},
    "manuel_afklaring": {"aarsag", "mangler", "konflikter"},
}


def result_template():
    """Returnerer en ny eksempelstruktur til prompten."""
    return {
        "niveau": {
            "kode": None,
            "sikkerhed": 0,
            "begrundelse": "Niveau kan ikke afgøres.",
        },
        "fagomraade": {
            "navn": None,
            "sikkerhed": 0,
            "begrundelse": "Fagområde kan ikke afgøres.",
        },
        "diagnoser": {
            "sammenhaeng": None,
            "begrundelse": "Diagnosesammenhæng kan ikke afgøres.",
        },
        "saerlige_forhold": {
            "hjerte": False,
            "kraeft": False,
        },
        "manuel_afklaring": {
            "aarsag": None,
            "mangler": [],
            "konflikter": [],
        },
    }


def _unique_object(pairs):
    """Afviser gentagne nøgler i samme JSON-objekt."""
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError("Dubleret JSON-felt.")

        result[key] = value

    return result


def _reject_constant(value):
    """Afviser NaN og Infinity."""
    raise ValueError(
        f"Ugyldig JSON-konstant: {value}."
    )


def validate_result(result):
    """Kontrollerer hele det grupperede AI-resultat.

    Returnerer intet ved et gyldigt resultat.
    Rejser ValueError ved et ugyldigt resultat.
    Funktionen ændrer eller afkorter aldrig resultatet.
    """
    max_chars = config.AI_MAX_TEXT_CHARS

    if type(max_chars) is not int or max_chars < 1:
        raise ValueError(
            "AI_MAX_TEXT_CHARS skal være et positivt heltal."
        )

    if not isinstance(result, dict):
        raise ValueError(
            "AI-resultatet skal være et JSON-objekt."
        )

    if set(result) != set(GROUP_FIELDS):
        raise ValueError(
            "AI-resultatet har manglende eller ekstra grupper."
        )

    for group, expected_fields in GROUP_FIELDS.items():
        group_value = result[group]

        if not isinstance(group_value, dict):
            raise ValueError(
                f"Gruppen {group} skal være et JSON-objekt."
            )

        if set(group_value) != expected_fields:
            raise ValueError(
                f"Gruppen {group} har manglende eller ekstra felter."
            )

    def check_text(value, path):
        """Kontrollerer én obligatorisk tekstværdi."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{path} skal være en ikke-tom tekst."
            )

        if len(value) > max_chars:
            raise ValueError(
                f"{path} overskrider grænsen "
                f"på {max_chars} tegn."
            )

    # Niveau
    level = result["niveau"]
    level_code = level["kode"]
    level_confidence = level["sikkerhed"]

    if (
        level_code is not None
        and (
            not isinstance(level_code, str)
            or level_code not in config.LEVEL_CODES
        )
    ):
        raise ValueError(
            "niveau.kode skal være A, B eller null."
        )

    if (
        type(level_confidence) is not int
        or not 0 <= level_confidence <= 100
    ):
        raise ValueError(
            "niveau.sikkerhed skal være et heltal fra 0 til 100."
        )

    if level_code is None and level_confidence != 0:
        raise ValueError(
            "niveau.sikkerhed skal være 0, "
            "når niveau.kode er null."
        )

    check_text(
        level["begrundelse"],
        "niveau.begrundelse",
    )

    # Fagområde
    clinical_area = result["fagomraade"]
    area_name = clinical_area["navn"]
    area_confidence = clinical_area["sikkerhed"]

    if (
        area_name is not None
        and (
            not isinstance(area_name, str)
            or area_name not in config.STARTUP_SERVICES
        )
    ):
        raise ValueError(
            "fagomraade.navn er ikke et tilladt fagområde."
        )

    if (
        type(area_confidence) is not int
        or not 0 <= area_confidence <= 100
    ):
        raise ValueError(
            "fagomraade.sikkerhed skal være et heltal "
            "fra 0 til 100."
        )

    if area_name is None and area_confidence != 0:
        raise ValueError(
            "fagomraade.sikkerhed skal være 0, "
            "når fagomraade.navn er null."
        )

    check_text(
        clinical_area["begrundelse"],
        "fagomraade.begrundelse",
    )

    # Diagnosesammenligning
    diagnoses = result["diagnoser"]
    diagnosis_consistent = diagnoses["sammenhaeng"]

    if (
        diagnosis_consistent is not None
        and type(diagnosis_consistent) is not bool
    ):
        raise ValueError(
            "diagnoser.sammenhaeng skal være "
            "true, false eller null."
        )

    check_text(
        diagnoses["begrundelse"],
        "diagnoser.begrundelse",
    )

    # Særlige forhold
    special_conditions = result["saerlige_forhold"]

    for field in ("hjerte", "kraeft"):
        if type(special_conditions[field]) is not bool:
            raise ValueError(
                f"saerlige_forhold.{field} "
                "skal være true eller false."
            )

    # Manuel afklaring
    manual_review = result["manuel_afklaring"]
    manual_reason = manual_review["aarsag"]

    if manual_reason is not None:
        check_text(
            manual_reason,
            "manuel_afklaring.aarsag",
        )

    for field in ("mangler", "konflikter"):
        values = manual_review[field]

        if not isinstance(values, list):
            raise ValueError(
                f"manuel_afklaring.{field} "
                "skal være en liste."
            )

        for index, value in enumerate(values):
            check_text(
                value,
                f"manuel_afklaring.{field}[{index}]",
            )


def parse_ai(text):
    """Fortolker og validerer et grupperet AI-svar.

    Returnerer:
        Ved gyldigt svar:
            (resultat, None)

        Ved ugyldigt svar:
            (None, fejltekst)

    Funktionen accepterer kun ren JSON.
    Markdown og gamle flade resultater accepteres ikke.
    """
    if (
        type(config.AI_MAX_TEXT_CHARS) is not int
        or config.AI_MAX_TEXT_CHARS < 1
    ):
        raise ValueError(
            "AI_MAX_TEXT_CHARS skal være et positivt heltal."
        )

    if not isinstance(text, str) or not text.strip():
        return (
            None,
            "AI-svaret mangler eller er ikke tekst.",
        )

    try:
        result = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )

        validate_result(result)

        return result, None

    except json.JSONDecodeError:
        return (
            None,
            "AI-svaret er ikke gyldig JSON.",
        )

    except ValueError as error:
        return None, str(error)

    except RecursionError:
        return (
            None,
            "AI-svaret har en for dyb JSON-struktur.",
        )


def decide(
    ai,
    services,
    tasks,
    input_issues,
    validation_error=None,
):
    """Beregner den vej, robotten ville vælge.

    Funktionen udfører ingen handlinger i CURA.
    Den returnerer kun en testbeslutning.
    """
    threshold = config.CONFIDENCE_THRESHOLD

    if (
        type(threshold) is not int
        or not 0 <= threshold <= 100
    ):
        raise ValueError(
            "CONFIDENCE_THRESHOLD skal være "
            "et heltal fra 0 til 100."
        )

    if not isinstance(input_issues, list):
        raise TypeError(
            "input_issues skal være en liste."
        )

    if not isinstance(services, dict):
        raise TypeError(
            "services skal være en dictionary."
        )

    if not isinstance(services.get("issues"), list):
        raise ValueError(
            "services mangler en gyldig issues-liste."
        )

    if not isinstance(services.get("items"), list):
        raise ValueError(
            "services mangler en gyldig items-liste."
        )

    if not isinstance(tasks, list):
        raise TypeError(
            "tasks skal være en liste."
        )

    reasons = (
        list(input_issues)
        + list(services["issues"])
    )

    provider = None
    priority = None

    # Et ugyldigt resultat må aldrig bruges til automatisk behandling.
    if validation_error:
        reasons.append(validation_error)
        ai = None

    elif ai is None:
        reasons.append("AI-resultatet mangler.")

    else:
        try:
            validate_result(ai)
        except ValueError as error:
            reasons.append(str(error))
            ai = None

    if not tasks:
        reasons.append(
            "Ingen tilknyttet opgave."
        )

    elif len(tasks) != 1:
        reasons.append(
            "Flere tilknyttede opgaver; "
            "ingen vælges automatisk."
        )

    level = None
    area = None
    heart = False
    cancer = False

    if ai is not None:
        level = ai["niveau"]["kode"]
        area = ai["fagomraade"]["navn"]

        heart = ai["saerlige_forhold"]["hjerte"]
        cancer = ai["saerlige_forhold"]["kraeft"]

        manual_review = ai["manuel_afklaring"]

        if ai["diagnoser"]["sammenhaeng"] is not True:
            reasons.append(
                "Diagnose og tekst er modstridende "
                "eller ikke afklaret."
            )

        if level is None or area is None:
            reasons.append(
                "Niveau eller fagområde er ikke afklaret."
            )

        if (
            ai["niveau"]["sikkerhed"] <= threshold
            or ai["fagomraade"]["sikkerhed"] <= threshold
        ):
            reasons.append(
                "Sikkerheden er ikke over tærsklen "
                "for begge vurderinger."
            )

        reasons.extend(
            manual_review["mangler"]
        )
        reasons.extend(
            manual_review["konflikter"]
        )

        if manual_review["aarsag"]:
            reasons.append(
                manual_review["aarsag"]
            )

        if (
            heart
            and (
                level != "A"
                or area != "Medicinsk"
            )
        ):
            reasons.append(
                "Hjertereglen er ikke overholdt."
            )

        if cancer != (area == "Kræft"):
            reasons.append(
                "Kræftflag og fagområde er inkonsistente."
            )

        if heart and cancer:
            reasons.append(
                "Hjerte og kræft kræver afklaring."
            )

    names = {
        service["performer_name"]
        for service in services["items"]
        if (
            isinstance(service, dict)
            and service.get("eligible") is True
            and service.get("performer_name")
        )
    }

    if config.PROVIDER_DOGN in names:
        provider = config.TARGET_DOGN
        priority = "P1"

    elif ai is not None and (heart or cancer):
        provider = config.TARGET_SPECIAL
        priority = "P2"

    elif config.PROVIDER_AFKLARING in names:
        provider = config.TARGET_AFKLARING
        priority = "P3"

    else:
        priority = "P4"

        unknown = (
            names
            - config.PROVIDER_TYPES.keys()
        )

        provider_types = {
            config.PROVIDER_TYPES[name]
            for name in names
            if name in config.PROVIDER_TYPES
        }

        allowed_provider_types = {
            "privat",
            "kommunal",
            "ikke_relevant",
        }

        if (
            unknown
            or not config.PROVIDER_LIST_COMPLETE
        ):
            reasons.append(
                "P4-leverandørlisten er ufuldstændig "
                "eller har ukendte navne."
            )

        elif not provider_types <= allowed_provider_types:
            reasons.append(
                "Ugyldig leverandørtype "
                "i konfigurationen."
            )

        elif {
            "privat",
            "kommunal",
        } <= provider_types:
            reasons.append(
                "Både privat og kommunal leverandør."
            )

        else:
            provider = (
                config.TARGET_MUNICIPAL
                if "kommunal" in provider_types
                else config.TARGET_DEFAULT
            )

    return {
        "dry_run": True,
        "would_route": (
            "manual"
            if reasons
            else "automatic"
        ),
        "manual_reasons": sorted(set(reasons)),
        "priority_candidate": priority,
        "provider_candidate": provider,
        "level_candidate": (
            config.LEVEL_NAMES.get(level)
        ),
        "subtype_code_candidate": (
            config.LEVEL_CODES.get(level)
        ),
        "startup_service_candidate": (
            config.STARTUP_SERVICES.get(area)
        ),
        "cura_actions_performed": False,
        "mail_sent": False,
    }