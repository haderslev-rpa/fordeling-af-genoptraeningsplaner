"""Producer: kun GENERALIZED med blank undertype. Ingen ændringer i CURA."""
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import configuration as config
from q_haderslev_vbo.automation_server.ats_is_item_in_queue import is_item_in_queue
from q_haderslev_vbo.automation_server.ats_update_item_data import update_item_data

LOGGER = logging.getLogger(__name__)


def _get_search_period():
    start, end = config.SEARCH_START_DAYS_AGO, config.SEARCH_END_DAYS_AGO
    if any(type(x) is not int or x < 0 for x in (start, end)) or start < end:
        raise ValueError("Søgedage skal være heltal: start >= slut >= 0.")

    tz = ZoneInfo(config.SEARCH_TIMEZONE)
    today = datetime.now(tz).date()
    return (
        datetime.combine(
            today - timedelta(days=start), time.min, tzinfo=tz
        ).isoformat(),
        datetime.combine(
            today - timedelta(days=end), time.max, tzinfo=tz
        ).isoformat(),
    )


def _required_id(message, key):
    value = message.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Beskeden mangler " + key)
    return value.strip()


async def populate_queue(workqueue, debug=False):
    from q_cura_api.api_client import set_cura_credential
    from q_cura_api.functionality.kommunikation import get_communications_in_period
    from q_cura_api.functionality.opgaver import get_tasks_for_communication

    if (
        config.MESSAGE_TYPE != "rehabilitation_plan"
        or config.REHABILITATION_TYPE != "GENERALIZED"
    ):
        raise ValueError("Denne proces understøtter kun almen genoptræning.")

    set_cura_credential(config.CURA_CREDENTIAL_NAME)
    start, end = _get_search_period()

    result = get_communications_in_period(
        received_from=start,
        received_to=end,
        message_type=config.MESSAGE_TYPE,
        count=config.COMMUNICATION_SEARCH_COUNT,
        raw=False,
    )

    messages = result.get("communications")
    if not isinstance(messages, list):
        raise RuntimeError("Uventet beskedformat.")

    total = result.get("bundle_total")
    if (
        isinstance(total, int) and total > len(messages)
    ) or len(messages) >= config.COMMUNICATION_SEARCH_COUNT:
        raise RuntimeError(
            "Muligt ufuldstændigt opslag. Forkort søgeperioden; "
            "pagination skal afklares."
        )

    added, skipped, seen = 0, 0, set()

    for message in messages:
        if message.get("rehabilitation_type") != config.REHABILITATION_TYPE:
            skipped += 1
            continue

        if "rehabilitation_subtype" not in message:
            raise RuntimeError("Beskeden mangler rehabilitation_subtype.")

        if str(message["rehabilitation_subtype"] or "").strip():
            skipped += 1
            continue

        reference = _required_id(message, "communication_id")

        if reference in seen or is_item_in_queue(
            queue_id=workqueue.id,
            item_reference=reference,
        ):
            skipped += 1
            continue

        borger_id = _required_id(message, "borger_id")

        tasks = get_tasks_for_communication(
            communication_id=reference,
            borger_id=borger_id,
            count=config.TASK_SEARCH_COUNT,
            raw=False,
        )["tasks"]

        task_ids = list(
            dict.fromkeys(_required_id(t, "task_id") for t in tasks)
        )

        box = {
            "communication_id": reference,
            "borger_id": borger_id,
            "received": message.get("received", ""),
            "sent": message.get("sent", ""),
            "rehabilitation_type": message["rehabilitation_type"],
            "rehabilitation_subtype": message["rehabilitation_subtype"],
            "task_ids": task_ids,
            "task_count": len(task_ids),
            "task_found": bool(task_ids),
        }

        data = update_item_data({}, box_updates=box, update=False)
        workqueue.add_item(data=data, reference=reference)

        seen.add(reference)
        added += 1

    LOGGER.info("Tilføjet=%s, oversprunget=%s", added, skipped)
    return {"added": added, "skipped": skipped}