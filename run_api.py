"""Sobe a API com SelectorEventLoop (o psycopg async não funciona com o ProactorEventLoop do Windows).

Uso: python run_api.py [porta] [host]
"""
import asyncio
import sys

import uvicorn

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
HOST = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"


def main():
    server = uvicorn.Server(uvicorn.Config("backend.main:app", host=HOST, port=PORT))
    if sys.version_info >= (3, 12):
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
