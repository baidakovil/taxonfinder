from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes


class PlainTextLoader:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".txt"

    def load(self, path: Path, *, max_file_size_mb: float) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        size_bytes = path.stat().st_size
        max_bytes = int(max_file_size_mb * 1024 * 1024)
        if size_bytes > max_bytes:
            size_mb = size_bytes / (1024 * 1024)
            raise ValueError(
                f"Input file exceeds maximum size ({max_file_size_mb:.1f} MB). "
                f"Current: {size_mb:.1f} MB."
            )

        data = path.read_bytes()
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return _decode_with_fallback(data)


def _decode_with_fallback(data: bytes) -> str:
    best = from_bytes(data).best()
    candidates: list[str] = []
    if best is not None and best.encoding:
        candidates.append(best.encoding)
    candidates.extend(["cp1251", "koi8-r", "iso8859-5", "mac_cyrillic"])

    best_text: str | None = None
    best_score = 0
    for encoding in candidates:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        score = _cyrillic_score(text)
        if score > best_score:
            best_score = score
            best_text = text

    if best_text is not None and best_score > 0:
        return best_text

    raise ValueError("Unable to detect input file encoding. Please convert the file to UTF-8.")


def _has_cyrillic(text: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)


def _cyrillic_score(text: str) -> int:
    lower = 0
    upper = 0
    for char in text:
        if "а" <= char <= "я" or char == "ё":
            lower += 1
        elif "А" <= char <= "Я" or char == "Ё":
            upper += 1
    return lower * 2 + upper


def _has_non_ascii(data: bytes) -> bool:
    return any(byte > 0x7F for byte in data)


__all__ = ["PlainTextLoader"]
