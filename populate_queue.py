"""Producer for fordeling-af-genoptraeningsplaner.

Alle søge-, filtrerings- og køoprettelsestrin ligger i dette modul.
Modulet ændrer ikke data i CURA. Kun nye ATS-workitems oprettes.
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import configuration as config
from q_cura_api.api_client import set_cura_credential
from q_cura_api.functionality.kommunikation import get_communications_in_period
from q_cura_api.functionality.opgaver import get_tasks_for_communication
from q_haderslev_vbo.automation_server.ats_is_item_in_queue import is_item_in_queue
from q_haderslev_vbo.automation_server.ats_update_item_data import update_item_data
import configuration as config

LOGGER = logging.getLogger(__name__)


def _get_search_period():
    """Returnerer inkluderet start/slut som ISO-tekst med dansk tidszone."""
    start_days = config.SEARCH_START_DAYS_AGO
    end_days = config.SEARCH_END_DAYS_AGO
    for value in (start_days, end_days):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Søgedage skal være ikke-negative heltal.")
    if start_days < end_days:
        raise ValueError("Startdage skal være større end eller lig med slutdage.")

    timezone = ZoneInfo(config.SEARCH_TIMEZONE)
    today = datetime.now(timezone).date()
    start = datetime.combine(
        today - timedelta(days=start_days), time.min, tzinfo=timezone
    )
    end = datetime.combine(
        today - timedelta(days=end_days), time.max, tzinfo=timezone
    ).replace(microsecond=0)
    return start.isoformat(), end.isoformat()


def _required_id(communication, field):
    """Afviser manglende id i stedet for at oprette et ubrugeligt item."""
    value = communication.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Communication mangler {field}.")
    return value.strip()


def _build_box(communication, communication_id):
    """Gemmer id'er og metadata, ikke beskedindhold eller rå ressourcer.

    Task-id'er findes via borgeren og matches på Communication-reference.
    Ingen eller flere match gemmes synligt; der vælges ikke vilkårligt én.
    Worker skal senere hente aktuelle ressourcer og kontrollere relationer.
    """
    borger_id = _required_id(communication, "borger_id")
    result = get_tasks_for_communication(
        communication_id=communication_id,
        borger_id=borger_id,
        count=config.TASK_SEARCH_COUNT,
        raw=False,
    )
    if not isinstance(result, dict) or not isinstance(result.get("tasks"), list):
        raise RuntimeError("Task-opslaget returnerede et uventet format.")
    task_ids = []
    for task in result["tasks"]:
        if not isinstance(task, dict) or not task.get("task_id"):
            raise RuntimeError("En returneret opgave mangler task_id.")
        if task["task_id"] not in task_ids:
            task_ids.append(task["task_id"])

    return {
        "communication_id": communication_id,
        "borger_id": borger_id,
        "received": communication.get("received") or "",
        "sent": communication.get("sent") or "",
        "rehabilitation_type": communication.get("rehabilitation_type") or "",
        "rehabilitation_subtype": communication.get("rehabilitation_subtype") or "",
        "task_found": bool(task_ids),
        "task_count": len(task_ids),
        "task_ids": task_ids,
    }


async def populate_queue(workqueue, debug=False):
    """Opretter items for genoptræningsplaner med blank undertype.

    Beskedtypen læses fra configuration.py.
    Returnerer antal tilføjede og oversprungne beskeder.
    """
    received_from, received_to = _get_search_period()

    message_type = config.MESSAGE_TYPE
    if not isinstance(message_type, str) or not message_type.strip():
        raise ValueError("MESSAGE_TYPE skal være udfyldt i configuration.py.")

    message_type = message_type.strip()

    # Filtrering og box-struktur er lavet til genoptræningsplaner.
    # Stop tydeligt, hvis konfigurationen ændres til en anden type.
    if message_type != "rehabilitation_plan":
        raise ValueError(
            "Denne proces understøtter kun genoptræningsplaner. "
            "MESSAGE_TYPE skal være 'rehabilitation_plan'."
        )

    queue_id = workqueue.id
    if isinstance(queue_id, bool) or queue_id is None or int(queue_id) <= 0:
        raise ValueError("Workqueue mangler et gyldigt teknisk id.")

    count = config.TASK_SEARCH_COUNT
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= 1000
    ):
        raise ValueError(
            "TASK_SEARCH_COUNT skal være et heltal mellem 1 og 1000."
        )

    set_cura_credential(config.CURA_CREDENTIAL_NAME)

    LOGGER.info("Beskedtype fra configuration.py: %s", message_type)
    LOGGER.info("Søger fra %s til %s", received_from, received_to)

    result = get_communications_in_period(
        received_from=received_from,
        received_to=received_to,
        message_type=message_type,
        raw=False,
    )

    if (
        not isinstance(result, dict)
        or not isinstance(result.get("communications"), list)
    ):
        raise RuntimeError(
            "Communication-opslaget returnerede et uventet format."
        )

    added = skipped = 0
    seen = set()

    for communication in result["communications"]:
        if not isinstance(communication, dict):
            raise RuntimeError("En Communication er ikke en dictionary.")

        if "rehabilitation_subtype" not in communication:
            raise RuntimeError(
                "Communication mangler rehabilitation_subtype."
            )

        if str(communication["rehabilitation_subtype"] or "").strip():
            continue

        reference = _required_id(communication, "communication_id")

        if reference in seen or is_item_in_queue(
            queue_id=queue_id,
            item_reference=reference,
        ):
            skipped += 1
            continue

        # Find først opgaver, når beskeden ikke allerede er i køen.
        box = _build_box(communication, reference)

        data = {}
        update_item_data(
            data,
            box_updates=box,
            update=False,
        )

        workqueue.add_item(
            data=data,
            reference=reference,
        )

        seen.add(reference)
        added += 1

        LOGGER.info(
            "Tilføjet %s med %s opgaver",
            reference,
            box["task_count"],
        )

    LOGGER.info("Tilføjet=%s, oversprunget=%s", added, skipped)

    return {
        "added": added,
        "skipped": skipped,
    }
