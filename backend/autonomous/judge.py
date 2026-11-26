"""Juiz Final isolado (contexto limpo) + gerador de relatório auditável em Markdown."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .adapters import LLMTextClient, invoke_structured_json
from .auditor import AuditReport
from .schemas import MissionRecord, ReviewVerdict
from .state_machine import calculate_progress


class _JudgeDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approved: bool
    summary: str
    findings: list[str] = Field(default_factory=list)
    follow_up_items: list[str] = Field(default_factory=list)


_JUDGE_SYSTEM_PROMPT = """Você é o Juiz Final independente do Modo Autônomo.
Avalie se as entregas realmente cumprem o objetivo principal e todas as regras de negócio,
com base exclusivamente no checklist executado, no relatório objetivo de auditoria e no git diff.

Regras:
1. Nunca aprove se houver falha de teste, erro de sintaxe ou violação de regra de negócio.
2. Só liste `follow_up_items` quando forem correções concretas, objetivas e acionáveis.
3. Não invente arquivos ou bugs que não estejam comprovados no diff/auditoria.
4. Responda EXCLUSIVAMENTE com JSON válido:
{
  "approved": true,
  "summary": "Parecer objetivo em 2-4 frases",
  "findings": ["Achado relevante (ou lista vazia)"],
  "follow_up_items": ["Item concreto de correção se approved=false (ou lista vazia)"]
}"""


def evaluate_final_review(
    mission: MissionRecord,
    audit: AuditReport,
    diff_text: str,
    llm: LLMTextClient,
    *,
    cycle: int,
) -> ReviewVerdict:
    """Executa revisão independente e aplica travas objetivas sobre o veredito do LLM."""
    progress = calculate_progress(mission)
    rules_txt = "\n".join(f"- {r}" for r in mission.business_rules) or "- (nenhuma)"
    items_txt = "\n".join(
        f"- [{item.status.value}] {item.id}: {item.title}"
        + (f" (commit {item.commit_sha[:8]})" if item.commit_sha else "")
        + (f" (erro: {item.last_error[:120]})" if item.last_error and item.status.value == "blocked" else "")
        for phase in sorted(mission.phases, key=lambda p: p.order)
        for item in phase.items
    )

    user_prompt = (
        f"Missão: {mission.title} (ciclo de revisão {cycle})\n"
        f"Modo: {mission.mode.value}\n"
        f"Progresso objetivo: {progress.done_items}/{progress.total_items} concluídos "
        f"({progress.effective_pct:.1f}% efetivo, {progress.blocked_items} bloqueado(s))\n\n"
        f"Objetivo Principal:\n{mission.objective}\n\n"
        f"Regras de Negócio:\n{rules_txt}\n\n"
        f"Checklist:\n{items_txt}\n\n"
        f"Relatório da Auditoria Objetiva:\n{audit.to_short_text()}\n\n"
        f"Git Diff Acumulado:\n{diff_text or '(sem diff)'}"
    )

    draft: _JudgeDraft = invoke_structured_json(
        llm,
        role="judge",
        system_prompt=_JUDGE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_cls=_JudgeDraft,
    )

    findings = [str(f).strip() for f in draft.findings if str(f).strip()]
    follow_ups = [str(f).strip() for f in draft.follow_up_items if str(f).strip()]
    approved = bool(draft.approved)

    # Trava objetiva: auditoria reprovada NUNCA pode ser aprovada pelo juiz LLM
    if not audit.passed:
        approved = False
        for issue in audit.blocking_issues:
            msg = f"[Auditoria] {issue}"
            if msg not in findings:
                findings.insert(0, msg)
        if not follow_ups:
            follow_ups = [f"Corrigir bloqueio de auditoria: {issue[:160]}" for issue in audit.blocking_issues[:3]]

    return ReviewVerdict(
        cycle=cycle,
        approved=approved,
        score_objective_pct=progress.effective_pct,
        summary=str(draft.summary or "").strip() or ("Revisão aprovada." if approved else "Pendências encontradas."),
        findings=findings,
        follow_up_items=follow_ups,
    )


def default_reports_dir() -> Path:
    base = Path(os.getenv("AUTONOMOUS_DATA_DIR") or ".autonomous_data").expanduser().resolve()
    reports = base / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports


def write_mission_report(
    mission: MissionRecord,
    audit: AuditReport | None = None,
    *,
    reports_dir: str | Path | None = None,
) -> Path:
    """Gera relatório final auditável em Markdown com progresso objetivo, commits e parecer."""
    progress = calculate_progress(mission)
    out_dir = Path(reports_dir).expanduser().resolve() if reports_dir else default_reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"mission_{mission.id}.md"

    lines: list[str] = [
        f"# Relatório da Missão Autônoma — {mission.title}",
        "",
        f"- **ID:** `{mission.id}`",
        f"- **Status final:** `{mission.status.value}`",
        f"- **Modo:** `{mission.mode.value}`",
        f"- **Workspace:** `{mission.workspace_path}`",
        f"- **Branch:** `{mission.branch_name or 'N/A'}`",
        f"- **Efetividade objetiva:** **{progress.effective_pct:.1f}%** "
        f"({progress.done_items}/{progress.total_items} concluídos, {progress.blocked_items} bloqueado(s))",
        f"- **Tarefas executadas:** {mission.tasks_executed}/{mission.config.max_total_tasks}",
        f"- **Ciclos de revisão usados:** {mission.review_cycles_used}/{mission.config.max_review_cycles}",
        "",
        "## Objetivo",
        mission.objective.strip(),
    ]

    if mission.business_rules:
        lines.append("")
        lines.append("## Regras de Negócio")
        for r in mission.business_rules:
            lines.append(f"- {r}")

    lines.append("")
    lines.append("## Fases e Itens")
    for phase in sorted(mission.phases, key=lambda p: p.order):
        lines.append(f"### Fase {phase.order}: {phase.title} (`{phase.status.value}`)")
        if phase.goal:
            lines.append(phase.goal)
        for item in phase.items:
            sha = f" · commit `{item.commit_sha[:8]}`" if item.commit_sha else ""
            err = f" · erro: {item.last_error}" if item.last_error and item.status.value == "blocked" else ""
            lines.append(f"- **[{item.status.value}]** `{item.id}` — {item.title} (tentativas: {item.attempts}){sha}{err}")
            for ev in item.evidence[-3:]:
                lines.append(f"  - Evidência: {ev}")
        if phase.audit_summary:
            lines.append(f"- *Auditoria da fase:* {phase.audit_summary}")

    if audit is not None:
        lines.append("")
        lines.append("## Auditoria Final")
        lines.append(audit.to_short_text())

    if mission.reviews:
        lines.append("")
        lines.append("## Parecer do Juiz Final")
        for rev in mission.reviews:
            verdict_txt = "APROVADO" if rev.approved else "REPROVADO"
            lines.append(f"### Ciclo {rev.cycle}: {verdict_txt} ({rev.score_objective_pct:.1f}% efetivo)")
            lines.append(rev.summary)
            if rev.findings:
                lines.append("Achados:")
                lines.extend(f"- {f}" for f in rev.findings)
            if rev.follow_up_items:
                lines.append("Correções sugeridas:")
                lines.extend(f"- {f}" for f in rev.follow_up_items)

    if mission.decisions:
        lines.append("")
        lines.append("## Log de Decisões")
        for dec in mission.decisions:
            tag = f"`{dec.item_id}` " if dec.item_id else ""
            lines.append(f"- {tag}{dec.summary}")

    report_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return report_file
