# 🧠 Assistente IA Local (FastAPI + LangGraph)

Um ecossistema de assistente virtual 100% local e autônomo, desenhado para rodar em hardware dedicado (GPU/VRAM + RAM Offload). A arquitetura orquestra múltiplos Modelos de Linguagem (LLMs) através de um roteador inteligente, delegando tarefas simples para modelos rápidos na GPU e tarefas complexas para modelos gigantes processados em background.

---

## 🎯 Objetivo da Arquitetura

O princípio central do projeto é **nunca usar um modelo gigante para tudo**. 
A persistência do sistema é garantida por um Banco de Dados relacional (PostgreSQL/SQLite), atuando como a única fonte da verdade. Integrações externas (como exportação para Notion) são tratadas apenas como *sinks* (destinos de visualização) não críticos.

### Princípios Base
1. **O Modelo Pequeno Decide:** O roteador classifica rápido e gasta pouca memória.
2. **O Modelo Intermediário Resolve:** A maior parte do trabalho acontece em tempo real na GPU.
3. **O Modelo Gigante é Assíncrono:** Tarefas densas rodam isoladas, liberam recursos ao terminar e não travam a API.
4. **O Banco é a Verdade:** Se a API cair ou o Notion ficar offline, nenhum histórico ou processamento é perdido.

---

## 🤖 Alocação de Hardware e Modelos

O sistema utiliza o LangGraph para rotear as requisições para o nó/modelo mais adequado:

| Nó / Função | Modelo Configurado | Hardware | Objetivo Principal |
|---|---|---|---|
| **Roteador** | `qwen3:4b` | CPU/RAM | Analisar o prompt estruturado (JSON) e decidir o fluxo. |
| **Generalista** | `gpt-oss:20b` | GPU / VRAM | Bate-papo, tarefas em tempo real e RAG. |
| **Coder** | `gpt-oss:20b` | GPU / VRAM | Geração e explicação de código (Python, SQL, etc). |
| **Notes (Draft & Final)** | `qwen3:30b-a3b` | GPU / VRAM | Criação de documentações técnicas complexas (uso de tags `<think>`). |
| **Heavy Task** | `DeepSeek-R1:70b` | VRAM + RAM Offload | Tarefas assíncronas longas, arquitetura e análise de repositórios. |

---

## 🔄 Fluxos de Execução

### 1. Fluxo Síncrono (Normal)
Usado para perguntas, código e geração de notas. A requisição HTTP aguarda a resposta do modelo.
`Usuário ➔ Roteador (4B) ➔ Nó Específico (20B/30B) ➔ Resposta Imediata`

### 2. Fluxo Assíncrono (Tarefas Pesadas)
Usado quando o prompt exige processamento massivo (ex: `@heavy`). A API não bloqueia.
1. Usuário envia o prompt.
2. API salva no Banco de Dados (`status = pending`).
3. API devolve um `task_id` imediatamente.
4. **Celery Worker** assume a tarefa em background.
5. Modelos leves são descarregados da VRAM (`keep_alive=0`).
6. O modelo Gigante (70B) é carregado e processa a requisição.
7. O resultado é salvo no Banco (`status = completed`).
8. Notificações e exportações (ex: Notion) são disparadas.

---

## 🏗️ Estrutura Lógica do Sistema

```text
                       FRONTEND (Streamlit)
                               │
                               ▼
                            FastAPI
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
          PostgreSQL                       LangGraph
         (Histórico)                       (Roteador)
              │                    ┌────────────┴────────────┐
              │                    ▼                         ▼
              │            Nós Síncronos               Heavy Node
              │         (General, Code, Note)         /tasks/heavy
              │                    │                         │
              │                    ▼                         ▼
              │             Retorna ao Front               Celery
              │                                              │
              │                                              ▼
              │                                      Background Worker
              │                                              │
              │                                              ▼
              │                                        DeepSeek-R1 (70B)
              └────────────────┬─────────────────────────────┘
                               ▼
                  database.crud.save_result()
                               │
                      ┌────────┴────────┐
                      ▼                 ▼
                 Notion Adapter     Notificador (OS/Telegram)
                  (Opcional)
