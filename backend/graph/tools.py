from pathlib import Path
import os
import re
import ast
import subprocess
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

@tool
def list_directory_files(dir_path: str) -> list:
    """
    Lista todos os arquivos de código dentro de uma pasta e suas subpastas.
    Use esta ferramenta para descobrir a estrutura do diretório e ver quais arquivos existem 
    antes de decidir quais você precisa ler o conteúdo.
    
    Args:
        dir_path (str): O caminho da pasta que deve ser mapeada.
        
    Returns:
        list: Uma lista contendo os caminhos (paths) de todos os arquivos encontrados.
    """
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.php', '.html', '.css', '.sql'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}

    file_paths = []
    
    for root, dirs, files in os.walk(dir_path):
        
        allowed_dirs = []
        for dir_name in dirs:
            if dir_name not in IGNORED_DIRS:
                allowed_dirs.append(dir_name)
        
        dirs[:] = allowed_dirs
        
        for file_name in files:
            if Path(file_name).suffix in CODE_EXTENSIONS:
                file_path = Path(root) / file_name
                file_paths.append(str(file_path))
                
    return file_paths

@tool
def read_file_content(file_path: str) -> str:
    """
    Lê e retorna o conteúdo (código-fonte) de um único arquivo específico.
    Use esta ferramenta APÓS usar a ferramenta 'list_directory_files', quando você já souber 
    o caminho exato do arquivo que precisa analisar.
    
    Args:
        file_path (str): O caminho exato do arquivo que você deseja ler.
        
    Returns:
        str: O texto com o código contido dentro do arquivo, ou uma mensagem de erro.
    """
    try:
        return Path(file_path).read_text(encoding='utf-8')
    except Exception as error:
        return f"Erro ao ler o arquivo: {str(error)}"
    

def parse_python_ast(content: str, indent: str) -> list:
    """Usa o AST para extrair classes e funções com precisão cirúrgica no Python"""
    signatures = []
    try:
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                signatures.append(f"{indent}    🔹 class {node.name}:")
                # Pega os métodos dentro da classe
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) or isinstance(child, ast.AsyncFunctionDef):
                        signatures.append(f"{indent}        🔸 def {child.name}(...)")
            
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                signatures.append(f"{indent}    🔹 def {node.name}(...)")
    except Exception:
        signatures.append(f"{indent}    ⚠️ (Erro de sintaxe no AST)")
    return signatures

@tool
def generate_repo_map(dir_path: str) -> str:
    """
    Gera um mapa estrutural do repositório, exibindo a árvore de arquivos e 
    as assinaturas de classes e funções, sem o corpo do código.
    Use isso para entender a arquitetura completa antes de decidir quais arquivos ler integralmente.
    
    Args:
        dir_path (str): O caminho da pasta que deve ser mapeada.
        
    Returns:
        str: Uma representação em texto da árvore do projeto com as assinaturas de código.
    """
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.php', '.md'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}
    
    REGEX_FALLBACK = re.compile(
        r'^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+\w+'
        r'|^\s*(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>', 
        re.MULTILINE
    )

    repo_map = [f"Mapa do Repositório: {dir_path}\n"]
    
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        
        level = root.replace(dir_path, '').count(os.sep)
        indent = ' ' * 4 * level
        folder_name = os.path.basename(root)
        
        if folder_name:
            repo_map.append(f"{indent}📂 {folder_name}/")
            
        sub_indent = ' ' * 4 * (level + 1)
        
        for file_name in files:
            ext = Path(file_name).suffix
            if ext in CODE_EXTENSIONS:
                file_path = Path(root) / file_name
                repo_map.append(f"{sub_indent}📄 {file_name}")
                
                try:
                    content = file_path.read_text(encoding='utf-8')
                    
                    if ext == '.py':
                        py_sigs = parse_python_ast(content, sub_indent)
                        repo_map.extend(py_sigs)
                    else:
                        signatures = REGEX_FALLBACK.findall(content)
                        for sig in signatures:
                            repo_map.append(f"{sub_indent}    🔹 {sig.strip()}")
                except Exception:
                    repo_map.append(f"{sub_indent}    ⚠️ (Erro ao ler arquivo)")
                    
    return "\n".join(repo_map)

