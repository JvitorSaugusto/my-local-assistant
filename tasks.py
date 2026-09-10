from typing import cast
from backend.api.schemas import GenerateTaskSchema
from backend.main import DB_URI_LANGGRAPH
from celery import Celery
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import HumanMessage
from psycopg import Connection
from langchain_core.runnables.config import RunnableConfig
from backend.graph import build_graph, State


celery_app = Celery("assistente_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")

celery_app.conf.task_routes = {"tasks.run_generate_task": {"queue": "generate_sequential"},}

@celery_app.task(bind=True)
def run_langgraph_task(self, thread_id: str, user_input: str):
    with Connection.connect(DB_URI_LANGGRAPH) as conn:
        
        checkpointer = PostgresSaver(conn) # type: ignore
        
        builder = build_graph() 
        app_graph = builder.compile(checkpointer=checkpointer)
        
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        inputs = cast(State, {"messages": [HumanMessage(content=user_input)]})
        
        app_graph.invoke(inputs, config=config)
        
    
    return {"status": "concluido", "thread_id": thread_id, "mensagem": "Salvo no DB!"}

@celery_app.task(bind=True)
def run_generate_task(self, thread_id: str, task_data: dict):
    with Connection.connect(DB_URI_LANGGRAPH) as conn:

        checkpointer = PostgresSaver(conn)  # type: ignore

        builder = build_graph()
        app_graph = builder.compile(
            checkpointer=checkpointer
        )

        config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id
            }
        }

        task = GenerateTaskSchema.model_validate(task_data)

        task_prompt = f"""
            EXECUTE A TAREFA DE IMPLEMENTAÇÃO.

            TÍTULO:
            {task.title}

            DESCRIÇÃO:
            {task.description}

            ARQUIVOS RELEVANTES:
            {task.files}

            MOTIVAÇÃO:
            {task.reason}
        """

        inputs = {
            "messages": [
                HumanMessage(content=task_prompt)
            ],
            "actual_route": "GENERATE",
            "active_generate_task": task,
            "thread_id": thread_id,
        }

        app_graph.invoke(
            inputs,
            config=config,
        )

    return {
        "status": "concluido",
        "thread_id": thread_id,
        "task_id": task.id,
    }