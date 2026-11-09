# backend/rag — RAG de código (módulo isolado)

Indexa repositórios inteiros em PostgreSQL + pgvector e devolve ao agente só os trechos relevantes.

## Regras de isolamento
- `backend/rag` **não importa** `backend.graph`, `backend.api` nem `backend.database`.
- O resto do sistema usa apenas `backend.rag.get_service()` (ou o router `/api/rag`).
- `backend/graph/rag_bridge.py` é o único arquivo do agente que conhece o RAG; se o RAG falhar, o agente segue sem ele.
- Store, embedder e resumidor são interfaces trocáveis (`store_base.py`, `providers.py`).

## Como funciona
1. **Scanner** (`scanner.py`): lista arquivos (respeita `.gitignore`; ignora binários, `.env`, `node_modules`...).
2. **Chunker** (`chunker.py`): um chunk por classe, função ou método (Python por AST; JS/TS por declarações; Markdown por título; resto por janelas). Cada arquivo também gera um chunk de **cabeçalho** (imports e constantes do topo).
3. **Resumo** (`providers.py`): uma frase por chunk, cacheada pelo hash do código. Sem `RAG_SUMMARY_MODEL` usa resumo heurístico (docstring, assinatura, nomes), sem LLM.
4. **Tag**: cada chunk carrega arquivo, classe pai, símbolo, linhas e resumo; a tag entra no texto que é vetorizado.
5. **Embedding + gravação**: só arquivos novos/alterados (hash). Schema `rag` no Postgres.
6. **Busca híbrida**: vetor + texto (tsvector) + símbolo, combinados por Reciprocal Rank Fusion.

## Entradas de ingestão (sempre explícitas)
- Pasta do computador: `POST /api/rag/sources/workspace {"path": "...", "name": "..."}`
- Zip: `POST /api/rag/sources/zip` (multipart `file`, `name`). Re-enviar com o mesmo nome atualiza só o que mudou.
- Página de gestão: `/static/rag.html`.

## Pré-requisitos
1. **pgvector** no Postgres. Com Docker, troque a imagem do Postgres por `pgvector/pgvector:pg16` (mesma versão major, mesmo volume). O usuário do banco precisa poder `CREATE EXTENSION vector`.
2. **Modelo de embedding** no Ollama: `ollama pull nomic-embed-text`.

## Variáveis de ambiente (todas opcionais)
| Variável | Padrão | Para quê |
|---|---|---|
| `RAG_DATABASE_URL` | `DATABASE_URL` | banco do RAG |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | servidor Ollama |
| `RAG_EMBED_MODEL` | `nomic-embed-text` | modelo de embedding |
| `RAG_EMBED_DIM` | `768` | dimensão do modelo (tem de bater) |
| `RAG_SUMMARY_MODEL` | vazio | modelo que escreve os resumos; vazio = heurístico |
| `RAG_SUMMARY_THINK` | vazio | esforço de raciocínio do modelo de resumo (`low`, `medium`, `high`, `true`, `off`); vazio = automático (`low` no gpt-oss) |
| `RAG_SUMMARY_TIMEOUT` | `180` | segundos por resumo |
| `RAG_SUMMARY_CONCURRENCY` | `2` | resumos em paralelo (ajuste junto com `OLLAMA_NUM_PARALLEL`) |
| `RAG_MAX_FILE_BYTES` | `400000` | arquivos maiores são ignorados |
| `RAG_MAX_CHUNK_LINES` | `200` | chunks maiores são divididos em partes |
| `RAG_ZIP_MAX_BYTES` / `RAG_ZIP_MAX_FILES` | 500 MB / 20000 | limites do zip |
| `RAG_WORK_DIR` | `.rag_work` | pasta temporária de extração |

Trocar de modelo de embedding exige recriar o schema: `DROP SCHEMA rag CASCADE;`.

## Testes
```
python -m unittest backend.rag.tests.test_rag_core backend.rag.tests.test_rag_service -v
python -m backend.rag.smoke_test            # com Postgres + Ollama reais
```
