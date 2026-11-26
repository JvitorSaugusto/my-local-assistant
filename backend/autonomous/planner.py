"""Planejador estruturado por fases para o Modo Autônomo."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .adapters import LLMTextClient, RepoInspectorPort, invoke_structured_json
from .guards import is_protected_relative_path
from .schemas import (
    ChecklistItem,
    ItemStatus,
    MissionMode,
    MissionPhase,
    MissionRecord,
    PhaseStatus,
)


class _PlannedItemDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str
    description: str = ""
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class _PlannedPhaseDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str
    goal: str = ""
    items: list[_PlannedItemDraft] = Field(default_factory=list)


class _PlanDraftResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phases: list[_PlannedPhaseDraft] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_PLANNER_SYSTEM_PROMPT = """Você é o planejador técnico do Modo Autônomo.
Sua função é quebrar o objetivo em FASES ordenadas e ITENS ATÔMICOS verificáveis.

Regras obrigatórias:
1. Cada item deve alterar poucos arquivos (idealmente 1 a 3 arquivos) e ter critérios objetivos de aceite.
2. Nunca inclua arquivos secretos ou proibidos (.env, .git, venv, node_modules).
3. Respeite todas as regras de negócio e convenções fornecidas.
4. Use os símbolos e rotas `[GET/POST ...]` listados na visão geral do repositório para planejar exatamente os arquivos que precisam de alteração (e pule os que já estão corretos).
5. Sempre inclua cobertura de testes (`pytest` em Python; `vitest`/`jest`/Testing Library em JS/TS/React) nos itens que alteram comportamento ou crie um item final de testes por fase.
6. No modo `diagnostic_only`, crie itens de inspeção e levantamento de evidências (somente leitura, sem editar código).
5. No modo `greenfield_phased`, organize estritamente em fases: fundação/estrutura -> modelos/domínio -> serviços/rotas -> testes/integração.
6. Responda EXCLUSIVAMENTE com um JSON válido neste formato:
{
  "phases": [
    {
      "id": "p1",
      "title": "Nome da fase",
      "goal": "Objetivo da fase",
      "items": [
        {
          "id": "p1_i1",
          "title": "Título curto do item atômico",
          "description": "O que verificar/implementar exatamente",
          "target_files": ["caminho/relativo.py"],
          "acceptance_criteria": ["Critério verificável"]
        }
      ]
    }
  ],
  "notes": ["Observação curta opcional"]
}"""


def build_mission_plan(
    mission: MissionRecord,
    llm: LLMTextClient,
    inspector: RepoInspectorPort,
) -> tuple[list[MissionPhase], list[str]]:
    """Gera e sanitiza o plano por fases respeitando budget máximo e proteção de caminhos."""
    overview = inspector.repo_overview(mission.workspace_path)
    detect_fn = getattr(inspector, "detect_project_stacks", None)
    stacks = sorted(detect_fn(mission.workspace_path)) if callable(detect_fn) else []
    stacks_label = ", ".join(stacks) if stacks else "não detectada"
    rules_txt = "\n".join(f"- {r}" for r in mission.business_rules) or "- (nenhuma regra extra)"
    convs_txt = "\n".join(f"- {c}" for c in mission.conventions) or "- (seguir padrão do repositório)"
    budget_cap = max(1, min(mission.config.max_total_tasks, 40))

    user_prompt = (
        f"Título: {mission.title}\n"
        f"Modo: {mission.mode.value}\n"
        f"Stacks detectadas: {stacks_label}\n"
        f"Limite máximo de itens totais: {budget_cap}\n\n"
        f"Objetivo:\n{mission.objective}\n\n"
        f"Regras de negócio:\n{rules_txt}\n\n"
        f"Convenções:\n{convs_txt}\n\n"
        f"Visão geral do workspace:\n{overview}"
    )

    draft: _PlanDraftResponse = invoke_structured_json(
        llm,
        role="planner",
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_cls=_PlanDraftResponse,
    )

    phases: list[MissionPhase] = []
    seen_item_ids: set[str] = set()
    total_items = 0

    for phase_idx, p_draft in enumerate(draft.phases, start=1):
        phase_id = f"p{phase_idx}"
        items: list[ChecklistItem] = []
        for item_idx, i_draft in enumerate(p_draft.items, start=1):
            if total_items >= budget_cap:
                break
            title = str(i_draft.title or "").strip()
            if not title:
                continue
            raw_id = (i_draft.id or "").strip() or f"{phase_id}_i{item_idx}"
            item_id = raw_id if raw_id not in seen_item_ids else f"{phase_id}_i{item_idx}"
            seen_item_ids.add(item_id)

            safe_targets = [
                t.strip().replace("\\", "/")
                for t in i_draft.target_files
                if str(t or "").strip() and not is_protected_relative_path(t)
            ]
            criteria = [str(c).strip() for c in i_draft.acceptance_criteria if str(c).strip()]
            if not criteria:
                criteria = ["Código válido sintaticamente e consistente com o objetivo da fase."]

            items.append(
                ChecklistItem(
                    id=item_id,
                    phase_id=phase_id,
                    title=title,
                    description=str(i_draft.description or "").strip(),
                    target_files=safe_targets,
                    acceptance_criteria=criteria,
                    status=ItemStatus.PENDING,
                )
            )
            total_items += 1

        if items:
            phases.append(
                MissionPhase(
                    id=phase_id,
                    order=len(phases) + 1,
                    title=str(p_draft.title or f"Fase {len(phases) + 1}").strip(),
                    goal=str(p_draft.goal or "").strip(),
                    status=PhaseStatus.PENDING,
                    items=items,
                )
            )

    if not phases:
        raise ValueError("O planejador não retornou nenhum item executável para a missão.")

    return phases, [str(n).strip() for n in draft.notes if str(n).strip()]
