"""IA locale et gratuite via Ollama (https://ollama.com), pour utiliser Celia sans crédit API.

Ollama fait tourner un modèle d'IA directement sur votre ordinateur : gratuit, privé,
mais moins performant que Claude et sans recherche web.
"""
import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"   # bon en français et sait utiliser des outils ; « qwen2.5:3b » pour les Mac 8 Go


def _request(path, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def is_running() -> bool:
    try:
        with _request("/api/tags", timeout=2) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def installed_models():
    try:
        with _request("/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except (OSError, urllib.error.URLError, ValueError):
        return []


def has_model(model: str) -> bool:
    names = installed_models()
    return model in names or f"{model}:latest" in names


def pull(model: str, progress=lambda msg: None):
    """Télécharge le modèle (une seule fois, plusieurs Go)."""
    with _request("/api/pull", {"name": model, "stream": True}, timeout=3600) as r:
        for line in r:
            try:
                info = json.loads(line)
            except ValueError:
                continue
            if info.get("error"):
                raise RuntimeError(info["error"])
            total, done = info.get("total"), info.get("completed")
            if total and done:
                progress(f"Téléchargement de l'IA gratuite… {done * 100 // total} % "
                         f"({total / 1e9:.1f} Go, une seule fois)")
            elif info.get("status"):
                progress(f"IA gratuite : {info['status']}")


def _tools_for_ollama(tools):
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools]


def chat(model, system, history, question, tools, run_tool, max_rounds=6) -> str:
    """Conversation avec le modèle local, en exécutant ses appels d'outils (planning, mémoire…)."""
    messages = [{"role": "system", "content": system}] + list(history) + [{"role": "user", "content": question}]
    payload_tools = _tools_for_ollama(tools)
    for _ in range(max_rounds):
        with _request("/api/chat", {"model": model, "messages": messages, "tools": payload_tools,
                                    "stream": False, "options": {"temperature": 0.4}}, timeout=300) as r:
            msg = json.load(r).get("message", {})
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            out, _ = run_tool(fn.get("name", ""), args)
            messages.append({"role": "tool", "content": out, "tool_name": fn.get("name", "")})
    return "Je n'ai pas réussi à terminer cette demande."
