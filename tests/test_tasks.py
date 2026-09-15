import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tasks import run_async_task, run_langgraph_task, run_generate_task, get_event_loop

# Testes para run_async_task
@pytest.mark.asyncio
async def test_run_async_task_success():
    """Testa execução bem-sucedida de tarefa assíncrona"""
    # Mock da função assíncrona
    mock_func = AsyncMock(return_value="resultado_teste")
    
    result = await run_async_task(mock_func, "param1", "param2")
    
    assert result == "resultado_teste"
    mock_func.assert_called_once_with("param1", "param2")

@pytest.mark.asyncio
async def test_run_async_task_timeout():
    """Testa timeout na execução de tarefa assíncrona"""
    # Mock da função que vai causar timeout
    mock_func = AsyncMock()
    mock_func.side_effect = asyncio.TimeoutError()
    
    with pytest.raises(asyncio.TimeoutError):
        await run_async_task(mock_func, "param1", timeout=0.1)

# Testes para run_langgraph_task
@pytest.mark.asyncio
async def test_run_langgraph_task_success():
    """Testa execução bem-sucedida de tarefa langgraph"""
    # Mock do LangGraph
    mock_graph = MagicMock()
    mock_graph.ainvoke.return_value = {"output": "resultado_langgraph"}
    
    with patch('tasks.langchain') as mock_langchain:
        mock_langchain.LangGraph.return_value = mock_graph
        
        result = await run_langgraph_task("input_teste")
        
        assert result == {"output": "resultado_langgraph"}

@pytest.mark.asyncio
async def test_run_langgraph_task_error():
    """Testa erro na execução de tarefa langgraph"""
    # Mock do LangGraph que lança exceção
    mock_graph = MagicMock()
    mock_graph.ainvoke.side_effect = Exception("Erro no langgraph")
    
    with patch('tasks.langchain') as mock_langchain:
        mock_langchain.LangGraph.return_value = mock_graph
        
        with pytest.raises(Exception) as exc_info:
            await run_langgraph_task("input_teste")
        
        assert str(exc_info.value) == "Erro no langgraph"

# Testes para run_generate_task
@pytest.mark.asyncio
async def test_run_generate_task_success():
    """Testa execução bem-sucedida de tarefa de geração"""
    # Mock do modelo de linguagem
    mock_model = MagicMock()
    mock_model.ainvoke.return_value = "resultado_geracao"
    
    with patch('tasks.ChatOpenAI') as mock_chat:
        mock_chat.return_value = mock_model
        
        result = await run_generate_task("prompt_teste", {"param1": "valor1"})
        
        assert result == "resultado_geracao"

@pytest.mark.asyncio
async def test_run_generate_task_with_parameters():
    """Testa execução de tarefa de geração com parâmetros"""
    # Mock do modelo de linguagem
    mock_model = MagicMock()
    mock_model.ainvoke.return_value = "resultado_com_parametros"
    
    with patch('tasks.ChatOpenAI') as mock_chat:
        mock_chat.return_value = mock_model
        
        result = await run_generate_task("prompt_teste", {"param1": "valor1", "param2": "valor2"})
        
        assert result == "resultado_com_parametros"

# Testes para get_event_loop
def test_get_event_loop():
    """Testa obtenção do event loop"""
    loop = get_event_loop()
    
    # Verifica se o loop é um objeto asyncio
    assert hasattr(loop, 'run_until_complete')