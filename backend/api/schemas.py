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
    """Schema usado APENAS pelo Heavy ao gerar tarefas.
    Não inclui id/repo_path/status: esses são preenchidos pelo sistema."""

    title: str = Field(
        description=(
            "Título curto e objetivo, focado no RESULTADO da tarefa. "
            "Ex: 'Abrir card de gestão OEE em nova aba'."
        )
    )
    description: str = Field(
        description=(
            "Roteiro COMPLETO e AUTOSSUFICIENTE para o Agente Executor, que NÃO "
            "tem acesso ao dossiê técnico — só a este texto e aos arquivos em 'files'. "
            "OBRIGATÓRIO: (1) se o dossiê contém o trecho de código a alterar, cite "
            "o código ATUAL e o código DEPOIS, ambos em blocos de crases; (2) repita "
            "ao final toda restrição de processo que o usuário pediu (ex: 'NÃO faça "
            "commit — apenas edite e pare'); (3) se alguma dependência deve ser "
            "mockada em vez de lida, diga isso explicitamente. "
            "NUNCA escreva uma descrição genérica de uma linha como 'substituir a "
            "lógica para abrir em nova aba' — isso é insuficiente e a tarefa falhará."
        )
    )
    files: list[str] = Field(
        default_factory=list,
        description=(
            "Caminhos relativos dos arquivos que serão criados ou editados "
            "(ex: 'components/quick-access-cards.tsx'). Inclua também arquivos que "
            "o Executor precise LER para concluir a tarefa."
        ),
    )
    reason: str = Field(
        default="",
        description="Por que esta alteração é necessária, do ponto de vista do usuário.",
    )
    priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Urgência da tarefa. Use 'medium' quando não houver indicação clara.",
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