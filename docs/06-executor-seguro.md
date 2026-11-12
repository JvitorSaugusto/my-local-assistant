# Executor seguro de tasks

Proteções do executor de microtasks (`backend/graph/executor.py`), todas sem LLM. Ficam em `backend/graph/task_guards.py`.

## Rollback automático

Se um passo falhar, ou se a verificação final falhar, os arquivos que a task tocou voltam ao estado de antes (`FileSnapshot`). Arquivos criados pela task são removidos. Tasks com `extract_zip` ou `copy_upload` não têm rollback. Desligue com `TASK_ROLLBACK_ON_FAIL=0` no `.env`.

## Cura de espaços no `old`

Quando o `old` de um `replace_text` não bate só por espaços no fim da linha ou indentação, o executor usa o único bloco equivalente do arquivo e avisa no log do passo. Se houver mais de um candidato, não mexe. Desligue com `TASK_HEAL_WHITESPACE=0`.

## Sintaxe de JavaScript e JSON

- `replace_text` em `.js`, `.mjs` e `.cjs` é recusado antes de gravar se deixar o arquivo com erro de sintaxe (usa `node --check`; ignorado se o node não existir ou se o arquivo já estava quebrado).
- Ao final da task, os `.js` e `.json` tocados são conferidos. Desligue com `TASK_JS_CHECK=0`.

## Verificação `pytest`

`{ "type": "pytest", "path": "backend/graph/tests/test_x.py" }` roda o arquivo de teste com o Python do backend (limite de 120 s) e falha a task se algum teste falhar.

## Dry-run ao importar

Depois de importar tasks com `steps`, o front roda o dry-run numa cópia do projeto e avisa quais vão falhar e por quê.
