from pydantic import BaseModel, Field, field_validator
from typing import Annotated, Literal, Union
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
    

# ----------------------------------------------------------------------
# MICROTASKS EXECUTÁVEIS
# Cada passo é uma operação EXATA (sem LLM): quem planeja (ex.: Claude) já
# entrega o texto/código final, e o executor apenas aplica e verifica.
# ----------------------------------------------------------------------

class _PathMixin(BaseModel):
    path: str = Field(description="Caminho RELATIVO à raiz do workspace.")

    @field_validator("path")
    @classmethod
    def _path_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("path não pode ser vazio")
        return value


class StepCreateBranch(BaseModel):
    op: Literal["create_branch"]
    branch: str = Field(description="Ex.: feature/pdf-tools. Se já estiver numa branch segura, é reaproveitada.")


class StepCreateFile(_PathMixin):
    op: Literal["create_file"]
    content: str = Field(description="Conteúdo COMPLETO do arquivo novo.")


class StepReplaceText(_PathMixin):
    op: Literal["replace_text"]
    old: str = Field(description="Trecho EXATO atual do arquivo (único, ou use occurrences='all').")
    new: str = Field(description="Trecho novo que o substitui.")
    occurrences: Literal["one", "all"] = "one"


class StepAppend(_PathMixin):
    op: Literal["append"]
    content: str


class StepWriteMarkdown(_PathMixin):
    op: Literal["write_markdown"]
    content: str
    overwrite: bool = False


class StepCreatePdf(_PathMixin):
    op: Literal["create_pdf"]
    content: str = Field(description="Conteúdo em Markdown.")
    title: str = ""
    overwrite: bool = False


class StepCopyUpload(_PathMixin):
    op: Literal["copy_upload"]
    source: str = Field(description="NOME do arquivo anexado (ex.: favicon.png), enviado pelo botão Anexar.")
    overwrite: bool = False

    @field_validator("source")
    @classmethod
    def _source_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source não pode ser vazio")
        return value


class StepExtractZip(_PathMixin):
    op: Literal["extract_zip"]
    source: str = Field(description="NOME do .zip anexado. `path` é a PASTA de destino ('.' = raiz).")
    on_conflict: Literal["skip", "overwrite"] = "skip"
    strip_top_folder: bool = True

    @field_validator("source")
    @classmethod
    def _source_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source não pode ser vazio")
        return value


TaskStep = Annotated[
    Union[
        StepCreateBranch,
        StepCreateFile,
        StepReplaceText,
        StepAppend,
        StepWriteMarkdown,
        StepCreatePdf,
        StepCopyUpload,
        StepExtractZip,
    ],
    Field(discriminator="op"),
]


class CheckFileExists(_PathMixin):
    type: Literal["file_exists"]


class CheckContains(_PathMixin):
    type: Literal["contains"]
    text: str


class CheckNotContains(_PathMixin):
    type: Literal["not_contains"]
    text: str


class CheckPythonSyntax(_PathMixin):
    type: Literal["python_syntax"]


class CheckLiteralsGrounded(_PathMixin):
    """Confere, sem LLM, se valores citados no documento `path` existem nas `sources`."""
    type: Literal["literals_grounded"]
    sources: list[str] = Field(min_length=1, description="Arquivos-fonte em que o documento deve se basear.")
    allow: list[str] = Field(default_factory=list, description="Valores permitidos mesmo sem estar nas fontes.")


TaskCheck = Annotated[
    Union[CheckFileExists, CheckContains, CheckNotContains, CheckPythonSyntax, CheckLiteralsGrounded],
    Field(discriminator="type"),
]


class GenerateTaskSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str] = Field(default_factory=list)
    reason: str = ""
    repo_path: str
    priority: Literal["low", "medium", "high"] = "medium"
    code_snippet: str | None = None
    status: Literal["pending", "queued", "running", "review", "completed", "failed"] = "pending"
    verify: list[TaskCheck] = Field(default_factory=list)
    

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

    code_snippet: str = Field(
        default="",
        description=(
            "OPCIONAL. Exemplo de código final de referência (assinatura, model, "
            "regex, bloco de lógica) vindo do dossiê ou do pedido do usuário. "
            "Use string vazia se não houver."
        ),
    )
    
class SecurityFinding(BaseModel):
    category: str = Field(description="Uma das 7 categorias: Injeção, Validação de Entrada, Segredos Expostos, Controle de Acesso, Deserialização Insegura, Path Traversal, Dados em Log.")
    file: str = Field(description="Caminho do arquivo auditado.")
    evidence: str = Field(
        description=(
            "COPIE E COLE o trecho de código EXATO do arquivo. "
            "É estritamente PROIBIDO resumir, explicar ou usar suas próprias palavras neste campo. "
            "Retorne APENAS o código puro que comprova a falha."
        )
    )
    risk: Literal["high", "medium", "low"]
    technical_analysis: str = Field(description="Vetor de ataque e impacto, em 2-3 frases.")
    exploitability_confirmed: bool = Field(
        description="True SOMENTE se há dado externo controlável chegando num sink sensível sem proteção confirmada. NEXT_PUBLIC_*, URL pública, limpeza de cookie no logout = False."
    )


class HeavyAnalysisSchema(BaseModel):
    security_findings: list[SecurityFinding] = Field(
        description=(
            "PREENCHA ESTE CAMPO PRIMEIRO, antes de 'analysis'. No Modo 3: releia "
            "o dossiê inteiro e crie um item para CADA trecho que se encaixe em "
            "uma das 7 categorias, mesmo que marque exploitability_confirmed=False "
            "depois. É PROIBIDO retornar [] sem ter revisado o dossiê linha por "
            "linha primeiro. Nos Modos 1 e 2, retorne []."
        )
    )
    tasks: list[HeavyGeneratedTask] = Field(default_factory=list, description="...")
    analysis: str = Field(
        description=(
            "Escreva DEPOIS de preencher security_findings. No Modo 3: resuma "
            "APENAS os itens com exploitability_confirmed=True já listados acima "
            "— não repita trecho de código aqui, ele já está estruturado. Nos "
            "Modos 1/2: resposta normal."
        )
    )
    
class TaskResponseSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str]
    reason: str
    priority: str = "medium"
    status: str
    code_snippet: str | None = None
    last_error: str | None = None
    steps: list[dict] | None = None
    verify: list[dict] | None = None
    attempts: int = 0

    class Config:
        from_attributes = True
        
        
class TaskCreateSchema(BaseModel):
    title: str
    description: str = ""
    files: list[str] = Field(default_factory=list)
    reason: str = ""
    priority: str = "medium"
    status: str = "pending"
    code_snippet: str | None = None
    steps: list[TaskStep] | None = None
    verify: list[TaskCheck] | None = None



class TaskBulkDeleteSchema(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
