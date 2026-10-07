"""Worker: vurderer GOP og kan valgfrit opdatere undertypen i CURA."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import configuration as config
from ai_prompt import build_prompt
from cura_read import get_services
from vurdering import parse_ai, decide, validate_result

from automation_server_client import WorkItemError
from q_haderslev_vbo.automation_server.ats_update_item_data import (
    update_item_data,
)
from q_haderslev_vbo.automation_server.ats_find_state import find_state


LOGGER = logging.getLogger(__name__)


class States:
    MESSAGE = "1.0 GOP hentet"
    TASKS = "2.0 Opgaver hentet"
    SERVICES = "3.0 Ydelser hentet"
    AI = "4.0 Copilot vurderet"
    DECISION = "5.0 Testbeslutning gemt"
    SUBTYPE = "6.0 CURA undertype verificeret"


def _now():
    """Returnerer tidspunktet som ISO-tekst."""
    return datetime.now(
        ZoneInfo(config.SEARCH_TIMEZONE)
    ).isoformat()


def _assess_ai(item, data, text, diagnoses, input_issues):
    """Henter, validerer og gemmer et grupperet AI-resultat."""
    if type(config.AI_SAVE_RAW_RESPONSE) is not bool:
        raise ValueError(
            "AI_SAVE_RAW_RESPONSE skal være True eller False."
        )

    box = data["box"]
    box.pop("test_decision", None)

    ai = {
        "result": None,
        "validation_error": None,
        "input_issues": list(input_issues),
        "prompt_version": config.PROMPT_VERSION,
        "received_at": None,
    }
    box["ai_result"] = ai

    if input_issues:
        ai["validation_error"] = (
            "AI-kald udeladt: input mangler."
        )
        return

    from q_sharepoint_api.functionality.copilot_runner import (
        run_copilot,
    )

    response = run_copilot(
        prompt=build_prompt(text, diagnoses),
        files=None,
        include_citations=False,
        simple_output=True,
        site_name=config.COPILOT_SITE,
    )

    if not isinstance(response, str):
        raise WorkItemError(
            "Copilot returnerede ikke det forventede tekstformat."
        )

    ai["received_at"] = _now()
    ai["debug"] = {"raw_response": response}
    ai["validation_error"] = (
        "Svaret er gemt, men endnu ikke valideret."
    )

    # Gem før validering, så et afbrudt forsøg kan undersøges.
    update_item_data(data, item=item)

    result, error = parse_ai(response)
    ai["result"] = result
    ai["validation_error"] = error

    if error is None and not config.AI_SAVE_RAW_RESPONSE:
        ai.pop("debug", None)

    if error:
        LOGGER.warning("AI-svaret blev afvist: %s", error)


def _update_subtype(item, data):
    """Opdaterer kun en godkendt kandidat og gemmer dokumentation."""
    enabled = config.CURA_SUBTYPE_UPDATE_ENABLED

    if type(enabled) is not bool:
        raise ValueError(
            "CURA_SUBTYPE_UPDATE_ENABLED skal være True eller False."
        )

    if not enabled:
        LOGGER.info("CURA-opdatering er slået fra.")
        return

    box = data["box"]
    decision = box.get("test_decision")

    if not isinstance(decision, dict):
        raise WorkItemError("Testbeslutningen mangler.")

    if (
        decision.get("would_route") != "automatic"
        or decision.get("manual_reasons")
    ):
        LOGGER.info(
            "CURA-opdatering udeladt: manuel behandling."
        )
        return

    ai = box.get("ai_result")

    if (
        not isinstance(ai, dict)
        or ai.get("validation_error")
        or ai.get("input_issues")
        or not isinstance(ai.get("result"), dict)
    ):
        raise WorkItemError("AI-grundlaget er ikke gyldigt.")

    result = ai["result"]

    try:
        validate_result(result)
    except ValueError:
        raise WorkItemError(
            "AI-resultatet overholder ikke kontrakten."
        ) from None

    subtype_code = decision.get("subtype_code_candidate")

    if subtype_code not in config.LEVEL_CODES.values():
        raise WorkItemError(
            "Beslutningen mangler en gyldig undertype."
        )

    if subtype_code != config.LEVEL_CODES.get(
        result["niveau"]["kode"]
    ):
        raise WorkItemError(
            "Beslutning og AI-niveau stemmer ikke overens."
        )

    communication_id = box["communication_id"]
    previous = box.get("cura_subtype_update")

    # Dokumentation bevares på tværs af genkørsler.
    if isinstance(previous, dict):
        if (
            previous.get("communication_id") != communication_id
            or previous.get("requested_subtype") != subtype_code
        ):
            raise WorkItemError(
                "Tidligere opdateringsforsøg har en anden kandidat. "
                "Sagen kræver manuel kontrol."
            )

    from q_cura_api.functionality.kommunikation import (
        get_communication_by_id,
        set_rehabilitation_plan_subtype,
    )

    current = get_communication_by_id(
        communication_id,
        raw=False,
    )

    if (
        not isinstance(current, dict)
        or current.get("communication_id") != communication_id
        or current.get("borger_id") != box["borger_id"]
        or current.get("rehabilitation_type") != config.REHABILITATION_TYPE
        or "rehabilitation_subtype" not in current
    ):
        raise WorkItemError(
            "Beskeden kunne ikke godkendes før CURA-opdatering."
        )

    current_subtype = str(
        current["rehabilitation_subtype"] or ""
    ).strip().upper()

    # Overskriv ikke en anden eksisterende klassifikation.
    if current_subtype not in ("", subtype_code):
        raise WorkItemError(
            "Beskeden har allerede en anden undertype. "
            "Sagen kræver manuel kontrol."
        )

    if (
        isinstance(previous, dict)
        and previous.get("verified") is True
    ):
        if current_subtype != subtype_code:
            raise WorkItemError(
                "Den tidligere verificerede undertype "
                "er ændret i CURA."
            )

        if not find_state(data, States.SUBTYPE):
            update_item_data(
                data,
                item=item,
                state=States.SUBTYPE,
            )

        LOGGER.info(
            "Tidligere CURA-opdatering er fortsat verificeret."
        )
        return

    # Gem hensigten før kaldet.
    box["cura_subtype_update"] = {
        "communication_id": communication_id,
        "requested_subtype": subtype_code,
        "started_at": _now(),
        "status": "started",
        "verified": False,
    }
    update_item_data(data, item=item)

    try:
        update_result = set_rehabilitation_plan_subtype(
            communication_id=communication_id,
            subtype_code=subtype_code,
        )

        if (
            not isinstance(update_result, dict)
            or update_result.get("success") is not True
            or update_result.get("verified") is not True
            or update_result.get("communication_id") != communication_id
            or update_result.get("stored_subtype") != subtype_code
        ):
            raise RuntimeError(
                "CURA-opdateringen blev ikke verificeret."
            )

    except Exception as error:
        box["cura_subtype_update"].update({
            "status": "failed_or_unverified",
            "finished_at": _now(),
            "error_type": type(error).__name__,
        })
        update_item_data(data, item=item)

        raise WorkItemError(
            "CURA-opdateringen fejlede eller kunne ikke verificeres. "
            "Kontrollér beskeden før genkørsel."
        ) from None

    box["cura_subtype_update"].update({
        "status": "verified",
        "finished_at": _now(),
        "verified": True,
        "changed": update_result.get("changed"),
        "old_subtype": update_result.get("old_subtype"),
        "stored_subtype": update_result["stored_subtype"],
    })

    if not find_state(data, States.SUBTYPE):
        update_item_data(
            data,
            item=item,
            state=States.SUBTYPE,
        )
    else:
        update_item_data(data, item=item)

    LOGGER.info("%s", States.SUBTYPE)


async def behandel_page(item, session=None, page=None):
    """Behandler ét item. main.py ejer afslutning og fejlhåndtering."""
    from q_cura_api.api_client import set_cura_credential
    from q_cura_api.functionality.kommunikation import (
        get_communication_by_id,
    )
    from q_cura_api.functionality.opgaver import (
        get_tasks_for_communication,
    )

    data = item.data
    update_item_data(data, update=False)
    box = data["box"]

    communication_id = box.get("communication_id")
    borger_id = box.get("borger_id")

    if not all(
        isinstance(value, str) and value.strip()
        for value in (communication_id, borger_id)
    ):
        raise WorkItemError(
            "Box mangler communication_id eller borger_id."
        )

    # Disse arbejdsdata hentes lokalt og gemmes ikke i box.
    for key in (
        "gop_input",
        "tasks",
        "services",
        "rehabilitation_type",
        "rehabilitation_subtype",
    ):
        box.pop(key, None)

    if config.TEST_REFRESH_ON_START:
        for key in ("ai_result", "test_decision", "test_run"):
            box.pop(key, None)

        # Tidligere CURA-opdateringsdokumentation bevares.
        data["state"] = []
        data["status"] = {}
        data["defer"] = None

        box["test_run"] = {
            "started_at": _now(),
            "prompt_version": config.PROMPT_VERSION,
        }

    update_item_data(data, item=item)
    set_cura_credential(config.CURA_CREDENTIAL_NAME)

    def save(state):
        if not find_state(data, state):
            update_item_data(
                data,
                item=item,
                state=state,
            )
        else:
            update_item_data(data, item=item)

        LOGGER.info("%s", state)

    # 1. Hent GOP og diagnoser.
    message = get_communication_by_id(
        communication_id,
        raw=False,
    )

    if not isinstance(message, dict):
        raise WorkItemError(
            "Uventet format fra beskedopslag."
        )

    if (
        message.get("communication_id") != communication_id
        or message.get("borger_id") != borger_id
    ):
        raise WorkItemError(
            "Beskeden matcher ikke boxens identifikatorer."
        )

    content_strings = message.get("content_strings")
    if content_strings is None:
        content_strings = []

    source_diagnoses = message.get("diagnoses")
    if source_diagnoses is None:
        source_diagnoses = []

    if not isinstance(content_strings, list) or any(
        not isinstance(value, str)
        for value in content_strings
    ):
        raise WorkItemError("Uventet format for GOP-tekst.")

    if not isinstance(source_diagnoses, list) or any(
        not isinstance(diagnose, dict)
        for diagnose in source_diagnoses
    ):
        raise WorkItemError("Uventet format for diagnoser.")

    diagnoses = [
        {
            "code": diagnose.get("code"),
            "code_type": diagnose.get("code_type"),
            "text": diagnose.get("text"),
        }
        for diagnose in source_diagnoses
    ]

    box["diagnoses"] = diagnoses
    text = "\n\n".join(content_strings)
    input_issues = []

    if not text.strip():
        input_issues.append("GOP-tekst mangler.")

    if not diagnoses:
        input_issues.append(
            "Diagnosens kodetekst mangler."
        )
    elif any(
        not isinstance(diagnose["text"], str)
        or not diagnose["text"].strip()
        for diagnose in diagnoses
    ):
        input_issues.append(
            "En eller flere diagnoser mangler kodetekst."
        )

    save(States.MESSAGE)

    # 2. Hent opgaver.
    task_result = get_tasks_for_communication(
        communication_id=communication_id,
        borger_id=borger_id,
        count=config.TASK_SEARCH_COUNT,
        raw=False,
    )

    if (
        not isinstance(task_result, dict)
        or not isinstance(task_result.get("tasks"), list)
    ):
        raise WorkItemError(
            "Uventet format fra opgaveopslag."
        )

    tasks = task_result["tasks"]

    if any(
        not isinstance(task, dict)
        or task.get("communication_id") != communication_id
        or task.get("borger_id") != borger_id
        for task in tasks
    ):
        raise WorkItemError(
            "Opgaver matcher ikke besked/borger."
        )

    if any(not task.get("task_id") for task in tasks):
        raise WorkItemError(
            "En opgave mangler task_id."
        )

    box["task_ids"] = [
        task["task_id"] for task in tasks
    ]
    box["task_count"] = len(tasks)
    box["task_found"] = bool(tasks)
    save(States.TASKS)

    # 4. Hent og valider grupperet AI-resultat.
    if (
        not find_state(data, States.AI)
        or not isinstance(box.get("ai_result"), dict)
    ):
        _assess_ai(
            item=item,
            data=data,
            text=text,
            diagnoses=diagnoses,
            input_issues=input_issues,
        )
        save(States.AI)

    # 3 og 5. Hent ydelser og beregn beslutning.
    if (
        not find_state(data, States.DECISION)
        or not isinstance(box.get("test_decision"), dict)
        or config.CURA_SUBTYPE_UPDATE_ENABLED is True
    ):
        services = get_services(borger_id)
        save(States.SERVICES)

        ai = box["ai_result"]

        box["test_decision"] = decide(
            ai=ai["result"],
            services=services,
            tasks=tasks,
            input_issues=ai["input_issues"],
            validation_error=ai["validation_error"],
        )

        save(States.DECISION)

    # 6. Valgfri rigtig opdatering.
    _update_subtype(item, data)

    # main.py gemmer Completed og kalder item.complete().