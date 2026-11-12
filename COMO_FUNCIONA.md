# Como o RAG de código funciona

Este documento responde, com base no código atual de `backend/rag/`:

0. [O que exatamente é transformado em embedding](#0-o-que-exatamente-é-transformado-em-embedding)
1. [Como a ingestão ocorre](#1-como-a-ingestão-ocorre)
2. [Como os chunks são divididos](#2-como-os-chunks-são-divididos)
3. [Como o resumo é montado sem IA](#3-como-o-resumo-é-montado-sem-ia)
4. [Como é decidido qual fonte a IA consulta](#4-como-é-decidido-qual-fonte-a-ia-consulta)
5. [Como o índice se mantém atualizado](#5-como-o-índice-se-mantém-atualizado)

**Vocabulário.** *Fonte* é uma unidade indexada: uma pasta do computador (tipo `workspace`) ou um zip enviado (tipo `zip`). *Chunk* é um trecho de código com identidade (uma função, uma classe, um cabeçalho...). *Projeto ativo* é a pasta de trabalho selecionada no chat (aba **Projeto**).

---

## 0. O que exatamente é transformado em embedding

**Resposta curta:** sim, é texto. O que o sistema lê é o **código-fonte dos seus arquivos como texto puro** (`.py`, `.js`, `.md`...). Não é PDF: não há leitura de página, OCR nem extração de layout (PDF e DOCX nem são indexados, pois a extensão não está na lista). O programa **corta esse texto** em pedaços que respeitam a estrutura do código (uma função, uma classe...), e cada pedaço, junto com uma etiqueta, é enviado como **uma string de texto** a um modelo de embedding, que devolve **uma lista de números**. Essa lista, junto com o texto original, é gravada no banco.

### O caminho de um trecho, do arquivo ao banco

```
app/views.py  (texto UTF-8)
      │  o chunker lê o texto e descobre, pela estrutura do Python (AST),
      │  em que linha cada função/classe começa e termina
      ▼
lista de trechos  (cada um é uma string: "class OSMobileSignupSyncView: ...")
      │  para cada trecho monta:  etiqueta + código  →  UM texto
      ▼
Ollama  POST /api/embed  { model: "nomic-embed-text", input: [texto1, texto2, ...] }
      │  o modelo devolve um vetor por texto: 768 números
      ▼
PostgreSQL (tabela rag.chunks): código original + etiqueta + resumo + o vetor
```

Ou seja: **sim, o código corta as classes e funções, o resultado de cada corte é um texto, e é esse texto que vai para o modelo de embedding.** A "ingestão" é exatamente isso, repetido para cada trecho de cada arquivo novo ou alterado.

### Exemplo real

Suponha este `app/views.py`:

```python
import json
from django.http import JsonResponse

ALLOWED_SIGNUP_TIPOS = {"cliente", "parceiro"}


class OSMobileSignupSyncView:
    """Recebe o cadastro vindo do app mobile."""

    def post(self, request):
        if request.tipo not in ALLOWED_SIGNUP_TIPOS:
            return JsonResponse({"detail": "tipo inválido"}, status=400)
        return JsonResponse({"ok": True}, status=201)
```

**Passo 1 - o chunker encontra dois trechos** (as linhas dizem onde cada um estava no arquivo):

| Trecho | `kind` | Linhas |
|---|---|---|
| imports + a constante `ALLOWED_SIGNUP_TIPOS` | `header` | 1-6 |
| a classe `OSMobileSignupSyncView` (pequena, então fica inteira num trecho) | `class` | 7-13 |

**Passo 2 - cada trecho vira UM texto (etiqueta + código).** Este é, literalmente, o texto enviado ao modelo para o segundo trecho:

```
[arquivo] app/views.py
[tipo] class
[símbolo] OSMobileSignupSyncView (linhas 7-13)
[resumo] Recebe o cadastro vindo do app mobile.

class OSMobileSignupSyncView:
    """Recebe o cadastro vindo do app mobile."""

    def post(self, request):
        if request.tipo not in ALLOWED_SIGNUP_TIPOS:
            return JsonResponse({"detail": "tipo inválido"}, status=400)
        return JsonResponse({"ok": True}, status=201)
```

A etiqueta entra de propósito: assim o vetor "sabe" em que arquivo e classe o código vive, e não só o que ele faz.

**Passo 3 - o modelo devolve um vetor.** Para esse texto, algo como `[0.0132, -0.0871, 0.0415, ... ]`, no total **768 números** (valores ilustrativos; a quantidade vem de `RAG_EMBED_DIM`).

**Passo 4 - vira uma linha no banco** (`rag.chunks`):

| Coluna | Conteúdo neste exemplo |
|---|---|
| `path` | `app/views.py` |
| `kind` / `qualname` | `class` / `OSMobileSignupSyncView` |
| `start_line` / `end_line` | 7 / 13 |
| `content` | o código da classe (**sem** a etiqueta; é o que será devolvido ao agente) |
| `summary` | `Recebe o cadastro vindo do app mobile.` |
| `embedding` | os 768 números |

### O que é um embedding (sem matemática)

É uma "impressão digital de significado": textos que **falam da mesma coisa** produzem listas de números **parecidas**, mesmo usando palavras diferentes. É por isso que a pergunta *"onde validamos o tipo de cadastro?"* encontra a classe acima, mesmo sem repetir nenhuma palavra do código. O vetor serve **só para achar**; ele não guarda o texto de volta, por isso o texto original é gravado ao lado.

### Na hora da pergunta (o caminho inverso)

1. A sua pergunta (também uma string) vai ao **mesmo** modelo e vira um vetor.
2. O Postgres (pgvector) compara esse vetor com os dos chunks e traz os mais próximos.
3. Em paralelo, a busca por texto e por nome de símbolo traz outros candidatos (ver seção 4).
4. Os trechos vencedores são devolvidos **com o texto original** (`content`), e é esse texto que a IA lê para responder.

### O que NÃO acontece

- Nenhum LLM lê o código durante a ingestão (só se você definir `RAG_SUMMARY_MODEL`; ver seção 3). O modelo de embedding apenas converte texto em números.
- O arquivo inteiro **não** vira um vetor só: cada função/classe tem o seu, e é por isso que dá para achar trechos pequenos em repositórios enormes.
- Nada é "treinado": você não altera nenhum modelo, só guarda vetores num banco.

---

## 1. Como a ingestão ocorre

A ingestão é **sempre explícita**: nada é indexado sozinho. Há duas portas de entrada, que usam o mesmo pipeline:

| Entrada | Como | Observação |
|---|---|---|
| Pasta do computador | `/static/rag.html` → "Indexar uma pasta", ou `POST /api/rag/sources/workspace` | Guarda o caminho; permite reindexar e atualizar sozinho (seção 5). |
| Zip | `/static/rag.html` → "Enviar um zip", ou `POST /api/rag/sources/zip` | Vira uma fonte com o nome que você der. Reenviar com o mesmo nome atualiza só o que mudou. |

### Passo a passo (`pipeline.py`)

1. **Varredura** (`scanner.py`). Em repositório git usa `git ls-files` (respeita o `.gitignore`); senão percorre as pastas. Ignora `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, lockfiles, `*.min.js`, `.env*`, binários, arquivos vazios e arquivos acima de 400 KB (JSON acima de 100 KB). Só entram extensões de texto conhecidas (`.py .js .ts .tsx .html .css .md .txt .sql .yml .toml .sh .bat .json`...).
2. **Comparação por hash.** Cada arquivo recebe um `sha1` do conteúdo. Só arquivos **novos ou alterados** seguem adiante; arquivos que sumiram são removidos do índice.
3. **Chunking** do arquivo (seção 2).
4. **Resumo** de cada chunk (seção 3). O resumo é guardado pelo hash do código: se o código não mudou, o resumo é reaproveitado (inclusive entre fontes).
5. **Embedding.** O texto vetorizado é a **tag + o código** (limite de 6000 caracteres), em lotes de 16, com o modelo de embedding do Ollama (`RAG_EMBED_MODEL`, padrão `nomic-embed-text`, 768 dimensões).
6. **Gravação** no PostgreSQL (schema `rag`, extensão pgvector). Cada arquivo é gravado numa transação: apaga os chunks antigos do arquivo e insere os novos.

### Execução e acompanhamento

- A ingestão roda **em segundo plano**; a API responde na hora com `job_id`. O progresso (arquivos feitos, chunks, arquivo atual) fica no banco e aparece em `/static/rag.html`.
- Estados do job: `queued`, `running`, `done`, `failed`, `cancelled`, `interrupted`. Se o servidor reiniciar durante uma ingestão, o job vira `interrupted`; basta reindexar (só o que faltou é refeito).
- É possível cancelar; o cancelamento é checado entre arquivos.
- Zips são extraídos numa pasta temporária (`.rag_work/`) com proteção contra *zip-slip* e *zip bomb*, e a pasta é apagada no fim. Se o zip tem uma única pasta na raiz (padrão do GitHub), ela é "desembrulhada".

---

## 2. Como os chunks são divididos

A regra geral: **um chunk = uma classe ou uma função/método inteiro**, nunca um corte arbitrário no meio de uma função. Quando não há estrutura para aproveitar, usa-se janelas de linhas.

### Python (por AST, `chunker.py`)

| Parte do arquivo | Chunk gerado (`kind`) |
|---|---|
| Linhas antes da primeira função/classe (imports, constantes, configuração; até 200 linhas) | `header` |
| Constantes de módulo definidas **depois** da primeira função | `constants` |
| Cada função de nível superior (com decoradores) | `function` |
| Classe com até 80 linhas | `class` (a classe inteira, em um chunk) |
| Classe com mais de 80 linhas | `class_skeleton` (linha da classe, docstring, atributos e as assinaturas dos métodos com `...`) **mais** um chunk `method` por método |
| Classes aninhadas | tratadas do mesmo jeito, com o nome qualificado (`Externa.Interna`) |

O chunk de **cabeçalho** existe de propósito: constantes soltas no topo do arquivo (ex.: `ALLOWED_SIGNUP_TIPOS = {...}`) não pertencem a nenhuma função e, sem ele, nunca seriam encontradas.

Se o arquivo tem erro de sintaxe, ele cai no modo de janelas.

### Outras linguagens

| Tipo | Regra |
|---|---|
| JavaScript / TypeScript | Cada declaração no início da linha (`function`, `class`, `const x = (...) =>`, `const x = function`) vai até a próxima declaração. O que vem antes da primeira é o `header`; comentários logo acima da primeira declaração ficam com ela. |
| Markdown | Uma seção por título (`#`, `##`, `###`). O texto antes do primeiro título é a introdução. |
| HTML, CSS, JSON, YAML, SQL, shell... | Janelas de 80 linhas com 10 de sobreposição (`block`). |

### Chunks muito grandes

Qualquer chunk com mais de 200 linhas (`RAG_MAX_CHUNK_LINES`) é dividido em **partes** com 10 linhas de sobreposição (`parte 1/3`, `2/3`...). Todas as partes mantêm o mesmo nome de símbolo.

### A tag

Cada chunk carrega uma tag que diz onde ele vive e o que ele faz. Ela entra no texto que é vetorizado, então a busca também "entende" o arquivo e a classe:

```
[arquivo] app/views.py
[tipo] method
[classe] OSMobileSignupSyncView
[símbolo] OSMobileSignupSyncView.post (linhas 12-40)
[resumo] Método OSMobileSignupSyncView.post(request). Usa: get, JsonResponse, loads.
```

---

## 3. Como o resumo é montado sem IA

Por padrão **não há LLM no resumo**: `RAG_SUMMARY_MODEL` vem vazio e o sistema usa o resumo heurístico (`HeuristicSummarizer`, em `providers.py`). Ele só lê a estrutura do código:

| Tipo de chunk | Como o resumo é montado | Exemplo |
|---|---|---|
| `header` / `constants` | Nomes de constantes em MAIÚSCULAS (3+ caracteres) e até 6 módulos importados | `Cabeçalho de app/views.py: define ALLOWED_SIGNUP_TIPOS; importa json, django.http.` |
| Função, método ou classe **com docstring** | Primeira frase da docstring (até 160 caracteres) | `Recebe o cadastro vindo do app mobile.` |
| Classe sem docstring | Nome e até 6 métodos | `Classe Parser com métodos read, validate, dump.` |
| Função/método sem docstring | Nome, parâmetros (sem `self`/`cls`) e até 6 nomes de funções que ele chama | `Função enviar_item(item). Usa: append, notify.` (para método: `Método Fila.enviar(item). ...`) |
| Qualquer outro (JS, markdown, CSS...) | Tipo, nome e a primeira linha não vazia (até 100 caracteres) | `section Uso: # Uso` |

**Se você quiser resumos escritos por IA**, defina `RAG_SUMMARY_MODEL` (ex.: um modelo pequeno do Ollama). O prompt pede **uma frase curta** (até 25 palavras, em português), citando nomes reais e sem inventar. Se a chamada falhar, o sistema volta sozinho para o resumo heurístico, então a ingestão nunca trava. Isso é mais lento: é uma chamada por chunk novo ou alterado.

O resumo fica guardado pelo hash do código. Mudar de modo não reescreve os resumos que já existem; eles só mudam quando o código do chunk muda (ou se a fonte for apagada e indexada de novo).

---

## 4. Como é decidido qual fonte a IA consulta

Esta é a parte que mais gera dúvida, então as regras exatas são estas.

### Regra padrão

O agente consulta a **fonte do projeto ativo**, que é a fonte do tipo `workspace` cujo caminho é igual ao do projeto ativo no chat, **mais as fontes vinculadas** a esse projeto (veja abaixo).

Consequências importantes:

- **Um zip nunca é consultado por padrão**, porque ele não tem caminho no computador. Para o agente chegar nele é preciso vincular ou pedir pelo nome.
- Outro workspace (Y) só é consultado por padrão se Y for o projeto ativo.
- Se o projeto ativo não estiver indexado, o padrão fica vazio (e o agente é avisado de quais fontes existem).

### Como chegar no zip ou no workspace Y estando no X

| Quero... | O que fazer | Quão garantido é |
|---|---|---|
| Perguntar sobre o zip/Y **só desta vez** | Diga o nome na pergunta: *"no zip `meu-zip`, onde fica a validação de CPF?"* | O agente vê a lista **"Fontes indexadas"** no contexto e chama a busca com `source="meu-zip"`. É decisão do modelo guiada pela sua frase; se ele errar o nome, a resposta da ferramenta lista os nomes corretos. |
| Que o zip/Y entre **sempre** nas buscas do projeto X | No chat, botão **Fontes** (ao lado de Auto/Heavy/Enhance) → marque a fonte. Também dá em `/static/rag.html` → **Contexto do projeto ativo** | **Determinístico.** Passa a fazer parte do padrão do projeto X e fica salvo. |
| Buscar em **tudo** | Peça "busque em todas as fontes" (o agente usa `source="all"`) | Decisão do modelo guiada pela sua frase. |
| Trocar de projeto | Selecione Y na aba **Projeto** do chat | Determinístico: Y vira o padrão (se estiver indexado). |
| Só pesquisar, sem agente | Caixa "Buscar no índice" em `/static/rag.html` | Busca em **todas** as fontes. |

### Onde o agente usa o RAG

- **Ferramenta `search_codebase`**, disponível ao chat de código, ao coletor de contexto e ao agente Generate. É o modelo quem decide **se** chama e **com qual** `source`. Parâmetros: `query`, `source` (vazio, `"all"` ou nome da fonte), `path_prefix`, `limit`.
- **Dossiê automático das tarefas em modo livre.** Antes de rodar a tarefa o sistema consulta o RAG com o título e a descrição dela, **no escopo padrão** do projeto, e anexa os trechos ao prompt. Quando existe alguma fonte indexada, esse dossiê inclui também a lista delas, no formato:

  ```
  Fontes indexadas (para consultar outra, use search_codebase com source="nome"):
  - meu-projeto (workspace, 120 arquivos): consultada por padrão
  - meu-zip (zip, 40 arquivos): para consultar use source="meu-zip"
  ```

### Como a busca em si funciona

Dentro das fontes escolhidas, a busca é **híbrida** e combina três rankings por *Reciprocal Rank Fusion*:

1. **vetor**: similaridade semântica (acha por assunto: "onde validamos o cadastro?");
2. **texto**: palavras exatas no código/resumo (acha `ALLOWED_SIGNUP_TIPOS`);
3. **símbolo**: nome da função/classe ou do arquivo.

Cada resultado traz arquivo, linhas, tipo, resumo e o trecho de código.

### Limites atuais

- A escolha entre fontes não vinculadas depende do modelo entender seu pedido. Se precisar de garantia, **vincule** a fonte.
- O seletor **Fontes** do chat vale para o **projeto**, não só para a conversa: a escolha vale em todas as conversas daquele projeto. O botão só aparece quando há pelo menos uma fonte indexada.

---

## 5. Como o índice se mantém atualizado

- **Fontes do tipo workspace:** sempre que o agente usa o RAG (dossiê ou `search_codebase`), o sistema faz antes uma **atualização incremental e síncrona** do projeto ativo: reprocessa só os arquivos novos, alterados ou removidos. Para não pesar, há no máximo **uma varredura por minuto** por projeto, ela não sobrepõe uma ingestão em andamento e tem limite de 25 segundos (o que sobrar continua na consulta seguinte). Edições feitas pelo agente, por tarefas de passos ou por você no editor entram no índice na próxima consulta.
- **Fontes do tipo zip:** não há pasta para observar. Para atualizar, envie o zip de novo com o **mesmo nome**; só o que mudou é reprocessado.
- **Atualizar na hora:** botão **Reindexar** em `/static/rag.html`.
- Vínculos e fontes apagadas: apagar uma fonte remove também os vínculos dela.

---

## Variáveis de ambiente e solução de problemas

As variáveis (`RAG_EMBED_MODEL`, `RAG_EMBED_DIM`, `RAG_SUMMARY_MODEL`...) estão no `README.md` desta pasta.

| Sintoma | Causa provável |
|---|---|
| "RAG indisponível: não foi possível ativar a extensão pgvector" | O Postgres não tem o pgvector. Use a imagem `pgvector/pgvector:pg16`. |
| "Dimensão do embedding difere de RAG_EMBED_DIM" | O modelo de embedding não tem a dimensão configurada. Ajuste `RAG_EMBED_DIM`; ao trocar de modelo, recrie o schema (`DROP SCHEMA rag CASCADE;`). |
| Zip nunca aparece nas respostas | Zip não é padrão: vincule ao projeto ou peça pelo nome (seção 4). |
| Resposta com trecho desatualizado | Aguarde a próxima consulta (atualização automática) ou use **Reindexar**. |
