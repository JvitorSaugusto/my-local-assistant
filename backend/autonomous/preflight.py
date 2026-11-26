"""Análise determinística de Pre-flight: valida clareza do escopo antes de editar arquivos."""

from __future__ import annotations

import re
from pathlib import Path

from .schemas import MissionMode, PreflightReport, ScopeClarity

_AMBIGUOUS_HINTS_RE = re.compile(
    r"\b(?:procure?\s+(?:erros?|bugs?|falhas?)|encontre?\s+(?:erros?|bugs?|falhas?)"
    r"|melhore?\s+tudo|refatore?\s+tudo|otimize?\s+o\s+projeto|revise?\s+geral"
    r"|falhas?\s+de\s+l[óo]gica|veja\s+o\s+que\s+est[áa]\s+errado)\b",
    re.IGNORECASE,
)
_GREENFIELD_HINTS_RE = re.compile(
    r"\b(?:cri[ae]\w*\s+(?:um\s+)?(?:novo\s+)?projeto|mont[ae]\w*\s+(?:um\s+)?projeto"
    r"|do\s+zero|scaffold|bootstrap\s+do\s+projeto)\b",
    re.IGNORECASE,
)
_TARGET_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[\w-]+/)+[\w.-]*|(?<![A-Za-z0-9_])[\w-]+\.(?:py|js|ts|tsx|jsx|mjs|cjs|css|scss|html|sql|json|ya?ml)\b",
    re.IGNORECASE,
)
_ACCEPTANCE_HINTS_RE = re.compile(
    r"\b(?:deve|precisa|crit[ée]rio|testes?|pytest|vitest|jest|eslint|tsc|typecheck|build|"
    r"retornar|status\s+\d{3}|garantir|validar|bloquear|exigir|renderizar|componente|hook|n[ãa]o\s+deve)\b",
    re.IGNORECASE,
)


def analyze_scope_preflight(
    objective: str,
    workspace_path: str,
    *,
    business_rules: list[str] | None = None,
    conventions: list[str] | None = None,
) -> PreflightReport:
    """Avalia o escopo da missão antes de iniciar e identifica lacunas ou necessidade de modo diagnóstico."""
    text = str(objective or "").strip()
    rules = [r.strip() for r in (business_rules or []) if str(r).strip()]
    convs = [c.strip() for c in (conventions or []) if str(c).strip()]

    missing_info: list[str] = []
    warnings: list[str] = []
    questions: list[str] = []

    root = Path(workspace_path).expanduser().resolve() if workspace_path else None
    ws_exists = bool(root and root.is_dir())
    is_git_repo = bool(root and (root / ".git").exists())

    if not ws_exists:
        missing_info.append("O diretório do workspace informado não existe.")
    elif not is_git_repo:
        warnings.append(
            "O workspace ainda não é um repositório Git; o isolamento em branch 'auto/*' exige Git inicializado."
        )

    detected_targets = sorted(dict.fromkeys(m.group(0).strip(".,;:") for m in _TARGET_PATH_RE.finditer(text)))
    is_ambiguous = bool(_AMBIGUOUS_HINTS_RE.search(text))
    is_greenfield = bool(_GREENFIELD_HINTS_RE.search(text))
    has_acceptance = bool(_ACCEPTANCE_HINTS_RE.search(text)) or len(rules) >= 1

    if len(text) < 40:
        missing_info.append("Objetivo muito curto para execução autônoma segura.")
        questions.append("Qual é o resultado exato esperado e quais arquivos/módulos entram no escopo?")

    if not rules:
        missing_info.append("Nenhuma regra de negócio explícita foi informada.")
        questions.append("Existem regras de negócio ou restrições que não podem ser quebradas?")

    if not has_acceptance:
        missing_info.append("Não há critérios objetivos de aceite/validação no objetivo.")
        questions.append("Como validar que o objetivo foi atingido (ex.: testes, status HTTP, contrato de saída)?")

    if not detected_targets and not is_greenfield:
        warnings.append("Nenhum arquivo ou pasta específica foi citada; a descoberta inicial terá que mapear o repo.")

    if is_ambiguous:
        recommended_mode = MissionMode.DIAGNOSTIC_ONLY
        warnings.append(
            "Objetivo aberto/exploratório detectado: recomenda-se rodar primeiro em modo diagnóstico "
            "(somente leitura) para listar evidências reais antes de editar código."
        )
        questions.append("Deseja executar primeiro em modo diagnóstico (somente leitura) ou liberar edição direta?")
    elif is_greenfield:
        recommended_mode = MissionMode.GREENFIELD_PHASED
        warnings.append(
            "Criação de projeto do zero detectada: recomenda-se ativar aprovação por fase (phase gate) "
            "para validar fundação/models antes de gerar rotas e testes."
        )
        if not convs:
            missing_info.append("Stack e convenções do novo projeto não foram declaradas em 'conventions'.")
            questions.append("Qual stack exata (framework, banco, estrutura de pastas, testes) deve ser seguida?")
    else:
        recommended_mode = MissionMode.EDIT

    # Classificação determinística de clareza
    score = 0
    if len(text) >= 60:
        score += 2
    elif len(text) >= 40:
        score += 1
    if rules:
        score += 2
    if has_acceptance:
        score += 2
    if detected_targets or convs:
        score += 1
    if is_ambiguous:
        score -= 3
    if not ws_exists:
        score -= 4

    if score >= 5 and not is_ambiguous:
        clarity = ScopeClarity.HIGH
        band = "alta"
    elif score >= 3:
        clarity = ScopeClarity.MEDIUM
        band = "media"
    else:
        clarity = ScopeClarity.LOW
        band = "baixa"

    requires_confirmation = (
        clarity == ScopeClarity.LOW
        or is_ambiguous
        or not ws_exists
        or len(missing_info) >= 2
    )

    return PreflightReport(
        clarity=clarity,
        recommended_mode=recommended_mode,
        estimated_success_band=band,
        requires_confirmation=requires_confirmation,
        missing_info=missing_info,
        warnings=warnings,
        detected_targets=detected_targets,
        questions_for_user=questions,
    )
