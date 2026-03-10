import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import lru_cache
from urllib.parse import urlencode

import httpx
from openai import OpenAI

from app.core.config import settings


_SUPPORTED_LANGS = {"uz", "en", "ru", "ko"}
_FAST_LANGUAGE_DETECT = os.getenv("OPENAI_FAST_LANGUAGE_DETECT", "1") == "1"
_LANG_LABELS = {
    "uz": "Uzbek",
    "en": "English",
    "ru": "Russian",
    "ko": "Korean",
    "auto": "auto",
}
_UZ_HINT_WORDS = {
    "va",
    "uchun",
    "qanday",
    "qaysi",
    "nima",
    "necha",
    "kerak",
    "bu",
    "shu",
    "ham",
    "emas",
    "mumkin",
    "lozim",
    "bo'yicha",
    "bilan",
    "yoki",
    "hujjat",
    "band",
    "bandda",
    "jadval",
    "masofa",
    "masofani",
    "balandlik",
    "kenglik",
    "qazish",
    "taqiqlanadi",
    "yozilgan",
    "qilinadi",
    "ortiq",
    "past",
    "tomonga",
    "qurilish",
    "me'yor",
    "talab",
}
_EN_HINT_WORDS = {
    "what",
    "which",
    "where",
    "when",
    "why",
    "how",
    "is",
    "are",
    "be",
    "the",
    "and",
    "or",
    "for",
    "with",
    "in",
    "of",
    "to",
    "from",
    "by",
    "on",
    "at",
    "shall",
    "must",
    "required",
    "minimum",
    "maximum",
    "distance",
    "depth",
    "height",
    "width",
    "requirements",
    "fire",
    "safety",
}


def _script_counts(text: str) -> tuple[int, int, int, int]:
    value = text or ""
    hangul = sum(1 for ch in value if 0xAC00 <= ord(ch) <= 0xD7AF)
    cyrillic = sum(1 for ch in value if 0x0400 <= ord(ch) <= 0x04FF)
    ascii_count = sum(1 for ch in value if ord(ch) < 128)
    return hangul, cyrillic, ascii_count, len(value)


def _is_strong_english_text(text: str) -> bool:
    hangul, cyrillic, ascii_count, total = _script_counts(text)
    if total == 0 or hangul > 0 or cyrillic > 0:
        return False
    tokens = re.findall(r"[a-zA-Z']+", (text or "").lower())
    if len(tokens) < 3:
        return False
    en_hits = sum(1 for token in tokens if token in _EN_HINT_WORDS)
    ascii_ratio = ascii_count / max(total, 1)
    return en_hits >= 1 and ascii_ratio > 0.95


def _parse_language_token(raw: str) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return None
    compact = re.sub(r"[^a-z]", "", value)
    if compact.startswith("en") or "english" in compact:
        return "en"
    if compact.startswith("uz") or "uzbek" in compact:
        return "uz"
    if compact.startswith("ru") or "russian" in compact:
        return "ru"
    if compact.startswith("ko") or "korean" in compact:
        return "ko"
    return None


