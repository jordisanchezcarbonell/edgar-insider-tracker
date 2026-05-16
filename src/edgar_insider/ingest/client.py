"""Cliente HTTP para la API pública de la SEC.

Encapsula tres cosas que cualquier llamada a la SEC necesita:
1. Headers obligatorios (User-Agent identificable, Accept-Encoding).
2. Rate limiting respetuoso (por debajo de los 10 req/s que permite la SEC).
3. Un reintento simple ante 429 (rate limit) o 503 (servicio no disponible).

Lo escribo como clase porque mantenemos estado: la sesión de `requests` (para
reutilizar la conexión TCP) y el timestamp de la última petición (para el
throttle). Una función suelta no podría llevar ese estado entre llamadas.
"""

from __future__ import annotations

import time

import requests

from edgar_insider.config import RATE_LIMIT_SLEEP_SECONDS, USER_AGENT


class SecClient:
    """Wrapper fino sobre requests.Session con throttle y reintento básico."""

    def __init__(self, user_agent: str = USER_AGENT, min_interval: float = RATE_LIMIT_SLEEP_SECONDS) -> None:
        self._session = requests.Session()
        # Headers recomendados por la SEC en https://www.sec.gov/os/accessing-edgar-data
        # El Host se setea automáticamente por urllib3 según la URL, no hace falta forzarlo.
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._min_interval = min_interval
        # Timestamp de la última petición. Empezamos en 0 para que la primera
        # llamada no espere.
        self._last_request_ts: float = 0.0

    def _throttle(self) -> None:
        """Duerme lo justo para que entre dos peticiones pasen `min_interval` segundos.

        En vez de un `time.sleep(min_interval)` ciego después de cada request
        (que sumaría latencia de red al sleep), medimos el tiempo desde la
        última petición y solo dormimos la diferencia. Más eficiente y más
        honesto con el rate limit real.
        """
        elapsed = time.monotonic() - self._last_request_ts
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, timeout: float = 30.0) -> requests.Response:
        """GET con throttle y un reintento ante 429/503.

        Levanta `requests.HTTPError` ante cualquier otro fallo (4xx/5xx).
        Preferimos fallar ruidosamente a esconder problemas con un retry loop
        agresivo — durante el aprendizaje queremos ver los errores reales.
        """
        for attempt in (1, 2):
            self._throttle()
            self._last_request_ts = time.monotonic()
            response = self._session.get(url, timeout=timeout)
            if response.status_code in (429, 503) and attempt == 1:
                # La SEC nos pide bajar el ritmo. Esperamos 2 segundos y reintentamos
                # una sola vez; si vuelve a fallar, dejamos que la excepción suba.
                print(f"  [warn] {response.status_code} en {url}, reintentando en 2s…")
                time.sleep(2.0)
                continue
            response.raise_for_status()
            return response
        # Inalcanzable: el bucle siempre termina con return o con raise_for_status.
        raise RuntimeError("unreachable")
