"""Input template list and downloads (plan §7, §8 Templates: UPLOADER)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.errors import ApiError
from app.auth.deps import require_role
from app.auth.roles import Role
from app.ingestion.templates import TEMPLATES, get_template, template_csv, template_xlsx
from app.schemas.templates import TemplateOut

router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(require_role(Role.UPLOADER))],
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("", response_model=list[TemplateOut])
def list_templates() -> list[TemplateOut]:
    """All templates in dependency order, with their columns."""
    return [TemplateOut.build(t, order) for order, t in enumerate(TEMPLATES.values(), start=1)]


@router.get(
    "/{name}",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, XLSX: {}}}},
)
def download_template(
    name: str, format: Annotated[Literal["csv", "xlsx"], Query()] = "csv"
) -> Response:
    """Blank template: headers and one example row (§7).

    `format=xlsx` gives a workbook whose cells are text, so Excel keeps leading zeros.
    """
    template = get_template(name)
    if template is None:
        raise ApiError(
            404,
            "NOT_FOUND",
            f"Unknown template {name!r}.",
            {"templates": [t.value for t in TEMPLATES]},
        )
    filename = f"{template.name.value}_template.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "xlsx":
        return Response(template_xlsx(template), media_type=XLSX, headers=headers)
    return Response(template_csv(template), media_type="text/csv; charset=utf-8", headers=headers)
