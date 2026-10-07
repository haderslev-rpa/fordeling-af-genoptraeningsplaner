import asyncio
import logging
import os
import sys

# ------------------------------------------------------------
# PROCESS-KODE (ET ITEM)
# ------------------------------------------------------------
from behandel import behandel_page

# ------------------------------------------------------------
# AUTOMATION SERVER
# ------------------------------------------------------------
from automation_server_client import (
    AutomationServer,
    Workqueue,
    WorkItemError,
    WorkItemStatus,
)
from q_haderslev_vbo.automation_server.ats_update_item_data import (
    update_item_data,
)


def _vaelg_items_til_behandling(workqueue: Workqueue):
    """Returnerer hele køen eller ét NEW-item til lokal debug."""
    item_reference = os.getenv("DEBUG_ITEM_REFERENCE", "").strip()

    if not item_reference:
        return workqueue

    items = workqueue.get_item_by_reference(
        reference=item_reference,
        status=WorkItemStatus.NEW,
    )
    if not items:
        raise RuntimeError(
            f"Ingen NEW-items fundet med reference: {item_reference}"
        )

    item = items[0]
    item.update_status(
        WorkItemStatus.IN_PROGRESS.value,
        "Startet via lokal debugkørsel",
    )
    return [item]


# ------------------------------------------------------------
# LOGGING (STANDARD)
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("automation_server_client").setLevel(logging.WARNING)
logging.getLogger("debugpy").setLevel(logging.WARNING)


# ------------------------------------------------------------
# QUEUE-MODE (PRODUCER)
# ------------------------------------------------------------
async def populate_queue(workqueue: Workqueue, debug: bool):
    """Starter producer-logikken i populate_queue.py.

    Returnerer modulets resultat med added og skipped.
    """
    logger = logging.getLogger(__name__)
    logger.info("Populate queue mode started")

    # Modulnavnet får et alias, så det ikke forveksles med funktionen.
    import populate_queue as queue_producer

    return await queue_producer.populate_queue(
        workqueue=workqueue,
        debug=debug,
    )


# ------------------------------------------------------------
# PROCESS-MODE (WORKER)
# ------------------------------------------------------------
async def process_workqueue(workqueue: Workqueue, debug: bool):
    """Skabelonens worker-flow uden Playwright."""
    logger = logging.getLogger(__name__)
    logger.info("Process workqueue mode started (debug=%s)", debug)

    for item in _vaelg_items_til_behandling(workqueue):
        with item:
            data = item.data

            try:
                print("================ NEXT ITEM ================")
                print(f"ITEM = ID: {item.id} - Reference: {item.reference}")

                # Ingen browser i denne API-baserede version.
                await behandel_page(item=item, session=None, page=None)

                update_item_data(
                    data,
                    item=item,
                    status="Completed",
                    status_code="Færdig",
                    state="Completed",
                )
                item.update(data)
                item.complete("Completed")

            except WorkItemError as error:
                # SOFT ERROR: Item fejler, næste item kan behandles.
                logger.error(
                    "WorkItemError for item %s: %s",
                    item.reference,
                    error,
                )
                item.fail(str(error))

            except Exception:
                # HARD ERROR: Stop hele processen.
                logger.exception("Uventet fejl")
                raise


# ------------------------------------------------------------
# MAIN ENTRY POINT
# ------------------------------------------------------------
if __name__ == "__main__":
    DEBUG = "--debug" in sys.argv
    QUEUE_MODE = "--queue" in sys.argv

    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # --------------------------------------------------------
    # QUEUE-MODE
    # --------------------------------------------------------
    if QUEUE_MODE:
        # Bevar eksisterende NEW-items. Dubletkontrollen ligger
        # i populate_queue.py, så køen skal ikke ryddes.
        # workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue, debug=DEBUG))
        sys.exit(0)

    # --------------------------------------------------------
    # PROCESS-MODE
    # --------------------------------------------------------
    # Midlertidig sikkerhedslås: Kun producer-delen er implementeret.
    # Fjern dette stop, når behandel.py indeholder den rigtige worker.
    raise SystemExit("Worker er ikke implementeret endnu. Brug --queue.")

    asyncio.run(process_workqueue(workqueue, debug=DEBUG))