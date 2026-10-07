"""Kun læsning af CURA-data. Ingen POST/PUT til forretningsressourcer."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import configuration as config


LOGGER = logging.getLogger(__name__)


def _parse_date(value):
    """Fortolker en valgfri CURA-dato."""
    if value is None or value == "":
        return None

    if not isinstance(value, str):
        raise ValueError(
            "Datoen skal være tekst eller tom."
        )

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).date()


def _fetch_service_resources(borger_id):
    """Henter alle sider med borgerens ProcedureRequest-ressourcer."""
    from q_cura_api import api_client
    from q_cura_api.functionality.borger_ydelser import (
        borger_ydelser_hent,
    )

    bundle = borger_ydelser_hent(
        borger_id,
        raw=True,
    )

    resources = {}
    seen_urls = set()

    while True:
        if (
            not isinstance(bundle, dict)
            or bundle.get("resourceType") != "Bundle"
        ):
            raise RuntimeError(
                "Ydelsesopslaget returnerede ikke et FHIR Bundle."
            )

        entries = bundle.get("entry", [])
        links = bundle.get("link", [])

        if (
            not isinstance(entries, list)
            or not isinstance(links, list)
        ):
            raise RuntimeError(
                "Ydelsesopslaget har et ugyldigt entry/link-format."
            )

        for entry in entries:
            if not isinstance(entry, dict):
                raise RuntimeError(
                    "Uventet entry i ydelsesopslaget."
                )

            resource = entry.get("resource", {})

            if not isinstance(resource, dict):
                raise RuntimeError(
                    "Uventet ydelsesresource."
                )

            if resource.get("resourceType") != "ProcedureRequest":
                continue

            resource_id = resource.get("id")

            if (
                not isinstance(resource_id, str)
                or not resource_id.strip()
            ):
                raise RuntimeError(
                    "Ydelse mangler id."
                )

            resource_id = resource_id.strip()

            if (
                resource_id in resources
                and resources[resource_id] != resource
            ):
                raise RuntimeError(
                    "Samme ydelses-id har forskellige data."
                )

            resources[resource_id] = resource

        next_links = [
            link.get("url")
            for link in links
            if (
                isinstance(link, dict)
                and link.get("relation") == "next"
            )
        ]

        if not next_links:
            return resources

        if (
            len(next_links) != 1
            or not isinstance(next_links[0], str)
            or not next_links[0]
        ):
            raise RuntimeError(
                "Ugyldigt next-link i ydelsesopslaget."
            )

        url = next_links[0]

        if (
            url in seen_urls
            or not url.startswith(api_client.BASE_URL)
        ):
            raise RuntimeError(
                "Ugyldigt eller gentaget pagination-link."
            )

        seen_urls.add(url)

        bundle = api_client.get(
            url[len(api_client.BASE_URL):],
            raw=True,
        )


def get_services(borger_id):
    """Henter og klassificerer borgerens aktive/fremtidige ydelser.

    Returnerer:
        items:
            Alle normaliserede ydelser. P1 og P3 undersøger disse.

        p4_items:
            Kun aktive/fremtidige ydelser, hvis organization_id findes
            i P4-kataloget.

        issues:
            Dataproblemer, som skal føre til manuel behandling.

        statistics:
            Optælling af hentede, relevante og oversprungne ydelser.
    """
    from organisation_catalogue import (
        get_organisation_by_id,
    )
    from q_cura_api.functionality.borger_ydelser import (
        _normaliser_ydelse,
    )

    resources = _fetch_service_resources(
        borger_id
    )

    today = datetime.now(
        ZoneInfo(config.SEARCH_TIMEZONE)
    ).date()

    services = []
    p4_items = []
    issues = []

    statistics = {
        "total": len(resources),
        "eligible": 0,
        "p4_catalogue_matches": 0,
        "skipped_other_organisation": 0,
        "skipped_missing_organisation_id": 0,
    }

    for resource in resources.values():
        service = _normaliser_ydelse(resource)

        if not isinstance(service, dict):
            raise RuntimeError(
                "Normalisering af ydelse returnerede "
                "ikke en dictionary."
            )

        if service.get("borger_id") != borger_id:
            raise RuntimeError(
                "Ydelse tilhører en anden borger."
            )

        service.pop("raw_resource", None)
        service.pop("bemærkninger", None)

        status = service.get("status", "")
        eligible = False

        if status in config.SERVICE_EXCLUDED_STATUSES:
            eligible = False

        elif status not in config.SERVICE_INCLUDED_STATUSES:
            issues.append(
                "Ukendt ydelsesstatus: " + str(status)
            )

        else:
            try:
                start_date = _parse_date(
                    service.get("startdato")
                )
                end_date = _parse_date(
                    service.get("slutdato")
                )

                if (
                    start_date is not None
                    and end_date is not None
                    and start_date > end_date
                ):
                    raise ValueError(
                        "Ydelsens startdato ligger efter slutdatoen."
                    )

                # En ydelse er relevant, hvis perioden ikke er udløbet.
                # Dette omfatter både aktive og fremtidige ydelser.
                eligible = (
                    end_date is None
                    or end_date >= today
                )

            except (TypeError, ValueError):
                issues.append(
                    "Ugyldig ydelsesperiode."
                )

        service["eligible"] = eligible
        service["p4_relevant"] = False
        service["p4_provider_type"] = None
        service["p4_source_type"] = None
        service["p4_root_names"] = []

        services.append(service)

        if not eligible:
            continue

        statistics["eligible"] += 1

        organization_id = service.get(
            "organization_id"
        )

        if not isinstance(organization_id, str):
            statistics[
                "skipped_missing_organisation_id"
            ] += 1
            continue

        organization_id = organization_id.strip()

        if not organization_id:
            statistics[
                "skipped_missing_organisation_id"
            ] += 1
            continue

        catalogue_organization = get_organisation_by_id(
            organization_id
        )

        if catalogue_organization is None:
            # Organisationen er ikke hjemmepleje eller plejehjem
            # ifølge kataloget. Ydelsen er derfor ikke relevant for P4.
            statistics[
                "skipped_other_organisation"
            ] += 1
            continue

        service["p4_relevant"] = True
        service["p4_provider_type"] = (
            catalogue_organization["provider_type"]
        )
        service["p4_source_type"] = (
            catalogue_organization["source_type"]
        )
        service["p4_root_names"] = list(
            catalogue_organization["root_names"]
        )

        # Brug katalogets navn som dokumentation.
        # Der foretages ikke et separat Organization/{id}-kald.
        service["performer_name"] = (
            catalogue_organization.get("name")
            or service.get("performer_name")
        )

        p4_items.append(service)

        statistics[
            "p4_catalogue_matches"
        ] += 1

    unique_issues = sorted(set(issues))

    LOGGER.info(
        (
            "Ydelser behandlet: total=%s, eligible=%s, "
            "p4_match=%s, anden_organisation=%s, "
            "mangler_organisations_id=%s"
        ),
        statistics["total"],
        statistics["eligible"],
        statistics["p4_catalogue_matches"],
        statistics["skipped_other_organisation"],
        statistics["skipped_missing_organisation_id"],
    )

    return {
        "items": services,
        "p4_items": p4_items,
        "issues": unique_issues,
        "statistics": statistics,
        "fetched_at": datetime.now(
            ZoneInfo(config.SEARCH_TIMEZONE)
        ).isoformat(),
    }