"""Response bodies for /templates (plan §7, §8)."""

from pydantic import BaseModel

from app.ingestion.templates import ColumnType, Template


class TemplateColumnOut(BaseModel):
    name: str
    type: ColumnType
    required: bool
    description: str
    example: str
    max_length: int | None
    scale: int | None
    choices: list[str]
    default: str | None


class TemplateOut(BaseModel):
    name: str
    title: str
    description: str
    order: int  # position in the dependency order (§7)
    columns: list[TemplateColumnOut]

    @classmethod
    def build(cls, template: Template, order: int) -> "TemplateOut":
        return cls(
            name=template.name.value,
            title=template.title,
            description=template.description,
            order=order,
            columns=[
                TemplateColumnOut(
                    name=c.name,
                    type=c.type,
                    required=c.required,
                    description=c.description,
                    example=c.example,
                    max_length=c.max_length,
                    scale=c.scale,
                    choices=list(c.choices),
                    default=c.default,
                )
                for c in template.columns
            ],
        )
