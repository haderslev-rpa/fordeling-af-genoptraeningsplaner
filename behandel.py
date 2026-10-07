"""Worker: læser CURA, kalder Copilot og gemmer testresultat i ATS."""

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


async def behandel_page(item, session=None, page=None):
    """Behandler ét item og gemmer Copilot-svaret som dokumentation."""
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

    # Arbejdsdata gemmes ikke permanent.
    for key in (
        "gop_input",
        "tasks",
        "services",
        "rehabilitation_type",
        "rehabilitation_subtype",
    ):
        box.pop(key, None)

    if config.TEST_REFRESH_ON_START:
        for key in (
            "ai_result",
            "test_decision",
            "test_run",
        ):
            box.pop(key, None)

        data["state"] = []
        data["status"] = {}
        data["defer"] = None

        box["test_run"] = {
            "started_at": datetime.now(
                ZoneInfo(config.SEARCH_TIMEZONE)
            ).isoformat(),
            "prompt_version": config.PROMPT_VERSION,
        }

    update_item_data(data, item=item)
    set_cura_credential(config.CURA_CREDENTIAL_NAME)

    def save(state):
        """Gemmer data og tilføjer staten, hvis den mangler."""
        if not find_state(data, state):
            update_item_data(data, item=item, state=state)
        else:
            update_item_data(data, item=item)

        # Svartekst og borgeroplysninger skrives ikke i loggen.
        LOGGER.info("%s", state)

    # --------------------------------------------------------
    # 1. HENT GOP
    # --------------------------------------------------------
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

    # Type og undertype kontrolleres kun i producer-delen.
    content_strings = message.get("content_strings") or []
    diagnoses = message.get("diagnoses") or []

    if not isinstance(content_strings, list) or any(
        not isinstance(value, str)
        for value in content_strings
    ):
        raise WorkItemError(
            "Uventet format for GOP-tekst."
        )

    if not isinstance(diagnoses, list) or any(
        not isinstance(diagnose, dict)
        for diagnose in diagnoses
    ):
        raise WorkItemError(
            "Uventet format for diagnoser."
        )

    text = "\n\n".join(content_strings)
    input_issues = []

    if not text.strip():
        input_issues.append("GOP-tekst mangler.")

    if not diagnoses or any(
        not diagnose.get("code")
        for diagnose in diagnoses
    ):
        input_issues.append("Diagnosekode mangler.")

    save(States.MESSAGE)

    # --------------------------------------------------------
    # 2. HENT OPGAVER
    # --------------------------------------------------------
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
        raise WorkItemError(
            "Uventet format fra opgaveopslag."
        )

    tasks = result["tasks"]

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

    box["task_ids"] = [task["task_id"] for task in tasks]
    box["task_count"] = len(tasks)
    box["task_found"] = bool(tasks)

    save(States.TASKS)

    # --------------------------------------------------------
    # 4. COPILOT-VURDERING OG DOKUMENTATION
    # --------------------------------------------------------
    if (
        not find_state(data, States.AI)
        or not isinstance(box.get("ai_result"), dict)
    ):
        # En ny vurdering kræver en ny beslutning.
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

            # Gem hele den returnerede svartekst uden ændringer.
            # Gem FØR parsing, så svaret bevares ved parserfejl.
            box["ai_result"]["raw_response"] = response
            box["ai_result"]["received_at"] = datetime.now(
                ZoneInfo(config.SEARCH_TIMEZONE)
            ).isoformat()
            box["ai_result"]["validation_error"] = (
                "Svaret er gemt, men endnu ikke valideret."
            )
            update_item_data(data, item=item)

            ai_result, error = parse_ai(response)

            # Opdatér felterne uden at overskrive raw_response.
            box["ai_result"]["result"] = ai_result
            box["ai_result"]["validation_error"] = error

        save(States.AI)

    # --------------------------------------------------------
    # 3 OG 5. HENT YDELSER OG GEM TESTBESLUTNING
    # --------------------------------------------------------
    if (
        not find_state(data, States.DECISION)
        or not isinstance(box.get("test_decision"), dict)
    ):
        # Ydelser holdes kun lokalt og hentes ved behov.
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

    # Ingen ændringer i CURA.
    # main.py gemmer Completed og kalder item.complete().

    # Ingen ændringer i CURA i denne implementering.
    # main.py gemmer Completed og kalder item.complete().