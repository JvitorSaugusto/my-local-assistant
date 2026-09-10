from typing import Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    route: Literal["NORMAL", "CODE", "NOTES", "HEAVY", "GENERATE_DISPATCH"] = Field(
        description=(
            "Categoria da intenção principal da mensagem do usuário.\n"
            "- NORMAL: bate-papo geral ou dúvidas não técnicas.\n"
            "- CODE: dúvidas pontuais de código ou bugs simples.\n"
            "- NOTES: geração ou atualização de anotações/documentação.\n"
            "- HEAVY: análise profunda de arquitetura, repositório ou geração de tarefas.\n"
            "- GENERATE_DISPATCH: ordem para executar ou despachar tarefas de implementação pendentes."
        )
    )