def _heuristic_detect_language(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return "uz"

    hangul_count, cyrillic_count, ascii_count, total = _script_counts(normalized)
    if hangul_count > 0 and hangul_count >= cyrillic_count:
        return "ko"
    if cyrillic_count > 0:
        return "ru"

    tokens = re.findall(r"[a-zA-Z']+", normalized.lower())
    if not tokens:
        return "uz"

    uz_hits = sum(1 for token in tokens if token in _UZ_HINT_WORDS)
    if any(ch in normalized for ch in ("o'", "g'", "o`", "g`")) or uz_hits >= 2:
        return "uz"

    en_hits = sum(1 for token in tokens if token in _EN_HINT_WORDS)
    ascii_ratio = ascii_count / max(total, 1)
    if en_hits >= 2 or (en_hits >= 1 and ascii_ratio > 0.98 and len(tokens) >= 4 and uz_hits == 0):
        return "en"
    return "uz"


def detect_query_language(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return "uz"
    heuristic = _heuristic_detect_language(value)
    if _FAST_LANGUAGE_DETECT:
        return heuristic
    if heuristic in {"ko", "ru"}:
        return heuristic
    if heuristic == "en":
        return "en"

    system = (
        "You are a strict language classifier. "
        "Return only one token from this set: "
        "'uz' for Uzbek, 'en' for English, 'ru' for Russian, 'ko' for Korean."
    )
    prompt = (
        "Detect the language of this user query.\n"
        "If mixed, choose the dominant language.\n"
        f"Query: {value}\n\nLanguage:"
    )
    try:
        raw = generate_text(
            prompt=prompt,
            system=system,
            options={"temperature": 0.0, "top_p": 0.9, "max_tokens": 4},
        )
        parsed = _parse_language_token(raw)
        if parsed in _SUPPORTED_LANGS:
            if heuristic in {"ko", "ru"} and parsed != heuristic:
                return heuristic
            if heuristic == "en" and parsed in {"ru", "ko"}:
                return "en"
            return parsed
    except Exception:
        pass
    return heuristic


@lru_cache(maxsize=1)
def _get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.EMBEDDING_MODEL, trust_remote_code=True)


def _normalize_vector(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def _encode_with_local_model(value: str) -> list[float]:
    embedder = _get_embedder()
    vector = embedder.encode([value], convert_to_numpy=True, normalize_embeddings=True)[0]
    return [float(v) for v in vector.tolist()]


def embed_text(text: str) -> list[float]:
    value = (text or "").strip()
    if not value:
        return []

    # Primary path: HuggingFace Inference API for BAAI/bge-m3.
    hf_token = settings.HF_TOKEN
    if hf_token:
        try:
            with httpx.Client(timeout=settings.EMBEDDING_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"https://api-inference.huggingface.co/models/{settings.EMBEDDING_MODEL}",
                    headers={"Authorization": f"Bearer {hf_token}"},
                    json={"inputs": value, "options": {"wait_for_model": True}},
                )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data and isinstance(data[0], (int, float)):
                    return _normalize_vector([float(v) for v in data])
                if isinstance(data, list) and data and isinstance(data[0], list):
                    dim = len(data[0])
                    accum = [0.0] * dim
                    count = 0
                    for row in data:
                        if not isinstance(row, list) or len(row) != dim:
                            continue
                        for idx, val in enumerate(row):
                            accum[idx] += float(val)
                        count += 1
                    if count > 0:
                        return _normalize_vector([v / count for v in accum])
        except Exception:
            pass

    # Fallback path: local sentence-transformers.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-embed")
    future = executor.submit(_encode_with_local_model, value)
    try:
        return future.result(timeout=settings.EMBEDDING_TIMEOUT_SECONDS)
    except FuturesTimeoutError as exc:
        future.cancel()
        raise TimeoutError(
            f"Embedding timeout after {settings.EMBEDDING_TIMEOUT_SECONDS} seconds"
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@lru_cache(maxsize=1)
def _get_openai_client() -> OpenAI:
    api_key = settings.OPENAI_API_KEY or settings.DEEPSEEK_API_KEY
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY yoki DEEPSEEK_API_KEY kiritilmagan.")
    kwargs = {"api_key": api_key}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL.rstrip("/")
    return OpenAI(**kwargs)


def generate_text(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    options: dict | None = None,
) -> str:
    req = {
        "model": model or settings.CHAT_MODEL,
        "messages": [],
        "stream": False,
    }
    if system:
        req["messages"].append({"role": "system", "content": system})
    req["messages"].append({"role": "user", "content": prompt})
    if options:
        for key in ("temperature", "top_p", "max_tokens"):
            if key in options:
                req[key] = options[key]
    response = _get_openai_client().chat.completions.create(**req)
    if not response.choices:
        return ""
    message = response.choices[0].message
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            if isinstance(chunk, dict):
                text = chunk.get("text")
            else:
                text = getattr(chunk, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts).strip()
    return str(content or "").strip()


def generate_answer(
    user_message: str,
    context: str,
    system_prompt: str | None = None,
    model: str | None = None,
) -> str:
    sys_prompt = system_prompt or (
        "Siz SHNQ/QMQ normativ hujjatlar bo'yicha aniq javob beradigan yordamchisiz. "
        "Faqat berilgan kontekstdan foydalaning, ishonchingiz bo'lmasa ochiq ayting."
    )
    prompt = (
        "KONTEKST:\n"
        f"{context}\n\n"
        "SAVOL:\n"
        f"{user_message}\n\n"
        "QISQA VA ANIQ JAVOB:"
    )
    return generate_text(
        prompt=prompt,
        system=sys_prompt,
        model=model or settings.CHAT_MODEL,
        options={"temperature": 0.1, "max_tokens": 700},
    )


def translate_text(
    text: str,
    target_language: str,
    source_language: str = "auto",
) -> str:
    value = (text or "").strip()
    if not value or target_language not in _SUPPORTED_LANGS:
        return value
    if source_language == target_language:
        return value
    source_label = _LANG_LABELS.get(source_language, "auto")
    target_label = _LANG_LABELS.get(target_language, "Uzbek")
    system = (
        "You are a professional translator. Translate accurately and naturally. "
        "Preserve SHNQ/QMQ/SNIP codes, numbers, and units exactly. "
        "Return only the translated text without explanations."
    )
    prompt = (
        f"Source language: {source_label}\n"
        f"Target language: {target_label}\n"
        f"Text:\n{value}\n\nTranslated text:"
    )
    try:
        translated = generate_text(
            prompt=prompt,
            system=system,
            options={"temperature": 0.0, "top_p": 0.9, "max_tokens": 320},
        )
        if translated and translated.strip():
            return translated.strip()
    except Exception:
        pass

    fallback = _http_translate_fallback(
        value,
        target_language=target_language,
        source_language=source_language,
        timeout=10,
    )
    if fallback and fallback.strip():
        return fallback.strip()
    return value


def _http_translate_fallback(
    text: str,
    target_language: str,
    source_language: str = "auto",
    timeout: int = 10,
) -> str:
    payload = (text or "").strip()
    if not payload:
        return payload
    if target_language not in _SUPPORTED_LANGS:
        return payload

    params = {
        "client": "gtx",
        "sl": source_language if source_language in _SUPPORTED_LANGS else "auto",
        "tl": target_language,
        "dt": "t",
        "q": payload,
    }
    url = "https://translate.googleapis.com/translate_a/single?" + urlencode(params)
    try:
        resp = httpx.get(url, timeout=max(5, int(timeout)))
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return payload
        chunks = data[0]
        if not isinstance(chunks, list):
            return payload
        text_parts: list[str] = []
        for item in chunks:
            if isinstance(item, list) and item:
                piece = item[0]
                if isinstance(piece, str) and piece:
                    text_parts.append(piece)
        joined = "".join(text_parts).strip()
        return joined or payload
    except Exception:
        return payload


def _is_suspicious_search_translation(source_language: str, translated: str) -> bool:
    if not (translated or "").strip():
        return True
    hangul, cyrillic, _ascii_count, _total = _script_counts(translated)
    if source_language == "ko" and hangul > 0:
        return True
    if source_language == "ru" and cyrillic > 0:
        return True
    return False


def _translate_to_uz_for_search(message: str, source_language: str) -> str:
    primary_source = "en" if source_language == "en" else "auto"
    first = translate_text(message, target_language="uz", source_language=primary_source)
    if not _is_suspicious_search_translation(source_language, first):
        return first

    try:
        pivot_en = translate_text(message, target_language="en", source_language="auto")
        second = translate_text(pivot_en, target_language="uz", source_language="en")
        if not _is_suspicious_search_translation(source_language, second):
            return second
    except Exception:
        pass

    try:
        system = (
            "You rewrite user queries into clear Uzbek (Latin script) for semantic search. "
            "Keep SHNQ/QMQ/SNIP codes, numbers, units, and technical terms exact."
        )
        prompt = (
            f"Original language: {_LANG_LABELS.get(source_language, 'auto')}\n"
            "Rewrite this query into Uzbek (Latin) only:\n"
            f"{message}\n\nUzbek query:"
        )
        forced = generate_text(
            prompt=prompt,
            system=system,
            options={"temperature": 0.0, "top_p": 0.9, "max_tokens": 220},
        )
        if forced and forced.strip():
            return forced.strip()
    except Exception:
        pass
    return first


def translate_query_for_search(message: str, source_language: str) -> str:
    if source_language in {"en", "ru", "ko"}:
        return _translate_to_uz_for_search(message, source_language=source_language)
    return message


def ensure_answer_language(answer: str, target_language: str) -> str:
    if target_language not in _SUPPORTED_LANGS:
        return answer
    if _looks_like_target_language(answer, target_language):
        return answer

    last_candidate = answer
    for source in ("uz", "auto"):
        try:
            candidate = translate_text(answer, target_language=target_language, source_language=source)
        except Exception:
            continue
        if candidate and candidate.strip():
            last_candidate = candidate.strip()
            if _looks_like_target_language(last_candidate, target_language):
                return last_candidate
    return last_candidate


def _looks_like_target_language(text: str, target_language: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    hangul, cyrillic, _ascii_count, _total = _script_counts(value)
    if target_language == "ko":
        return hangul > 0
    if target_language == "ru":
        return cyrillic > 0
    if target_language == "en":
        if cyrillic > 0 or hangul > 0:
            return False
        return _is_strong_english_text(value)
    if target_language == "uz":
        if cyrillic > 0 or hangul > 0:
            return False
        tokens = re.findall(r"[a-zA-Z']+", value.lower())
        uz_hits = sum(1 for token in tokens if token in _UZ_HINT_WORDS)
        en_hits = sum(1 for token in tokens if token in _EN_HINT_WORDS)
        if any(ch in value for ch in ("o'", "g'", "o`", "g`")):
            return True
        if uz_hits >= 2:
            return True
        if en_hits >= 2 and uz_hits == 0:
            return False
        return uz_hits >= en_hits
    return False
