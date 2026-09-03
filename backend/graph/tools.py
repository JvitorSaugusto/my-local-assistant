from pathlib import Path
import os
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
    

@tool
def ingest_directory(dir_path: str) -> dict:
    """
    Lê uma pasta inteira no computador e retorna o conteúdo de todos os arquivos de código encontrados.
    Use esta ferramenta quando precisar analisar projetos inteiros, ler códigos-fonte de um diretório ou
    buscar o contexto de múltiplos arquivos de uma só vez (ex: auditorias de segurança ou documentação).
    
    A ferramenta ignora automaticamente pastas de sistema (como node_modules, .git, venv) e
    captura apenas arquivos com extensões de programação (ex: .py, .js, .html, .css).
    
    Args:
        dir_path (str): O caminho completo (absoluto ou relativo) da pasta que deve ser lida.
        
    Returns:
        dict: Um dicionário onde as chaves são os caminhos dos arquivos e os valores são os textos (códigos) contidos neles.
    """
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.php', '.html', '.css', '.sql'}
    IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'env'}

    result = {}

    for root, dirs, files in os.walk(dir_path):
        
        allowed_dirs = []
        for dir_name in dirs:
            if dir_name not in IGNORED_DIRS:
                allowed_dirs.append(dir_name)
                
        dirs[:] = allowed_dirs
        
        for file_name in files:
            if Path(file_name).suffix in CODE_EXTENSIONS:
                file_path = Path(root) / file_name

                try:
                    result[str(file_path)] = file_path.read_text(encoding='utf-8')

                except UnicodeDecodeError:
                    continue

    return result
