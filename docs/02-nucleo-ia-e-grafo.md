# Núcleo de Execução e Inteligência Artificial

## Visão Geral

Este documento descreve os componentes principais da lógica de backend, incluindo o fluxo de interação com a IA, a construção do grafo de execução e os modelos de dados utilizados na aplicação.

## Componentes Principais da API

### Controladores

#### `ai_controller.py`

O controlador de IA é responsável por gerenciar as interações com o modelo de linguagem e as tarefas de processamento. Contém:

1. **Rotas da API**
   - `/`: Endpoint para chat com a IA
   - `/messages/{thread_id}`: Endpoint para obter histórico do chat
   - `/batch/`: Endpoint para envio em lote de tarefas
   - `/{thread_id}/tasks`: Endpoint para obter tarefas pendentes

2. **Funções Principais**
   - `chat_with_ai()`: Processa mensagens de usuário e retorna respostas da IA
   - `get_chat_history()`: Retorna o histórico completo do chat
   - `send_tasks_background()`: Envia tarefas para execução em segundo plano
   - `get_pending_tasks()`: Retorna tarefas pendentes para um thread específico

3. **Dependências**
   - `get_compiled_graph()`: Fornece o grafo compilado da aplicação
   - `CompiledGraphDep`: Dependência injetada para acesso ao grafo

### Modelos de Dados

#### `models.py`

Os modelos definem a estrutura das tabelas no banco de dados:

1. **AiChatModel**
   - Tabela `chats`
   - Campos: id, thread_id, title, created_at, updated_at
   - Usado para armazenar conversas da IA

2. **TaskModel**
   - Tabela `agent_tasks`
   - Campos: id, thread_id, title, description, files, reason, priority, status
   - Usado para gerenciar tarefas pendentes e em execução

## Construção do Grafo de Execução

### `builder.py`

O arquivo `builder.py` é responsável por construir o grafo de execução completo da aplicação:

1. **Nós do Grafo**
   - `router_node`: Roteia as mensagens para os nós apropriados
   - `standard_node_20b`: Processamento padrão com modelo 20B
   - `code_node`: Geração de código
   - `generate_node`: Execução de tarefas de implementação
   - `generate_dispatch_node`: Disparo de tarefas em background
   - `note_draft_node`: Criação de rascunhos de notas
   - `note_refine_node`: Refinamento de notas
   - `context_gatherer_node`: Coleta de contexto do sistema
   - `heavy_analyzer_node`: Análise profunda com modelo pesado
   - `enhancer_node`: Aprimoramento de prompts

2. **Condições de Transição**
   - `check_context_limit`: Verifica limite de mensagens e decide se deve resumir
   - `route_decision`: Determina o próximo nó baseado na decisão do roteador
   - `after_enhancer_route`: Roteamento após o nó de aprimoramento
   - `tools_condition`: Condição para uso de ferramentas

3. **Ferramentas Disponíveis**
   - `list_directory_files`: Lista arquivos em diretórios
   - `read_file_content`: Lê conteúdo de arquivos
   - `generate_repo_map`: Gera mapa do repositório
   - `create_git_branch`: Cria novas branches git
   - `create_new_file`: Cria novos arquivos
   - `edit_existing_file`: Edita arquivos existentes
   - `append_to_file`: Adiciona conteúdo a arquivos
   - `git_commit_changes`: Faz commit das mudanças

## Fluxo de Interação com a IA

### Processo de Chat

1. **Recebimento da Mensagem**
   - Mensagem do usuário é recebida via endpoint `/`
   - A mensagem é processada pelo nó `router_node`

2. **Roteamento**
   - O nó `router_node` determina o caminho apropriado com base no conteúdo
   - Pode ser roteado para: `standard_node_20b`, `code_node`, `generate_node`, etc.

3. **Processamento**
   - A mensagem é processada pelo nó selecionado
   - Pode utilizar ferramentas do sistema para coletar contexto

4. **Resposta**
   - Resposta é retornada ao usuário
   - Histórico é mantido no grafo de estado

### Processo de Tarefas em Background

1. **Envio em Lote**
   - Endpoint `/batch/` permite envio de múltiplas tarefas
   - Utiliza Celery para execução assíncrona

2. **Disparo de Tarefas**
   - `send_tasks_background()` envia tarefas para o Celery
   - Cada tarefa é registrada no banco de dados como pendente

3. **Execução**
   - Tarefas são executadas em segundo plano
   - Resultados são armazenados no banco de dados

## Modelos de Linguagem e Configurações

### Configurações de LLM

#### `config.py`

1. **Modelos Disponíveis**
   - `standard_llm`: Modelo 20B para processamento padrão
   - `code_llm`: Modelo especializado em código
   - `generate_llm`: Modelo Qwen3-Coder para geração de código
   - `note_llm_draft`: Modelo para rascunhos de notas
   - `note_llm_final`: Modelo para refinamento de notas
   - `context_gatherer_llm`: Modelo para coleta de contexto
   - `heavy_llm`: Modelo DeepSeek R1 para análise profunda

2. **Configurações**
   - Temperatura variável para diferentes tipos de processamento
   - Tamanho máximo de tokens configurado para cada modelo
   - Contexto de contexto configurado para cada modelo

3. **Ferramentas Bindadas**
   - `code_llm_with_tools`: LLM com ferramentas para código
   - `note_llm_draft_with_tools`: LLM com ferramentas para notas
   - `context_gatherer_llm_with_tools`: LLM com ferramentas para coleta de contexto
   - `generate_llm_with_tools`: LLM com ferramentas para geração

## Fluxo de Execução Completo

### Para uma Tarefa de Geração

1. **Recebimento**
   - Mensagem contendo instrução de geração é recebida
   - Roteador identifica como tarefa de geração

2. **Processamento**
   - Nó `generate_node` é acionado
   - Contexto do workspace é coletado
   - Prompt é montado com informações do banco de dados

3. **Execução**
   - Modelo Qwen3-Coder é invocado com ferramentas
   - Ferramentas são usadas para leitura/escrita de arquivos
   - Código é gerado e implementado

4. **Finalização**
   - Tarefa é registrada no banco de dados
   - Resultados são retornados ao usuário

### Para uma Análise Profunda

1. **Recebimento**
   - Mensagem com solicitação de análise é recebida
   - Roteador identifica como tarefa pesada

2. **Coleta de Contexto**
   - Nó `context_gatherer_node` coleta informações do sistema
   - Ferramentas são usadas para leitura de arquivos e diretórios

3. **Análise**
   - Nó `heavy_analyzer_node` processa com modelo DeepSeek R1
   - Análise é gerada com base no contexto coletado

4. **Geração de Tarefas**
   - Novas tarefas podem ser criadas e registradas no banco de dados
   - Resultados são retornados ao usuário

## Estrutura de Estado

### `State` (em `config.py`)

O estado do grafo é composto por:

1. **Mensagens**
   - Lista de mensagens de conversa
   - Inclui humanas, assistentes e ferramentas

2. **Contexto**
   - thread_id: Identificador único da conversa
   - summary: Resumo da conversa
   - actual_route: Rota atual do processamento
   - heavy_context: Contexto coletado para análise pesada

3. **Flags de Controle**
   - enhance_before_heavy: Indica se precisa aprimorar antes de análise pesada
   - active_node: Nó atualmente ativo
   - enhanced_prompt: Prompt aprimorado

4. **Tarefas**
   - active_generate_task: Tarefa de geração atual
   - generate_start_idx: Índice inicial para geração