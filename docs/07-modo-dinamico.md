# Modo dinâmico: desfazer e revisar

Tasks com `steps` vazio são executadas pelo LLM (Celery). O diário de alterações (`backend/graph/task_journal.py`) guarda o original de cada arquivo antes de a IA gravar.

## O que ele faz

- **Falhou, desfaz sozinho:** verificação, nenhuma alteração, revisão automática ou exceção desfazem as edições da execução atual. O diff da tentativa continua em "Ver alterações". Desligue com `TASK_ROLLBACK_ON_FAIL=0`.
- **Ver alterações:** mostra só o que a task mudou, inclusive arquivos fora de `files`.
- **Reprovar:** pergunta se deve desfazer as alterações no disco (`POST /api/tasks/{id}/revert`). Arquivos que mudaram depois da task não são tocados e são listados como conflito.
- **Aprovar:** apaga o diário da task.
- **Sintaxe:** `.json` e `.js` gravados pela IA também são conferidos na revisão final, junto com `.py`.

## Onde fica

`~/.assistente_local/task_journal/task_<id>` (ou `TASK_JOURNAL_DIR`). Diários com mais de 14 dias são apagados quando uma nova task começa.
