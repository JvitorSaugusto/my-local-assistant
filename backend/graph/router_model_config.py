from typing import Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    route: Literal["NORMAL", "CODE", "NOTES"] = Field(
        description="Categoria da intenção principal da mensagem do usuário"
    )