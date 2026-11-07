# Microtasks executáveis

Você me pede (Claude) as tarefas → eu devolvo um **JSON** → você cola em **Importar JSON** no painel de tarefas → `Executar Tarefas`.
Tarefas com `steps` são executadas **sem LLM** (rápido, sem "delírio"); tarefas só com texto continuam indo para o agente como antes.

## Campos da tarefa

| Campo | Obrigatório | Descrição |
|---|---|---|
| `title` | sim | Título curto |
| `description`, `reason`, `files`, `priority` | não | Contexto para você (e para o agente, se não houver `steps`) |
| `steps` | não | Lista de operações **exatas**, executadas em ordem |
| `verify` | não | Verificações pós-execução (a "revisão") |

## Passos (`steps`)

| `op` | Campos | O que faz |
|---|---|---|
| `create_branch` | `branch` | Cria/ativa a branch. Se já estiver numa branch segura, reaproveita |
| `create_file` | `path`, `content` | Cria arquivo **novo** (falha se existir com conteúdo diferente) |
| `replace_text` | `path`, `old`, `new`, `occurrences` (`one`\|`all`) | Troca um trecho **exato**. `old` precisa existir e ser único |
| `append` | `path`, `content` | Adiciona ao final (imports vão para o topo em `.py`) |
| `write_markdown` | `path`, `content`, `overwrite` | Cria `.md`/`.txt` (`overwrite:true` para sobrescrever) |
| `create_pdf` | `path`, `content`, `title`, `overwrite` | PDF a partir de Markdown (títulos, listas, tabelas, código) |

Não existe operação de apagar arquivo. Caminhos são relativos à raiz do workspace e **não podem** sair dele, nem tocar em `.git`, `.env`, `venv`, `node_modules`.

## Verificações (`verify`)

`file_exists` (`path`) · `contains` (`path`, `text`) · `not_contains` (`path`, `text`) · `python_syntax` (`path`).
Todo `.py` tocado por um passo já tem a sintaxe checada automaticamente.

## Comportamento

- **Falhou?** A tarefa fica `failed`, com o motivo (passo X/N + mensagem) e o botão **Reiniciar**.
- **Reiniciar é seguro (idempotente):** passos já aplicados são detectados e pulados; segue de onde parou.
- **Ordem:** tarefas rodam por id. Se uma falhar, as seguintes ficam `pending` (não empilha erro).
- Edição em `.py` é validada **antes** de gravar (sintaxe, função duplicada). Se rejeitar, nada é salvo.
- Final de linha (CRLF/LF) do arquivo é preservado.

## Prompt modelo para me pedir tarefas

```
Gere microtasks no formato do MICROTASKS.md (JSON puro, sem comentários).
Objetivo: <o que você quer>
Regras: uma tarefa = uma mudança pequena e verificável; a 1ª tarefa faz create_branch;
inclua verify em todas; para replace_text use APENAS texto que está no código que enviei abaixo
(copiado exatamente); se faltar código para eu ter certeza, me peça o arquivo em vez de inventar.
Código relevante:
<cole aqui os arquivos/trechos>
```

> `create_file`, `append`, `write_markdown` e `create_pdf` não dependem de código existente, então eu consigo gerá-los sem ver seu repositório.
> `replace_text` exige que eu veja o trecho exato (por isso o prompt pede o código).


## Modo livre (sem `steps`): contexto, verificação e revisão

- **Contexto pronto:** antes de chamar o modelo o sistema monta um dossiê com o `git diff`, os arquivos de `files` (arquivos grandes entram com cabeçalho, esboço e trechos alterados) e as constantes/classes usadas e definidas em outros `.py`. O que foi entregue aparece nos pensamentos da resposta.
- **Verificação:** `verify` também vale no modo livre. Novo tipo `literals_grounded`:
  `{ "type": "literals_grounded", "path": "DOC.txt", "sources": ["app/views.py"], "allow": [] }` confere, por código, se valores entre aspas/crases, headers `X-...` e códigos HTTP do documento existem nas fontes. Documentos `.md/.txt` criados pelo agente são conferidos automaticamente contra os demais arquivos de `files`.
- **Autocorreção:** se sintaxe, `verify` ou a checagem de documentos falhar, o erro volta ao modelo (até `MAX_VERIFY_RETRIES`, padrão 2) antes de a tarefa ficar `failed`.
- **Revisão:** com `REVIEW_FREE_TASKS = True` a tarefa termina em `review`: use **Ver alterações**, depois **Aprovar** ou **Reprovar** (o comentário é anexado à descrição e a tarefa volta a `pending`).
- **Quando usar cada modo:** edição de código com trecho conhecido e documentação que vai para outra pessoa → modo determinístico (`write_markdown` com o texto final). Modo livre → tarefas mecânicas locais, sempre com `verify`.
