from pathlib import Path
import os
import re
import ast
from langchain_core.tools import tool

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
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.php'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}
    
    REGEX_FALLBACK = re.compile(
        r'^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+\w+'
        r'|^\s*(?:public|private|protected)\s+(?:static\s+)?(?:function)\s+\w+', 
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