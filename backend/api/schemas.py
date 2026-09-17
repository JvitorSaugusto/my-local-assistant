from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class AiRequestSchema(BaseModel):
    message: str
    thread_id: str
    

class ChatRequestSchema(BaseModel):
    title: str


class ChatResponseSchema(BaseModel):
    id: int
    thread_id: str
    title: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class BatchRequestSchema(BaseModel):
    thread_id: str
    prompts: list[str]
    

class GenerateTaskSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str] = Field(default_factory=list)
    reason: str = ""
    repo_path: str
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["pending", "queued", "running", "completed", "failed"] = "pending"
    

class HeavyGeneratedTask(BaseModel):
    title: str = Field(
        description="Título curto e específico da tarefa."
    )

    objective: str = Field(
        description="Objetivo exato da alteração."
    )

    target: str = Field(
        description="Localização exata: arquivo, classe, função, método, rota ou componente."
    )

    logic: str = Field(
        description="Descrição cirúrgica de como a alteração deve ser implementada, usando os nomes reais encontrados no dossiê."
    )

    constraints: str = Field(
        description="Restrições específicas impostas pelo usuário para esta tarefa."
    )

    files: list[str] = Field(
        description="Somente os arquivos realmente envolvidos na tarefa."
    )

    reason: str = Field(
        description="Justificativa técnica baseada nas evidências do dossiê."
    )

    priority: str = Field(
        description="Prioridade técnica da tarefa: alta, média ou baixa."
    )

class HeavyAnalysisSchema(BaseModel):
    analysis: str = Field(
        description=(
            "Sua análise técnica em texto livre (Markdown), destinada ao USUÁRIO. "
            "Explique o diagnóstico, as alternativas consideradas e a decisão tomada. "
            "Se o pedido for apenas uma pergunta ou explicação, coloque aqui a resposta "
            "completa e deixe 'tasks' vazio."
        )
    )
    tasks: list[HeavyGeneratedTask] = Field(
        default_factory=list,
        description=(
            "Tarefas de implementação para o Agente Executor. "
            "OBRIGATÓRIO: Você DEVE gerar pelo menos uma tarefa aqui SEMPRE que o "
            "usuário pedir qualquer alteração, edição ou criação de código/arquivos. "
            "Deixe VAZIO APENAS se for puramente uma pergunta teórica ou dúvida sem intenção "
            "de mexer no código."
        ),
    )
    
class TaskResponseSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str]
    reason: str
    status: str

    class Config:
        from_attributes = True