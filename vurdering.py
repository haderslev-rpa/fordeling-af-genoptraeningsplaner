"""Validering og beregning af den vej robotten ville have valgt."""
import json
import configuration as config


def parse_ai(text):
    """Returnerer (resultat, fejl). Ugyldigt svar godkendes aldrig."""
    try:
        value = text.strip()
        if value.startswith("```json") and value.endswith("```"):
            value = value[7:-3].strip()

        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("Ikke et JSON-objekt")

        for key in ("level_confidence", "clinical_area_confidence"):
            if type(result[key]) is not int or not 0 <= result[key] <= 100:
                raise ValueError("Ugyldig sikkerhedsgrad")

        if result["level_code"] not in (None, "A", "B"):
            raise ValueError("Ugyldigt niveau")

        if result["clinical_area"] not in (None, *config.STARTUP_SERVICES):
            raise ValueError("Ugyldigt fagområde")

        for key in ("heart_related", "cancer_related"):
            if type(result[key]) is not bool:
                raise ValueError("Ugyldigt flag")

        if (
            result["diagnosis_consistent"] is not None
            and type(result["diagnosis_consistent"]) is not bool
        ):
            raise ValueError("Ugyldig diagnosekontrol")

        for key in ("missing_information", "conflicting_information"):
            if (
                not isinstance(result[key], list)
                or not all(isinstance(x, str) for x in result[key])
            ):
                raise ValueError("Ugyldig liste")

        for key in (
            "level_reason",
            "clinical_area_reason",
            "diagnosis_comparison_reason",
        ):
            if not isinstance(result[key], str) or not result[key].strip():
                raise ValueError("Manglende begrundelse")

        if (
            result["manual_review_reason"] is not None
            and not isinstance(result["manual_review_reason"], str)
        ):
            raise ValueError("Ugyldig manuel årsag")

        return result, None

    except (ValueError, TypeError, KeyError, AttributeError):
        return None, "Copilot-svaret overholder ikke JSON-kontrakten."


def decide(ai, services, tasks, input_issues, validation_error=None):
    """Returnerer testbeslutning. Udfører ingen handlinger."""
    reasons = list(input_issues) + list(services["issues"])
    provider = priority = None

    if validation_error:
        reasons.append(validation_error)

    if not tasks:
        reasons.append("Ingen tilknyttet opgave.")
    elif len(tasks) != 1:
        reasons.append(
            "Flere tilknyttede opgaver; ingen vælges automatisk."
        )

    if ai:
        if ai["diagnosis_consistent"] is not True:
            reasons.append(
                "Diagnose og tekst er modstridende eller ikke afklaret."
            )

        if ai["level_code"] is None or ai["clinical_area"] is None:
            reasons.append("Niveau eller fagområde er ikke afklaret.")

        if min(
            ai["level_confidence"],
            ai["clinical_area_confidence"],
        ) <= config.CONFIDENCE_THRESHOLD:
            reasons.append(
                "Sikkerheden er ikke over tærsklen for begge vurderinger."
            )

        reasons.extend(
            ai["missing_information"] + ai["conflicting_information"]
        )

        if ai["manual_review_reason"]:
            reasons.append(ai["manual_review_reason"])

        if ai["heart_related"] and (
            ai["level_code"] != "A"
            or ai["clinical_area"] != "Medicinsk"
        ):
            reasons.append("Hjertereglen er ikke overholdt.")

        if ai["cancer_related"] != (ai["clinical_area"] == "Kræft"):
            reasons.append(
                "Kræftflag og fagområde er inkonsistente."
            )

        if ai["heart_related"] and ai["cancer_related"]:
            reasons.append("Hjerte og kræft kræver afklaring.")

    names = {
        s["performer_name"]
        for s in services["items"]
        if s["eligible"] and s.get("performer_name")
    }

    if config.PROVIDER_DOGN in names:
        provider, priority = config.TARGET_DOGN, "P1"

    elif ai and (ai["heart_related"] or ai["cancer_related"]):
        provider, priority = config.TARGET_SPECIAL, "P2"

    elif config.PROVIDER_AFKLARING in names:
        provider, priority = config.TARGET_AFKLARING, "P3"

    else:
        priority = "P4"
        unknown = names - config.PROVIDER_TYPES.keys()
        types = {
            config.PROVIDER_TYPES[n]
            for n in names
            if n in config.PROVIDER_TYPES
        }

        if unknown or not config.PROVIDER_LIST_COMPLETE:
            reasons.append(
                "P4-leverandørlisten er ufuldstændig "
                "eller har ukendte navne."
            )

        elif not types <= {"privat", "kommunal", "ikke_relevant"}:
            reasons.append(
                "Ugyldig leverandørtype i konfigurationen."
            )

        elif {"privat", "kommunal"} <= types:
            reasons.append("Både privat og kommunal leverandør.")

        else:
            provider = (
                config.TARGET_MUNICIPAL
                if "kommunal" in types
                else config.TARGET_DEFAULT
            )

    level = ai.get("level_code") if ai else None
    area = ai.get("clinical_area") if ai else None

    return {
        "dry_run": True,
        "would_route": "manual" if reasons else "automatic",
        "manual_reasons": sorted(set(reasons)),
        "priority_candidate": priority,
        "provider_candidate": provider,
        "level_candidate": config.LEVEL_NAMES.get(level),
        "subtype_code_candidate": config.LEVEL_CODES.get(level),
        "startup_service_candidate": config.STARTUP_SERVICES.get(area),
        "cura_actions_performed": False,
        "mail_sent": False,
    }