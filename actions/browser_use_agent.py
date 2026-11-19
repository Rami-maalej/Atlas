from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from core.llm_client import resolve_llm_url

logger = logging.getLogger("browser_use")


def _find_config() -> dict:
    cfg: dict = {}
    try:
        from core.paths import config_path
        p = config_path("api_keys.json")
        cfg = json.loads(p.read_text())
    except Exception:
        cfg = {}
    if "llm_provider" not in cfg:
        # Sandbox / missing config — fall back to the repository config,
        # same mechanism used by core.llm_client.
        repo = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        try:
            cfg.update(json.loads(repo.read_text()))
        except Exception:
            pass
    if cfg.get("llm_url_local") or cfg.get("llm_url_remote"):
        cfg["llm_url"] = resolve_llm_url(cfg)
    return cfg


def _make_chat_openai(model: str, api_key: str, base: str):
    """Return a chat client, preferring browser-use's own ChatOpenAI.

    When browser_use is missing, fall back to the plain ``openai`` SDK so the
    configured provider can still be reached programmatically.
    """
    try:
        from browser_use.llm import ChatOpenAI

        return ChatOpenAI(model=model, api_key=api_key, base_url=base)
    except ImportError:
        pass
    try:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base)
    except ImportError:
        return None


def _build_llm_client() -> dict | None:
    """Build the browser-use LLM client for the configured provider.

    ``browser_use`` is an optional dependency — when it is missing the caller
    gets a clear message instead of an ImportError traceback.
    """
    cfg = _find_config()
    provider = cfg.get("llm_provider", "nvidia-nim")
    llm_url = cfg.get("llm_url", "http://localhost:11434")
    llm_model = cfg.get("llm_model", "llama3.2")
    key_field = ""
    try:
        from core.llm_provider_detector import get_provider
        p = get_provider(provider.replace("-", "_"))
        key_field = (p or {}).get("key_field", "")
    except Exception:
        pass
    api_key = (cfg.get(key_field) or "").strip() if key_field else ""
    if not api_key:
        api_key = (cfg.get("llm_api_key") or "not-needed").strip()

    base = llm_url.rstrip("/") + "/v1"

    if provider == "nvidia_nim":
        # NIM requires the FULL model id (e.g. nvidia/nemotron-...).
        # Stripping the prefix made every chat call return 404.
        model = llm_model
        client = _make_chat_openai(model, api_key, base)
        if client is None:
            return None
        return {"client": client, "model": model}

    if provider == "openai":
        client = _make_chat_openai(llm_model, api_key, base)
        if client is None:
            return None
        return {"client": client, "model": llm_model}

    if provider in ("ollama", "openrouter"):
        client = _make_chat_openai(llm_model, api_key, base)
        if client is None:
            return None
        return {"client": client, "model": llm_model}

    client = _make_chat_openai(llm_model, api_key, base)
    if client is None:
        return None
    return {
        "client": client,
        "model": llm_model,
    }


def run_browser_use_task(
    task: str,
    timeout: int = 180,
    headless: bool = True,
    max_steps: int = 30,
    use_vision: bool = False,
) -> str:
    start = time.time()
    logger.info("browser-use task: %.80s", task)

    try:
        llm_info = _build_llm_client()
        if llm_info is None:
            return "No LLM client configured for browser-use."
        llm = llm_info["client"]

        from browser_use import Agent, Browser

        browser = Browser(headless=headless)
        agent = Agent(task=task, llm=llm, browser=browser)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            history = loop.run_until_complete(
                asyncio.wait_for(agent.run(max_steps=max_steps), timeout=timeout)
            )
        finally:
            try:
                loop.run_until_complete(browser.close())
            except Exception:
                pass
            loop.close()
            asyncio.set_event_loop(None)

        elapsed = time.time() - start
        final = getattr(history, "final_result", None)
        result = final() if callable(final) else None
        if result:
            text = str(result).strip()
        else:
            text = str(history)
            if not text or text == "None":
                text = "Task completed but no result returned."

        logger.info("browser-use done in %.1fs: %.100s", elapsed, text)
        return text

    except TimeoutError:
        logger.warning("browser-use timed out after %ds", timeout)
        return f"Task timed out after {timeout} seconds."
    except ImportError as e:
        logger.error("browser-use import error: %s", e)
        return f"browser-use library not available: {e}"
    except Exception as e:
        logger.exception("browser-use error")
        return f"browser-use error: {e}"
