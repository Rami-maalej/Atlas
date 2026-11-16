from __future__ import annotations

import json
import logging
from io import BytesIO

try:  # Optional deps — without them we still explain the screen from the
    # accessibility tree + active window instead of failing outright.
    import cv2
    import mss
    import numpy as np
    from PIL import Image
    _HAS_VISION = True
except ImportError:  # pragma: no cover - depends on the host install
    cv2 = None  # type: ignore[assignment]
    mss = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _HAS_VISION = False

logger = logging.getLogger("screen_explain")

_OLLAMA_URL = "http://127.0.0.1:11434"
_MODEL = "qwen2.5:7b"


def _ollama_running() -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(f"{_OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_chat(messages: list[dict], model: str = _MODEL) -> str:
    import urllib.request
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(f"{_OLLAMA_URL}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data.get("message", {}).get("content", "")


def _screenshot() -> bytes:
    if not _HAS_VISION:
        raise RuntimeError("screenshot support missing (install mss + pillow)")
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=50)
        return buf.getvalue()


def _analyze_image(img_bytes: bytes) -> dict:
    if not _HAS_VISION:
        return {}
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return {}
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    edges = cv2.Canny(gray, 50, 150)
    edge_pct = float(np.count_nonzero(edges) / edges.size * 100)

    dom_colors = {}
    for _ in range(3):
        data = img.reshape(-1, 3)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, labels, centers = cv2.kmeans(data.astype(np.float32), 3, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        for i, c in enumerate(centers):
            hex_c = f"#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x}"
            count = int(np.sum(labels == i))
            dom_colors[hex_c] = dom_colors.get(hex_c, 0) + count
        break

    dom_colors = sorted(dom_colors.items(), key=lambda x: -x[1])[:5]
    top_colors = [c for c, _ in dom_colors]

    text_regions = 0
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 11, 2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect = cw / max(ch, 1)
        area = cw * ch
        if 20 < area < 50000 and 0.1 < aspect < 10 and ch > 4:
            text_regions += 1

    return {
        "resolution": f"{w}x{h}",
        "brightness": f"{brightness:.0f}/255",
        "contrast": f"{contrast:.0f}",
        "edge_density": f"{edge_pct:.1f}%",
        "dominant_colors": top_colors,
        "text_like_regions": text_regions,
    }


def _active_window() -> str:
    try:
        from actions.screen_reader import get_active_window_info
        info = get_active_window_info()
        return f"{info.get('title', '?')} ({info.get('app', '?')})"
    except Exception as e:
        logger.warning("Active window detection failed: %s", e)
        return "unknown"


def _ui_elements() -> list[dict]:
    try:
        from actions.screen_reader import get_ui_elements
        elems = get_ui_elements()
        seen = set()
        unique = []
        for e in elems[:30]:
            key = (e.get("name", ""), e.get("role", ""))
            if key not in seen:
                seen.add(key)
                unique.append(e)
        return unique[:15]
    except Exception:
        return []


def screen_explain(parameters: dict = None, **kwargs) -> str:
    img_bytes = None
    if _HAS_VISION:
        try:
            img_bytes = _screenshot()
        except Exception as e:
            logger.error("Screenshot failed: %s", e)

    img_info = _analyze_image(img_bytes) if img_bytes else {}
    window = _active_window()
    elements = _ui_elements()

    if img_info is None:
        img_info = {}

    if not img_info and not elements and window == "unknown":
        return "I cannot see the screen — screenshot support is not installed."

    ui_text = "\n".join(
        f"  {e.get('role', '?')}: {e.get('name', '')}" for e in elements
    ) if elements else "  (none detected)"

    prompt = (
        "You are JARVIS. A screenshot was taken. Here is what I know about it:\n\n"
        f"Active window: {window}\n"
        f"Resolution: {img_info.get('resolution', '?')}\n"
        f"Brightness: {img_info.get('brightness', '?')}\n"
        f"Contrast: {img_info.get('contrast', '?')}\n"
        f"Edge density: {img_info.get('edge_density', '?')}\n"
        f"Dominant colors: {', '.join(img_info.get('dominant_colors', []))}\n"
        f"Text-like regions: {img_info.get('text_like_regions', '?')}\n\n"
        f"Accessibility tree:\n{ui_text}\n\n"
        "Describe concisely what is on the user's screen right now — the app, its layout, "
        "what elements are visible. Be specific but brief (2-4 sentences)."
    )

    if _ollama_running():
        try:
            messages = [
                {"role": "user", "content": prompt}
            ]
            return _ollama_chat(messages)
        except Exception as e:
            logger.warning("Ollama vision failed: %s", e)

    fallback_parts = [f"Active window: {window}"]
    if img_info.get("resolution"):
        fallback_parts.append(f"Screen: {img_info['resolution']}, "
                              f"brightness {img_info.get('brightness')}")
    if elements:
        fallback_parts.append(f"{len(elements)} UI elements detected")
    return ". ".join(fallback_parts) + "."