# ──────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS (não são tools — não ficam visíveis pro LLM)
# ──────────────────────────────────────────────────────────────────────────

PROTECTED_BRANCHES = {"main", "master"}

def _resolve_path(file_path: str, workspace_path: str | None) -> Path:
    """Resolve o caminho recebido do LLM contra o workspace da conversa.
    Se o LLM já mandou um caminho absoluto, usa como está; se mandou
    relativo (o comportamento esperado e mais comum), junta com o
    workspace_path do State."""
    path = Path(file_path)
    if path.is_absolute():
        return path
    if workspace_path:
        return Path(workspace_path) / path
    return path

def _find_existing_ancestor(path: Path) -> Path:
    """Sobe na árvore de diretórios até achar uma pasta que já existe —
    necessário porque, ao criar um arquivo novo, as pastas pai ainda podem
    não existir no momento da checagem de branch."""
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _get_current_branch(file_path: str) -> str | None:
    """Retorna o nome da branch git atual do repositório que contém
    file_path, ou None se não for possível determinar (não é um repositório
    git, ou o comando git não está disponível)."""
    start_dir = _find_existing_ancestor(Path(file_path).parent)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(start_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def _check_not_on_protected_branch(file_path: str) -> str | None:
    """Retorna uma mensagem de erro se o arquivo estiver numa branch
    protegida (main/master); retorna None se a edição pode prosseguir."""
    branch = _get_current_branch(file_path)

    if branch is not None and branch in PROTECTED_BRANCHES:
        return (
            "ERRO DE SEGURANÇA: Você não pode editar arquivos na branch "
            "main/master. Use a ferramenta 'create_git_branch' primeiro!"
        )

    return None


# ──────────────────────────────────────────────────────────────────────────
# TOOLS
# ──────────────────────────────────────────────────────────────────────────

GENERATE_BRANCHES: dict[str, str] = {}
GENERATE_BRANCH_ATTEMPTS: dict[str, int] = {}
MAX_BRANCH_ATTEMPTS = 2

@tool
def create_git_branch(branch_name: str, runtime: ToolRuntime) -> str:
    """Cria uma nova branch git a partir da branch atual e muda para ela imediatamente.

    Use esta ferramenta OBRIGATORIAMENTE antes de qualquer edição de arquivo,
    assim que você receber uma nova tarefa. Nunca tente editar arquivos
    diretamente na branch 'main' ou 'master' — as ferramentas de escrita vão
    bloquear a operação automaticamente se você tentar. O repositório correto
    já é identificado automaticamente pelo sistema — você não precisa (e não
    consegue) informá-lo.

    Args:
        branch_name: Nome da nova branch, no padrão
            'feature/<resumo-curto-da-tarefa-atual>' (gere um resumo com base
            na tarefa que VOCÊ está executando agora — NUNCA reutilize um
            nome de exemplo genérico), em minúsculas, com palavras separadas
            por hífen, sem espaços ou acentos.

    Returns:
        Uma mensagem de sucesso confirmando a branch criada, ou uma mensagem
        de erro clara explicando o motivo da falha (branch já existe,
        caminho não é um repositório git, etc).
    """
    workspace_path = runtime.state.get("workspace_path")
    if not workspace_path:
        return "ERRO: nenhum workspace definido para esta conversa."

    repo = Path(workspace_path).resolve()
    repo_key = str(repo)

    attempts = GENERATE_BRANCH_ATTEMPTS.get(repo_key, 0)
    if attempts >= MAX_BRANCH_ATTEMPTS:
        return (
            "ERRO FATAL — EXECUÇÃO BLOQUEADA: já houve "
            f"{attempts} tentativas de criar uma branch para esta tarefa, "
            "todas falhando. NÃO tente mais nenhum nome de branch. "
            "Encerre a execução agora e reporte esta falha na sua resposta final, "
            "sem chamar nenhuma outra ferramenta."
        )

    if not repo.exists():
        return f"ERRO: o caminho '{workspace_path}' não existe."
    if not (repo / ".git").exists():
        return f"ERRO: '{workspace_path}' não é a raiz de um repositório git."

    base_commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    if base_commit_result.returncode != 0:
        return f"ERRO ao obter o commit atual: {base_commit_result.stderr.strip()}"
    base_commit = base_commit_result.stdout.strip()

    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(repo), capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "ERRO: comando 'git' não encontrado."
    except subprocess.TimeoutExpired:
        return "ERRO: timeout no comando git."

    if result.returncode != 0:
        # 👇 conta a falha
        GENERATE_BRANCH_ATTEMPTS[repo_key] = attempts + 1

        stderr = result.stderr.strip()
        if "already exists" in stderr:
            return f"ERRO: a branch '{branch_name}' já existe. Escolha outro nome."
        return f"ERRO ao criar a branch: {stderr}"

    # sucesso — zera o contador, a execução está progredindo
    GENERATE_BRANCH_ATTEMPTS[repo_key] = 0

    current_branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    current_branch = current_branch_result.stdout.strip()

    if current_branch != branch_name:
        return (
            "ERRO DE SEGURANÇA: a branch foi criada, mas a branch atual "
            f"é '{current_branch}' em vez de '{branch_name}'."
        )

    GENERATE_BRANCHES[repo_key] = {"branch": branch_name, "base_commit": base_commit}

    return f"Branch '{branch_name}' criada e ativada com sucesso. Commit base: {base_commit[:8]}."


@tool
def create_new_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Cria um novo arquivo do zero com o conteúdo especificado.

    Use esta ferramenta apenas para arquivos que AINDA NÃO EXISTEM. Se o
    arquivo já existir, use 'edit_existing_file' ou 'append_to_file'.
    Os diretórios intermediários do caminho são criados automaticamente
    caso não existam.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a criação de
    arquivos enquanto a branch atual for 'main' ou 'master'. Use
    'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório, incluindo nome e
            extensão (ex: 'backend/api/routes/users.py'). O sistema já
            resolve isso automaticamente contra o repositório correto — NÃO
            inclua o caminho absoluto do disco.
        content: O conteúdo completo do arquivo, exatamente como deve ficar
            gravado em disco (incluindo indentação e quebras de linha).

    Returns:
        Uma mensagem de sucesso com o caminho do arquivo criado, ou uma
        mensagem de erro explicando o motivo da falha.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if resolved_path.exists():
        return (
            f"ERRO: o arquivo '{file_path}' já existe. Use 'edit_existing_file' "
            "ou 'append_to_file' para modificar um arquivo existente."
        )

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
    except OSError as error:
        return f"ERRO ao criar o arquivo '{file_path}': {error}"

    return f"Arquivo '{file_path}' criado com sucesso ({len(content)} caracteres)."


@tool
def edit_existing_file(file_path: str, old_snippet: str, new_snippet: str, runtime: ToolRuntime) -> str:
    """Edita um arquivo existente substituindo um trecho exato por outro (search and replace).

    Use esta ferramenta em vez de reescrever o arquivo inteiro — isso evita
    perder partes do arquivo que não deveriam mudar. O 'old_snippet' deve
    ser copiado EXATAMENTE como aparece no arquivo (mesma indentação, mesmas
    quebras de linha) — use o conteúdo retornado por 'read_file_content'
    como referência, nunca digite de memória. O trecho precisa ser único no
    arquivo: se aparecer mais de uma vez, inclua linhas extras de contexto
    antes/depois até que ele se torne único.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório (ex: 'tasks.py'). O
            sistema já resolve isso automaticamente contra o repositório
            correto — NÃO inclua o caminho absoluto do disco.
        old_snippet: O trecho exato de texto já existente no arquivo que
            deve ser substituído.
        new_snippet: O novo trecho que deve tomar o lugar de 'old_snippet'.

    Returns:
        Uma mensagem de sucesso, ou um erro claro se o arquivo não existir,
        se 'old_snippet' não for encontrado, ou se aparecer mais de uma vez.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe. Use 'create_new_file' para criá-lo."
    
    try:
        original_content = resolved_path.read_text(encoding="utf-8")
    except OSError as error:
        return f"ERRO ao ler o arquivo '{file_path}': {error}"

    occurrences = original_content.count(old_snippet)

    if occurrences == 0:
        return (
            "ERRO: o trecho informado em 'old_snippet' não foi encontrado no "
            f"arquivo '{file_path}'. Confira se foi copiado exatamente como "
            "está no arquivo (indentação e quebras de linha incluídas)."
        )

    if occurrences > 1:
        return (
            f"ERRO: o trecho informado aparece {occurrences} vezes no arquivo "
            f"'{file_path}', e a edição precisa ser única. Inclua mais linhas "
            "de contexto antes ou depois do trecho para torná-lo único."
        )

    updated_content = original_content.replace(old_snippet, new_snippet)

    try:
        resolved_path.write_text(updated_content, encoding="utf-8")
    except OSError as error:
        return f"ERRO ao salvar o arquivo '{file_path}': {error}"

    return f"Arquivo '{file_path}' editado com sucesso."


@tool
def append_to_file(file_path: str, content: str, runtime: ToolRuntime) -> str:
    """Adiciona conteúdo ao final de um arquivo existente, sem alterar o que já está lá.

    Use esta ferramenta para casos simples de adição no final do arquivo,
    como uma nova rota em urls.py, uma nova variável em um .env, ou uma
    nova linha de log/configuração. Se o conteúdo precisar ser inserido no
    meio do arquivo, use 'edit_existing_file'.

    IMPORTANTE: esta ferramenta bloqueia automaticamente a edição enquanto a
    branch atual for 'main' ou 'master'. Use 'create_git_branch' antes.

    Args:
        file_path: Caminho RELATIVO à raiz do repositório. O sistema já
            resolve isso automaticamente contra o repositório correto — NÃO
            inclua o caminho absoluto do disco.
        content: O texto a ser adicionado ao final do arquivo. Inclua uma
            quebra de linha no início se o conteúdo precisar começar numa
            linha separada do que já existe.

    Returns:
        Uma mensagem de sucesso, ou um erro se o arquivo não existir.
    """
    workspace_path = runtime.state.get("workspace_path")
    resolved_path = _resolve_path(file_path, workspace_path)

    security_error = _check_not_on_protected_branch(str(resolved_path))
    if security_error:
        return security_error

    if not resolved_path.exists():
        return f"ERRO: o arquivo '{file_path}' não existe. Use 'create_new_file' para criá-lo."

    try:
        with resolved_path.open("a", encoding="utf-8") as file:
            file.write(content)
    except OSError as error:
        return f"ERRO ao adicionar conteúdo ao arquivo '{file_path}': {error}"

    return f"Conteúdo adicionado ao final de '{file_path}' com sucesso."


@tool
def git_commit_changes(commit_message: str, runtime: ToolRuntime) -> str:
    @tool
def git_commit_changes(commit_message: str, runtime: ToolRuntime) -> str:
    """Cria um commit git apenas com as alterações da tarefa atual.

    Use esta ferramenta SOMENTE no final da tarefa, depois de já ter feito
    todas as edições necessárias com as outras ferramentas de escrita.

    O commit só é permitido na branch criada pelo Generate para esta execução,
    e apenas as alterações pertencentes à tarefa devem ser incluídas. O
    repositório correto já é identificado automaticamente pelo sistema.

    A `commit_message` deve seguir o padrão Conventional Commits, escolhido
    de acordo com o tipo de mudança feita:
    - 'feat: ...' para uma nova funcionalidade;
    - 'fix: ...' para correção de bug;
    - 'refactor: ...' para mudança de estrutura sem alterar comportamento;
    - 'chore: ...' para tarefas de manutenção (configs, dependências);
    - 'docs: ...' para mudanças em documentação.

    Exemplo: 'feat: adiciona paginação na listagem de usuários' (gere a
    mensagem com base na mudança REAL que você implementou nesta execução —
    nunca reuse este exemplo literalmente).

    Args:
        commit_message: Mensagem do commit, seguindo o padrão Conventional
            Commits descrito acima.

    Returns:
        Uma mensagem de sucesso com a saída do commit, ou um erro explicando
        o motivo da falha (branch incorreta, nenhuma alteração para commitar,
        repositório inválido, etc).
    """
    workspace_path = runtime.state.get("workspace_path")
    if not workspace_path:
        return "ERRO: nenhum workspace definido para esta conversa."

    repo = Path(workspace_path).resolve()

    if not (repo / ".git").exists():
        return f"ERRO: '{workspace_path}' não é a raiz de um repositório git."

    execution = GENERATE_BRANCHES.get(str(repo))

    if execution is None:
        return (
            "ERRO DE SEGURANÇA: nenhuma branch foi criada pelo Generate "
            "para este repositório nesta execução."
        )

    expected_branch = execution["branch"]
    base_commit = execution["base_commit"]

    try:
        # Confirma branch atual.
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if branch_result.returncode != 0:
            return (
                "ERRO DE SEGURANÇA: não foi possível verificar "
                "a branch atual."
            )

        current_branch = branch_result.stdout.strip()

        if current_branch != expected_branch:
            return (
                "ERRO DE SEGURANÇA: a branch atual não é a branch "
                "criada pelo Generate.\n"
                f"Esperada: '{expected_branch}'\n"
                f"Atual: '{current_branch}'"
            )

        # Descobre os arquivos modificados desde o commit base.
        diff_result = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                base_commit,
                "HEAD",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if diff_result.returncode != 0:
            return (
                "ERRO ao verificar alterações da branch: "
                f"{diff_result.stderr.strip()}"
            )

        # Arquivos já commitados depois do base.
        committed_files = {
            line.strip()
            for line in diff_result.stdout.splitlines()
            if line.strip()
        }

        # Descobre alterações atuais, incluindo arquivos novos e deletados.
        status_result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )

        if status_result.returncode != 0:
            return (
                "ERRO ao verificar alterações pendentes: "
                f"{status_result.stderr.strip()}"
            )

        pending_files = set()

        for line in status_result.stdout.splitlines():
            if len(line) >= 4:
                file_path = line[3:].strip()

                # Trata rename no formato:
                # old -> new
                if " -> " in file_path:
                    file_path = file_path.split(" -> ")[-1].strip()

                pending_files.add(file_path)

        # Só podem entrar arquivos que pertençam à execução.
        execution_files = committed_files | pending_files

        if not execution_files:
            return (
                "AVISO: não havia nenhuma alteração da tarefa "
                "para commitar."
            )

        # Adiciona somente os arquivos detectados nesta execução.
        add_result = subprocess.run(
            ["git", "add", "--", *sorted(execution_files)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if add_result.returncode != 0:
            return (
                "ERRO ao executar git add: "
                f"{add_result.stderr.strip()}"
            )

        # Cria o commit.
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if commit_result.returncode != 0:
            combined_output = (
                commit_result.stderr + commit_result.stdout
            ).lower()

            if "nothing to commit" in combined_output:
                return "AVISO: não havia nenhuma mudança para commitar."

            return (
                "ERRO ao criar o commit: "
                f"{commit_result.stderr.strip() or commit_result.stdout.strip()}"
            )

        del GENERATE_BRANCHES[str(repo)] 
        
        return (
            f"Commit criado com sucesso na branch '{current_branch}'.\n"
            f"Arquivos incluídos: {', '.join(sorted(execution_files))}\n"
            f"{commit_result.stdout.strip()}"
        )

    except FileNotFoundError:
        return (
            "ERRO: comando 'git' não encontrado. "
            "Verifique se o Git está instalado e no PATH."
        )

    except subprocess.TimeoutExpired:
        return "ERRO: o comando git demorou demais para responder (timeout)."
    
