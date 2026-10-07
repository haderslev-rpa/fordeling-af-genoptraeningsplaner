"""Kun læsning af CURA-data. Ingen POST/PUT til forretningsressourcer."""
from datetime import datetime
from zoneinfo import ZoneInfo
import configuration as config


def get_services(borger_id):
    """Henter alle sider, normaliserer og markerer aktive/fremtidige ydelser."""
    from q_cura_api import api_client
    from q_cura_api.functionality.borger_ydelser import (
        borger_ydelser_hent,
        _normaliser_ydelse,
    )

    bundle = borger_ydelser_hent(borger_id, raw=True)
    resources, seen = {}, set()

    while True:
        if (
            not isinstance(bundle, dict)
            or bundle.get("resourceType") != "Bundle"
        ):
            raise RuntimeError(
                "Ydelsesopslaget returnerede ikke et FHIR Bundle."
            )

        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "ProcedureRequest":
                if not resource.get("id"):
                    raise RuntimeError("Ydelse mangler id.")
                resources[resource["id"]] = resource

        links = [
            x["url"]
            for x in bundle.get("link", [])
            if x.get("relation") == "next"
        ]
        if not links:
            break

        url = links[0]
        if url in seen or not url.startswith(api_client.BASE_URL):
            raise RuntimeError("Ugyldigt eller gentaget pagination-link.")

        seen.add(url)
        bundle = api_client.get(
            url[len(api_client.BASE_URL):], raw=True
        )

    today = datetime.now(ZoneInfo(config.SEARCH_TIMEZONE)).date()
    services, issues, names = [], [], {}

    for resource in resources.values():
        service = _normaliser_ydelse(resource)

        if service.get("borger_id") != borger_id:
            raise RuntimeError("Ydelse tilhører en anden borger.")

        service.pop("raw_resource", None)
        service.pop("bemærkninger", None)

        status = service.get("status", "")
        eligible = False

        if status not in config.SERVICE_EXCLUDED_STATUSES:
            if status not in config.SERVICE_INCLUDED_STATUSES:
                issues.append("Ukendt ydelsesstatus: " + str(status))
            else:
                try:
                    start = service.get("startdato") or ""
                    end = service.get("slutdato") or ""

                    start_date = (
                        datetime.fromisoformat(
                            start.replace("Z", "+00:00")
                        ).date()
                        if start else None
                    )
                    end_date = (
                        datetime.fromisoformat(
                            end.replace("Z", "+00:00")
                        ).date()
                        if end else None
                    )

                    if start_date and end_date and start_date > end_date:
                        raise ValueError("Omvendt periode")

                    eligible = end_date is None or end_date >= today

                except (ValueError, TypeError):
                    issues.append("Ugyldig ydelsesperiode.")

        service["eligible"] = eligible

        if eligible and not service.get("performer_name"):
            org_id = service.get("organization_id")

            if org_id:
                if org_id not in names:
                    org = api_client.get(
                        "Organization/" + org_id, raw=True
                    )
                    if (
                        org.get("resourceType") != "Organization"
                        or org.get("id") != org_id
                    ):
                        raise RuntimeError(
                            "Organisationsopslag matcher ikke id."
                        )
                    names[org_id] = org.get("name", "")

                service["performer_name"] = names[org_id]

            if not service.get("performer_name"):
                issues.append(
                    "Relevant ydelse mangler leverandørnavn."
                )

        services.append(service)

    return {
        "items": services,
        "issues": sorted(set(issues)),
        "fetched_at": datetime.now(
            ZoneInfo(config.SEARCH_TIMEZONE)
        ).isoformat(),
    }