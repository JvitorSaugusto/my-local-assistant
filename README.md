# My Local Assistant

Um assistente de IA local, orquestrado com **LangGraph**, que roteia cada mensagem para o modelo certo — do classificador mais leve ao especialista mais pesado — e é capaz de ler o próprio código-fonte de projetos para responder, documentar e analisar com precisão.

## 🎯 Objetivo

Este projeto nasceu como um estudo aprofundado de **LangGraph** e teve como meta replicar, com modelos locais e gratuitos, padrões de ferramentas presentes em assistentes de IA comerciais bastante conhecidos — sem depender de nenhuma API paga.

Dois exemplos concretos disso guiaram o design:

- **Leitura de diretórios e arquivos** — a mesma capacidade de "enxergar" um projeto inteiro que assistentes de código comerciais oferecem, implementada aqui como tools próprias (`list_directory_files`, `read_file_content`, `ingest_directory`).
- **Filas de tarefas em background** — a possibilidade de disparar uma solicitação, fechar o computador, e o processamento continuar rodando via **Celery**, sem depender de a aplicação ficar aberta.

## 🏗️ Arquitetura

O sistema é dividido em múltiplos modelos de tamanhos e propósitos diferentes, orquestrados por um grafo de estado (LangGraph). A ideia central é nunca usar um modelo maior do que o necessário para cada tarefa:

```
                         MENSAGEM DO USUÁRIO
                                 │
                                 ▼
                      check_context_limit
                        (conversa muito longa?)
                          │              │
                          ▼              ▼
                  summarize_node    router_node
                   (resume o          │
                    histórico)        │
                          └──────────►│
                                      ▼
                    tag explícita (@heavy / @enhance)?
                    ou classificação por LLM (NORMAL/CODE/NOTES)
                          │
        ┌─────────┬───────┼────────────┬──────────────┐
        ▼         ▼       ▼            ▼              ▼
  standard_node  code_node  note_draft_node   heavy_task_node_70b   enhancer_node
  (conversa   (código,   (notas técnicas,  (análise profunda,      (reescreve o
   geral)      com          com tools de      arquitetura, com       prompt antes
               tools de     leitura +         leitura completa       de rotear)
               leitura)     refino em          do projeto)
                            2 passadas)
```

Nós que possuem ferramentas (`code_node`, `note_draft_node`, `heavy_task_node_70b`) passam por um `ToolNode` compartilhado sempre que a LLM solicita uma chamada de ferramenta — o resultado retorna automaticamente para o **mesmo nó que fez a chamada**, através de uma "etiqueta" (`active_node`) gravada no estado do grafo.

## 🤖 Modelos e Funções

| Modelo | Papel | Ferramentas | Observações |
|---|---|---|---|
| `qwen3:4b` | Roteador — classifica a intenção da mensagem (`NORMAL`, `CODE`, `NOTES`) | — | Saída estruturada (schema Pydantic), temperatura 0, sem espaço para ambiguidade |
| `gpt-oss:20b` | Generalista (`standard_node_20b`) e Aprimorador de prompt (`enhancer_node`) | — | Modelo padrão para conversas do dia a dia e para reescrever prompts antes do roteamento |
| `gpt-oss:20b` | Código (`code_node`) | leitura cirúrgica (`list_directory_files`, `read_file_content`) | Foco em tarefas de programação; lê apenas os arquivos que precisa, um de cada vez |
| `qwen3:30b-a3b` | Notas técnicas (`note_draft_node` + `note_refine_node`) | leitura cirúrgica (só no rascunho) | Geração em duas passadas: um rascunho e uma etapa de aprofundamento/revisão |
| `DeepSeek-R1:70b` | Análise profunda e arquitetura (`heavy_task_node_70b`) | leitura completa (inclui `ingest_directory`) | Reservado para tarefas complexas — acionado explicitamente via tag `@heavy` |

## 🔀 Roteamento

Cada mensagem passa por duas camadas de decisão:

