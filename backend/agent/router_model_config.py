from typing import Literal
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama

class RouteDecision(BaseModel):
    route: Literal["NORMAL", "CODE", "NOTES"] = Field(
        description="Categoria da intenção principal da mensagem do usuário"
    )

router_llm = ChatOllama(model="llama3.2:1b", temperature=0.0)
router_structured = router_llm.with_structured_output(RouteDecision)