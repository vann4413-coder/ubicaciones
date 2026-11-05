"""Cliente HTTP compartido con reintentos y caché en memoria."""
import asyncio
import time
from typing import Any

import httpx

from app import config

_cliente: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 6 * 3600


def cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None:
        _cliente = httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            # El servicio de carburantes devuelve XML salvo que se pida JSON expresamente.
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json, */*;q=0.5"},
            follow_redirects=True,
        )
    return _cliente


async def cerrar() -> None:
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None


class ErrorFuente(Exception):
    """La fuente externa no respondió o devolvió algo inesperado."""


async def _pedir(metodo: str, url: str, *, params=None, data=None, reintentos=2) -> httpx.Response:
    ultimo: Exception | None = None
    for intento in range(reintentos + 1):
        try:
            r = await cliente().request(metodo, url, params=params, data=data)
            if r.status_code >= 500 or r.status_code == 429:
                raise ErrorFuente(f"{url} respondió {r.status_code}")
            r.raise_for_status()
            return r
        except (httpx.HTTPError, ErrorFuente) as e:
            ultimo = e
            if intento < reintentos:
                await asyncio.sleep(1.5 * (intento + 1))
    raise ErrorFuente(str(ultimo))


def _clave(url, params, data):
    return f"{url}|{sorted((params or {}).items())}|{data}"


async def get_json(url: str, params: dict | None = None, cache: bool = True) -> Any:
    k = _clave(url, params, None)
    if cache and k in _cache and time.time() - _cache[k][0] < CACHE_TTL:
        return _cache[k][1]
    r = await _pedir("GET", url, params=params)
    try:
        valor = r.json()
    except ValueError as e:
        raise ErrorFuente(f"Respuesta no JSON de {url}: {r.text[:200]}") from e
    if cache:
        _cache[k] = (time.time(), valor)
    return valor


async def get_text(url: str, params: dict | None = None, cache: bool = True) -> str:
    k = _clave(url, params, None)
    if cache and k in _cache and time.time() - _cache[k][0] < CACHE_TTL:
        return _cache[k][1]
    r = await _pedir("GET", url, params=params)
    if cache:
        _cache[k] = (time.time(), r.text)
    return r.text


async def post_json(url: str, data: dict, cache: bool = True) -> Any:
    k = _clave(url, None, data)
    if cache and k in _cache and time.time() - _cache[k][0] < CACHE_TTL:
        return _cache[k][1]
    r = await _pedir("POST", url, data=data)
    valor = r.json()
    if cache:
        _cache[k] = (time.time(), valor)
    return valor


async def get_bytes(url: str, params: dict | None = None) -> tuple[bytes, str]:
    """Descarga binaria (PDF, imágenes). Devuelve (contenido, content-type)."""
    r = await _pedir("GET", url, params=params)
    return r.content, r.headers.get("content-type", "")