1. **Tags explícitas** — o usuário pode forçar o caminho digitando `@heavy` (força o modelo especialista) ou `@enhance` (reescreve o prompt antes de prosseguir). As duas podem ser combinadas (`@enhance` + `@heavy` na mesma mensagem), reescrevendo o prompt e enviando o resultado direto para o modelo pesado.
2. **Classificação por LLM** — na ausência de uma tag, um classificador leve (`qwen3:4b`) decide entre `NORMAL`, `CODE` e `NOTES`, considerando também um resumo das mensagens recentes da conversa para entender o contexto.

## 🛠️ Ferramentas (Tools)

| Ferramenta | O que faz | Quem usa |
|---|---|---|
| `list_directory_files` | Mapeia recursivamente os arquivos de código de uma pasta (ignorando `.git`, `node_modules`, ambientes virtuais, etc.) | Código, Notas, Análise Profunda |
| `read_file_content` | Lê o conteúdo de um único arquivo específico | Código, Notas, Análise Profunda |
| `ingest_directory` | Lê o conteúdo de todos os arquivos de um projeto de uma só vez | Somente Análise Profunda |

A divisão não é arbitrária: modelos menores (`gpt-oss:20b`, `qwen3:30b-a3b`) recebem apenas as ferramentas de leitura cirúrgica, reduzindo o risco de tentarem processar contexto demais de uma vez. `ingest_directory` fica reservada ao modelo de 70B, que tem janela de contexto e capacidade de síntese suficientes para lidar com um projeto inteiro em uma única chamada.

## 📝 Fluxo de Geração de Notas

A criação de notas técnicas acontece em duas etapas, em vez de uma única chamada:

1. **Rascunho** (`note_draft_node`) — gera uma primeira versão, usando as ferramentas de leitura quando a nota depende de um projeto ou arquivo real.
2. **Refino** (`note_refine_node`) — revisa o rascunho, aprofundando seções rasas e adicionando exemplos, sem ferramentas — o objetivo aqui é lapidar o texto, não buscar mais informação.

## ⏳ Processamento em Background (Filas)

Tarefas podem ser enviadas para uma fila **Celery** (com **Redis** como broker), permitindo que múltiplas solicitações sejam processadas de forma assíncrona — inclusive continuando após o encerramento da aplicação ou do computador que a originou. O resultado de cada execução é persistido no banco de dados, então nada se perde entre o disparo da tarefa e sua conclusão.

## 💾 Persistência

O histórico de cada conversa é mantido pelo próprio **checkpointer do LangGraph**, apoiado em **PostgreSQL** — cada conversa é identificada por um `thread_id`, e o estado completo (mensagens, resumo, rota ativa) é automaticamente salvo e recuperado a cada interação, sem necessidade de lógica manual de persistência de mensagens.

## 🖥️ Frontend

Interface web simples (HTML, CSS e JavaScript puros), gerada com auxílio de IA.

## 📁 Estrutura do Projeto

```
my-local-assistant/
│
├── reset.py
├── tasks.py                    # Definição das tarefas Celery
│
├── alembic/                    # Migrations do banco (metadados de chats)
│   ├── env.py
│   └── versions/
│
└── backend/
    ├── main.py                 # Ponto de entrada FastAPI + lifespan (checkpointer)
    │
    ├── adapters/                # Integrações externas
    │   ├── filesystem.py
    │   └── notion.py
    │
    ├── api/
    │   ├── schemas.py
    │   ├── services.py
    │   └── controllers/
    │       ├── ai_controller.py    # Rotas de chat, histórico e fila
    │       └── chat_controller.py
    │
    ├── database/
    │   ├── config.py
    │   └── models.py
    │
    ├── graph/                   # Núcleo do LangGraph
    │   ├── builder.py           # Montagem do grafo (nós e arestas)
    │   ├── config.py            # Modelos, State e bind de tools
    │   ├── nodes.py             # Lógica de cada nó
    │   ├── prompts.py           # System prompts de cada modelo
    │   ├── tools.py             # Ferramentas de leitura de arquivos
    │   └── utils.py             # Detecção de tags explícitas
    │
    └── static/                  # Frontend (HTML/CSS/JS)
```

## 🔮 Roadmap

- Ferramenta de web scraping, para consulta de documentações externas;
- Ferramenta de leitura de imagens;
- Geração de PDFs a partir de conteúdo estruturado.
