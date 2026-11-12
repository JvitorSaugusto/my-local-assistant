# Commit automático por task

Opt-in: ponha `TASK_AUTOCOMMIT=1` no `.env` e reinicie o backend e o worker. Código em `backend/graph/task_commit.py`.

## Quando commita

- **Task determinística** (com `steps`): logo depois de executar e passar nas verificações.
- **Task dinâmica** (LLM): quando você clica em **Aprovar**, com o que a IA mudou (vem do diário de alterações).

Mensagem: `task #<id>: <título>`.

## O que garante que não mistura com o seu trabalho

- Commita só os arquivos que a task tocou (`git commit -- <arquivos>`). O resto do que você tem aberto fica como está.
- Se algum desses arquivos já tinha alterações suas não commitadas antes da task, não commita nada e avisa quais são.
- Nunca commita em `main` nem `master`.
- Ignora arquivos do `.gitignore`, a cópia temporária do dry-run e tasks com `extract_zip` ou `copy_upload`.
- Diferença só de fim de linha (CRLF/LF) não conta como alteração sua.

Se o commit falhar (identidade do git, hook), a task continua concluída e o relatório mostra o motivo.
