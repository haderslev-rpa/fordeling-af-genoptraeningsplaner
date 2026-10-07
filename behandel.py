"""Worker-delen for fordeling-af-genoptraeningsplaner.

Denne første version implementerer kun producer-delen, som køres med
--queue. Worker-logikken til klassifikation, undertype og flytning af
opgaven til en anden organisation tilføjes senere.
"""

from automation_server_client import WorkItemError


async def behandel_page(item, session=None, page=None):
    """Stopper tydeligt, hvis processen køres uden --queue endnu."""
    raise WorkItemError(
        "Worker-delen er ikke implementeret endnu. "
        "Kør processen med --queue for at oprette work items."
    )
