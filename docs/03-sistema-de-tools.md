# Sistema de Ferramentas

## Introdução

O sistema de ferramentas é uma componente fundamental do ecossistema que permite a interação segura com o ambiente de desenvolvimento através de operações de leitura e escrita em arquivos, manipulação de repositórios Git e gerenciamento de contexto. Este sistema fornece as capacidades básicas para que os agentes possam interagir com o código-fonte do projeto.

## Arquitetura das Tools Personalizadas

### Leituras e Manipulação de Arquivos

O sistema oferece ferramentas especializadas para leitura e manipulação de arquivos:

1. **`list_directory_files`**
   - Lista todos os arquivos em um diretório específico
   - Retorna uma lista com os caminhos relativos dos arquivos
   - Utilizado para navegação e descoberta de arquivos

2. **`read_file_content`**
   - Lê o conteúdo completo de um arquivo específico
   - Retorna o conteúdo como texto puro
   - Permite leitura segura de arquivos no workspace

3. **`generate_repo_map`**
   - Gera um mapa estrutural do repositório
   - Exibe a árvore de arquivos e assinaturas de classes/funções
   - Utilizado para compreensão da estrutura do projeto

### `edit_existing_file` com Validação de Snippet

A ferramenta `edit_existing_file` permite edição segura de arquivos existentes:

- **Validação de Snippet**: O sistema verifica se o trecho a ser substituído existe exatamente como especificado
- **Precisão**: Utiliza busca literal para evitar alterações acidentais
- **Segurança**: Garante que apenas trechos específicos sejam modificados

### Ferramentas de Git e Manipulação

1. **`create_git_branch`**
   - Cria novas branches git
   - Implementa proteções contra criação em branches protegidas

2. **`create_new_file`**
   - Cria novos arquivos no sistema de arquivos
   - Garante a criação de diretórios intermediários se necessário

3. **`append_to_file`**
   - Adiciona conteúdo ao final de arquivos existentes
   - Mantém o conteúdo original intacto

4. **`git_commit_changes`**
   - Realiza commits das mudanças no repositório Git
   - Inclui mensagens de commit padronizadas

## Restrições de Git e Segurança

### Proteções Implementadas

1. **Branch Protegida**
   - Impede a criação de novas branches em `main` ou `master`
   - Verifica o status atual do repositório antes de operações

2. **Validação de Contexto**
   - Verifica se o workspace está configurado corretamente
   - Garante que as operações ocorram no diretório correto

3. **Segurança de Operações**
   - Todas as operações são validadas antes da execução
   - Implementa mecanismos para evitar alterações acidentais

## Mecanismo de Injeção de Contexto via `runtime.state`

O sistema utiliza o mecanismo de injeção de contexto através do `runtime.state`:

1. **Contexto de Execução**
   - Informações sobre o workspace atual
   - Status da branch Git em uso
   - Configurações específicas para a execução

2. **Injeção Automática**
   - Contexto é injetado automaticamente nas operações
   - Permite que as ferramentas operem com base no ambiente correto

## Travas de Segurança Implementadas

### Validações de Segurança

1. **Verificação de Branch**
   - Impede operações em branches protegidas
   - Confirma o status da branch antes de qualquer alteração

2. **Validação de Caminhos**
   - Garante que apenas caminhos relativos ao workspace sejam usados
   - Evita acesso a diretórios fora do escopo permitido

3. **Snippets Exatos**
   - Requer trechos exatos para operações de edição
   - Impede alterações acidentais em arquivos

### Controles de Execução

1. **Proteção contra Operações Perigosas**
   - Validações antes de qualquer operação de escrita
   - Confirmação de contexto antes da execução

2. **Mecanismos de Backup**
   - Sistema de validação para evitar perda de dados
   - Verificações antes de alterações significativas

## Fluxo de Execução e Integração

### Integração com o Restante do Sistema

1. **Fluxo de Processamento**
   - As ferramentas são invocadas através dos nós do grafo
   - Contexto é passado automaticamente via `runtime.state`
   - Resultados são integrados ao histórico da conversa

2. **Integração com LangGraph**
   - Ferramentas são bindadas aos modelos LLM
   - Chamadas de ferramentas são processadas como parte do fluxo
   - Resultados são retornados para o próximo nó do grafo

3. **Gestão de Erros**
   - Tratamento específico para falhas em operações de arquivo
   - Feedback ao usuário sobre problemas de acesso ou permissão
   - Logs detalhados para diagnóstico de problemas

### Exemplo de Fluxo

1. Um nó do grafo invoca `read_file_content` para ler um arquivo
2. O sistema verifica o contexto atual via `runtime.state`
3. A leitura é realizada com segurança no workspace especificado
4. O conteúdo é retornado ao nó para processamento adicional
5. Se necessário, uma ferramenta de edição é chamada para modificar o código

## Considerações Finais

O sistema de ferramentas foi projetado com foco em segurança e precisão, permitindo que os agentes interajam com o ambiente de desenvolvimento de forma controlada e segura. As proteções implementadas garantem que as operações sejam realizadas apenas no contexto apropriado, evitando alterações acidentais ou perigosas no código-fonte do projeto.