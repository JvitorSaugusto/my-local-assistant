# Ciclo de Vida e Servidor

## Visão Geral

Este documento descreve os processos de inicialização, conexão com o banco de dados e configuração do servidor estático da aplicação. O ciclo de vida é gerenciado pelo FastAPI através do contexto `lifespan`, que permite executar ações antes e após o servidor estar pronto para receber requisições.

## Função `lifespan`

A função `lifespan` é responsável por gerenciar o ciclo de vida da aplicação FastAPI. Ela é executada automaticamente durante a inicialização e encerramento do servidor.

### Processos de Inicialização

1. **Conexão com o Banco de Dados**
   - Cria uma pool de conexões assíncronas com o PostgreSQL usando `AsyncConnectionPool`
   - Configura o `checkpointer` para persistência de estado do LangGraph
   - Estabelece a conexão com o banco de dados através da variável de ambiente `DATABASE_URL`

2. **Configuração do LangGraph**
   - Inicializa o grafo de execução chamando `build_graph().compile()`
   - Configura o `checkpointer` para persistência de estado
   - Armazena o grafo compilado no estado da aplicação (`app.state.compiled_graph`)

3. **Configuração do Servidor**
   - Monta os arquivos estáticos no caminho `/static`
   - Define as rotas da API

### Processos de Finalização

- O `yield` na função `lifespan` permite que o servidor continue operando
- Após o encerramento, o contexto é liberado automaticamente

## Função `serve_index`

A função `serve_index` é responsável por servir o conteúdo estático principal da aplicação.

### Fluxo de Requisição

1. **Localização do Arquivo**
   - O arquivo `index.html` é localizado no diretório `static/`
   - O caminho completo é montado a partir do diretório base

2. **Entrega do Conteúdo**
   - Retorna o conteúdo do arquivo `index.html` como resposta HTTP
   - Serve como ponto de entrada para a interface do usuário

## Conexão com o Banco de Dados

### Configuração

- A conexão é configurada através da variável de ambiente `DATABASE_URL`
- O modelo `AsyncPostgresSaver` é utilizado para persistência de estado do LangGraph
- A URL é modificada para remover o sufixo `+asyncpg` para compatibilidade com o LangGraph

### Recursos Alocados

- Pool de conexões assíncronas com autocommit ativado
- Persistência de estado do grafo de execução
- Conexão segura com o banco de dados PostgreSQL

## Servidor Estático

### Montagem de Arquivos Estáticos

- Os arquivos estáticos são montados no caminho `/static`
- Diretório configurado como `backend/static`
- Permite acesso aos recursos da interface do usuário (CSS, JS, imagens)

### Estrutura de Arquivos Estáticos

O diretório `backend/static` contém:
- `index.html`: Página principal da aplicação
- `script.js`: Código JavaScript da interface
- Outros recursos estáticos necessários para a UI

## Fluxo de Funcionamento

1. **Inicialização**
   - Servidor FastAPI inicia
   - Função `lifespan` é executada
   - Conexão com banco de dados estabelecida
   - Grafo LangGraph compilado e configurado
   - Arquivos estáticos montados

2. **Operação Normal**
   - Servidor aguarda requisições HTTP
   - Rotas da API são acessíveis
   - Conteúdo estático é servido corretamente

3. **Encerramento**
   - Servidor é desligado
   - Recursos são liberados automaticamente