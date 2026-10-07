"""Læs Excel og byg organisationshierarkier i hukommelsen."""

import logging
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

import configuration as config


LOGGER = logging.getLogger(__name__)

_CATALOGUE = None


def _validate_type_mapping():
    """Validerer P4-typerne i configuration.py."""
    mapping = config.P4_ORGANISATION_TYPES

    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(
            "P4_ORGANISATION_TYPES skal være en ikke-tom dictionary."
        )

    allowed_values = {
        "kommunal",
        "privat",
    }

    for source_type, provider_type in mapping.items():
        if (
            not isinstance(source_type, str)
            or not source_type.strip()
        ):
            raise ValueError(
                "Alle nøgler i P4_ORGANISATION_TYPES "
                "skal være ikke-tomme tekster."
            )

        if provider_type not in allowed_values:
            raise ValueError(
                "P4_ORGANISATION_TYPES må kun mappe til "
                "'kommunal' eller 'privat'."
            )


def _read_roots(content, year):
    """Returnerer fanenavn og overordnede organisationer fra Excel."""
    sheet = (
        config.ORGANISATIONS_SHEET_2026
        if year == 2026
        else config.ORGANISATIONS_SHEET_OTHER
    )

    workbook = load_workbook(
        BytesIO(content),
        read_only=True,
        data_only=True,
    )

    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(
                f"Excel-fanen {sheet!r} mangler."
            )

        rows = workbook[sheet].iter_rows(
            max_col=2,
            values_only=True,
        )

        expected_header = (
            "Overordnet organisationsnavn",
            "Type",
        )

        if next(rows, None) != expected_header:
            raise ValueError(
                "Forventede 'Overordnet organisationsnavn' "
                "i A1 og 'Type' i B1."
            )

        roots = {}

        for row_number, row in enumerate(rows, start=2):
            name, category = row

            if name is None and category is None:
                continue

            if not all(
                isinstance(value, str) and value.strip()
                for value in (name, category)
            ):
                raise ValueError(
                    f"Excel-række {row_number} mangler navn eller type."
                )

            name = name.strip()
            category = category.strip()

            if category not in config.P4_ORGANISATION_TYPES:
                raise ValueError(
                    f"Excel-række {row_number} har en ukendt type: "
                    f"{category!r}."
                )

            if name in roots and roots[name] != category:
                raise ValueError(
                    f"Modstridende typer for {name!r}."
                )

            roots[name] = category

        if not roots:
            raise ValueError(
                "Excel-fanen indeholder ingen organisationer."
            )

        return sheet, roots

    finally:
        workbook.close()


def _fetch_organizations():
    """Henter alle organisationssider fra CURA."""
    from q_cura_api import api_client
    from q_cura_api.functionality.organisation_hent import (
        get_organizations,
    )

    bundle = get_organizations(
        search_name=None,
        raw=True,
        include_inactive=True,
    )

    organizations = {}
    seen_urls = set()

    base_url = api_client.BASE_URL
    base_parts = urlsplit(base_url)

    for page_number in range(
        1,
        config.ORGANISATIONS_MAX_PAGES + 1,
    ):
        if (
            not isinstance(bundle, dict)
            or bundle.get("resourceType") != "Bundle"
        ):
            raise RuntimeError(
                "Organisationsopslaget returnerede ikke et Bundle."
            )

        entries = bundle.get("entry", [])
        links = bundle.get("link", [])

        if (
            not isinstance(entries, list)
            or not isinstance(links, list)
        ):
            raise RuntimeError(
                "Uventet entry/link-format i organisationsopslaget."
            )

        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("resource"), dict)
            ):
                raise RuntimeError(
                    "Uventet organisationsresource."
                )

            resource = entry["resource"]

            if resource.get("resourceType") != "Organization":
                continue

            organization_id = resource.get("id")

            if (
                not isinstance(organization_id, str)
                or not organization_id.strip()
            ):
                raise RuntimeError(
                    "En organisation mangler id."
                )

            organization_id = organization_id.strip()

            if (
                organization_id in organizations
                and organizations[organization_id] != resource
            ):
                raise RuntimeError(
                    "Samme organisations-id har forskellige data."
                )

            organizations[organization_id] = resource

        if any(not isinstance(link, dict) for link in links):
            raise RuntimeError(
                "Uventet pagination-link."
            )

        next_links = [
            link.get("url")
            for link in links
            if link.get("relation") == "next"
        ]

        LOGGER.info(
            "Organisationsside %s læst",
            page_number,
        )

        if not next_links:
            return organizations

        if (
            len(next_links) != 1
            or not isinstance(next_links[0], str)
            or not next_links[0]
        ):
            raise RuntimeError(
                "Ugyldigt next-link."
            )

        url = urljoin(base_url, next_links[0])
        parts = urlsplit(url)

        # Der må ikke følges links til et andet CURA-miljø.
        if (
            parts.scheme != base_parts.scheme
            or parts.netloc != base_parts.netloc
            or not url.startswith(base_url)
            or parts.fragment
            or url in seen_urls
        ):
            raise RuntimeError(
                "Ugyldigt eller gentaget pagination-link."
            )

        if page_number == config.ORGANISATIONS_MAX_PAGES:
            raise RuntimeError(
                "Sidegrænsen er nået; organisationslisten "
                "er ikke færdig."
            )

        seen_urls.add(url)

        bundle = api_client.get(
            url[len(base_url):],
            raw=True,
        )

    raise RuntimeError(
        "Ingen afslutning på organisationsopslaget."
    )


