"""Worker: vurderer GOP og kan valgfrit opdatere undertypen i CURA."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import configuration as config
from ai_prompt import build_prompt
from cura_read import get_services
from vurdering import parse_ai, decide

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


def _update_subtype(item, data):
    """Opdaterer kun en godkendt kandidat og gemmer dokumentation i ATS."""
    enabled = getattr(config, "CURA_SUBTYPE_UPDATE_ENABLED", False)
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
        LOGGER.info("CURA-opdatering udeladt: manuel behandling.")
        return

    ai = box.get("ai_result")
    if (
        not isinstance(ai, dict)
        or ai.get("validation_error")
        or ai.get("input_issues")
        or not isinstance(ai.get("result"), dict)
    ):
        raise WorkItemError("AI-grundlaget er ikke gyldigt.")

    subtype_code = decision.get("subtype_code_candidate")
    if subtype_code not in ("BASIC", "ADVANCED"):
        raise WorkItemError("Beslutningen mangler en gyldig undertype.")

    if subtype_code != config.LEVEL_CODES.get(
        ai["result"].get("level_code")
    ):
        raise WorkItemError("Beslutning og AI-niveau stemmer ikke overens.")

    communication_id = box["communication_id"]
    previous = box.get("cura_subtype_update")

    # Bevar dokumentation på tværs af retries og test-refresh.
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

    # Kontrollér beskeden igen lige før en eventuel opdatering.
    current = get_communication_by_id(communication_id, raw=False)
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
                "Den tidligere verificerede undertype er ændret i CURA."
            )
        update_item_data(data, item=item, state=States.SUBTYPE)
        LOGGER.info("Tidligere CURA-opdatering er fortsat verificeret.")
        return

    # Gem hensigten FØR kaldet, så et afbrudt forsøg kan undersøges.
    box["cura_subtype_update"] = {
        "communication_id": communication_id,
        "requested_subtype": subtype_code,
        "started_at": _now(),
        "status": "started",
        "verified": False,
    }
    update_item_data(data, item=item)

    try:
        result = set_rehabilitation_plan_subtype(
            communication_id=communication_id,
            subtype_code=subtype_code,
        )

        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or result.get("verified") is not True
            or result.get("communication_id") != communication_id
            or result.get("stored_subtype") != subtype_code
        ):
            raise RuntimeError("CURA-opdateringen blev ikke verificeret.")

    except Exception as error:
        box["cura_subtype_update"].update({
            "status": "failed_or_unverified",
            "finished_at": _now(),
            "error_type": type(error).__name__,
        })
        update_item_data(data, item=item)
        # Fejl kan være sket efter PUT. Undgå at påstå, at intet er ændret.
        raise WorkItemError(
            "CURA-opdateringen fejlede eller kunne ikke verificeres. "
            "Kontrollér beskeden før genkørsel."
        ) from None

    box["cura_subtype_update"].update({
        "status": "verified",
        "finished_at": _now(),
        "verified": True,
        "changed": result.get("changed"),
        "old_subtype": result.get("old_subtype"),
        "stored_subtype": result["stored_subtype"],
    })
    # Testbeslutningen forbliver et forslag; udførelsen dokumenteres separat.
    update_item_data(data, item=item, state=States.SUBTYPE)
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
        raise WorkItemError("Box mangler communication_id eller borger_id.")

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

        # cura_subtype_update må IKKE slettes ved refresh.
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
            update_item_data(data, item=item, state=state)
        else:
            update_item_data(data, item=item)
        LOGGER.info("%s", state)

    # 1. HENT GOP OG DIAGNOSER
    message = get_communication_by_id(communication_id, raw=False)
    if not isinstance(message, dict):
        raise WorkItemError("Uventet format fra beskedopslag.")
    if (
        message.get("communication_id") != communication_id
        or message.get("borger_id") != borger_id
    ):
        raise WorkItemError("Beskeden matcher ikke boxens identifikatorer.")

    content_strings = message.get("content_strings")
    if content_strings is None:
        content_strings = []
    source_diagnoses = message.get("diagnoses")
    if source_diagnoses is None:
        source_diagnoses = []

    if not isinstance(content_strings, list) or any(
        not isinstance(value, str) for value in content_strings
    ):
        raise WorkItemError("Uventet format for GOP-tekst.")
    if not isinstance(source_diagnoses, list) or any(
        not isinstance(diagnose, dict) for diagnose in source_diagnoses
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
        input_issues.append("Diagnosens kodetekst mangler.")
    elif any(
        not isinstance(diagnose["text"], str)
        or not diagnose["text"].strip()
        for diagnose in diagnoses
    ):
        input_issues.append("En eller flere diagnoser mangler kodetekst.")

    save(States.MESSAGE)

    # 2. HENT OPGAVER
    result = get_tasks_for_communication(
        communication_id=communication_id,
        borger_id=borger_id,
        count=config.TASK_SEARCH_COUNT,
        raw=False,
    )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("tasks"), list)
    ):
        raise WorkItemError("Uventet format fra opgaveopslag.")

    tasks = result["tasks"]
    if any(
        not isinstance(task, dict)
        or task.get("communication_id") != communication_id
        or task.get("borger_id") != borger_id
        for task in tasks
    ):
        raise WorkItemError("Opgaver matcher ikke besked/borger.")
    if any(not task.get("task_id") for task in tasks):
        raise WorkItemError("En opgave mangler task_id.")

    box["task_ids"] = [task["task_id"] for task in tasks]
    box["task_count"] = len(tasks)
    box["task_found"] = bool(tasks)
    save(States.TASKS)

    # 4. COPILOT-VURDERING
    if (
        not find_state(data, States.AI)
        or not isinstance(box.get("ai_result"), dict)
    ):
        box.pop("test_decision", None)
        box["ai_result"] = {
            "raw_response": None,
            "result": None,
            "validation_error": None,
            "input_issues": input_issues,
            "prompt_version": config.PROMPT_VERSION,
        }

        if input_issues:
            box["ai_result"]["validation_error"] = (
                "AI-kald udeladt: input mangler."
            )
        else:
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
            box["ai_result"]["raw_response"] = response
            box["ai_result"]["received_at"] = _now()
            box["ai_result"]["validation_error"] = (
                "Svaret er gemt, men endnu ikke valideret."
            )
            update_item_data(data, item=item)

            ai_result, error = parse_ai(response)
            box["ai_result"]["result"] = ai_result
            box["ai_result"]["validation_error"] = error

        save(States.AI)

    # 3 OG 5. YDELSER OG BESLUTNING
    # Ved aktiveret skrivning genberegnes beslutningen med aktuelle ydelser.
    if (
        not find_state(data, States.DECISION)
        or not isinstance(box.get("test_decision"), dict)
        or getattr(config, "CURA_SUBTYPE_UPDATE_ENABLED", False) is True
    ):
        services = get_services(borger_id)
        save(States.SERVICES)
        ai = box["ai_result"]

        box["test_decision"] = decide(
            ai["result"],
            services,
            tasks,
            ai.get("input_issues", input_issues),
            ai["validation_error"],
        )
        save(States.DECISION)

    # 6. VALGFRI RIGTIG OPDATERING
    _update_subtype(item, data)

    # main.py gemmer Completed og kalder item.complete().