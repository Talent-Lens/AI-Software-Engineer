# scripts/run_agents.py
from agents.graph import app

chat_result = app.invoke({"mode": "chat", "question": "How does basic auth work?", "file_path": "", "result": {}})
print("Code Chat:", chat_result["result"])

docs_result = app.invoke({"mode": "docs", "question": "", "file_path": "test_repo/src/requests/auth.py", "result": {}})
print("Docs:", docs_result["result"])