def _build_catalogue(roots, organizations):
    """Finder de fire rødder og alle deres efterkommere."""
    children = defaultdict(list)

    for organization_id, organization in organizations.items():
        part_of = organization.get("partOf") or {}

        if not isinstance(part_of, dict):
            raise RuntimeError(
                "Uventet partOf-format."
            )

        reference = part_of.get("reference")

        if reference:
            if (
                not isinstance(reference, str)
                or not reference.startswith("Organization/")
            ):
                raise RuntimeError(
                    "Ukendt partOf-reference."
                )

            children[reference].append(organization_id)

    result_by_id = {}

    for root_name, source_type in roots.items():
        matches = [
            organization_id
            for organization_id, organization
            in organizations.items()
            if organization.get("name") == root_name
        ]

        if len(matches) != 1:
            raise ValueError(
                f"Forventede ét præcist match på {root_name!r}, "
                f"fandt {len(matches)}."
            )

        provider_type = config.P4_ORGANISATION_TYPES[source_type]
        pending = deque([matches[0]])
        visited = set()

        while pending:
            organization_id = pending.popleft()

            if organization_id in visited:
                raise RuntimeError(
                    "Cirkulært organisationshierarki fundet."
                )

            visited.add(organization_id)

            organization = organizations[organization_id]

            pending.extend(
                children.get(
                    "Organization/" + organization_id,
                    [],
                )
            )

            # Inaktive organisationer gennemgås stadig som forældre.
            if (
                not config.ORGANISATIONS_INCLUDE_INACTIVE
                and organization.get("active") is not True
            ):
                continue

            existing = result_by_id.get(organization_id)

            if existing:
                if existing["provider_type"] != provider_type:
                    raise ValueError(
                        "En organisation arver modstridende "
                        "P4-typer."
                    )

                if root_name not in existing["root_names"]:
                    existing["root_names"].append(root_name)

                continue

            result_by_id[organization_id] = {
                "organization_id": organization_id,
                "name": organization.get("name"),
                "active": organization.get("active"),
                "part_of_reference": (
                    organization.get("partOf") or {}
                ).get("reference"),
                "source_type": source_type,
                "provider_type": provider_type,
                "root_names": [root_name],
            }

    organizations_list = sorted(
        result_by_id.values(),
        key=lambda organization: (
            str(organization["name"] or "").casefold(),
            organization["organization_id"],
        ),
    )

    return organizations_list, result_by_id


def initialize_organisations():
    """Genindlæser kataloget før første work item."""
    global _CATALOGUE

    _CATALOGUE = None

    _validate_type_mapping()

    if type(config.ORGANISATIONS_INCLUDE_INACTIVE) is not bool:
        raise ValueError(
            "ORGANISATIONS_INCLUDE_INACTIVE skal være bool."
        )

    if (
        type(config.ORGANISATIONS_MAX_PAGES) is not int
        or config.ORGANISATIONS_MAX_PAGES < 1
    ):
        raise ValueError(
            "ORGANISATIONS_MAX_PAGES skal være "
            "et positivt heltal."
        )

    from q_sharepoint_api.sp_api import get_client
    from q_cura_api.api_client import set_cura_credential

    client = get_client()

    site_id = client.get_site_id(
        config.ORGANISATIONS_SITE
    )

    downloaded = client.download_file_to_memory_by_path(
        site_id=site_id,
        file_path=config.ORGANISATIONS_FILE_PATH,
        save_dir=None,
    )

    year = datetime.now(
        ZoneInfo(config.SEARCH_TIMEZONE)
    ).year

    sheet, roots = _read_roots(
        downloaded["file_bytes"],
        year,
    )

    set_cura_credential(
        config.CURA_CREDENTIAL_NAME
    )

    all_organizations = _fetch_organizations()

    organizations, by_id = _build_catalogue(
        roots,
        all_organizations,
    )

    _CATALOGUE = {
        "sheet": sheet,
        "loaded_at": datetime.now(
            ZoneInfo(config.SEARCH_TIMEZONE)
        ).isoformat(),
        "organizations": organizations,
        "by_id": by_id,
    }

    LOGGER.info(
        "P4-katalog klar: fane=%s, organisationer=%s",
        sheet,
        len(organizations),
    )

    return deepcopy(_CATALOGUE)


def get_organisations():
    """Returnerer en kopi af kataloget uden nye API-kald."""
    if _CATALOGUE is None:
        raise RuntimeError(
            "Organisationskataloget er ikke indlæst."
        )

    return deepcopy(_CATALOGUE)


def get_organisation_by_id(organization_id):
    """Slår ét id op i memory-kataloget uden API-kald."""
    if _CATALOGUE is None:
        raise RuntimeError(
            "Organisationskataloget er ikke indlæst."
        )

    if not isinstance(organization_id, str):
        return None

    organization_id = organization_id.strip()

    if not organization_id:
        return None

    organization = _CATALOGUE["by_id"].get(
        organization_id
    )

    return (
        deepcopy(organization)
        if organization is not None
        else None
    )