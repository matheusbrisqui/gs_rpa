import hashlib
import math

from .config import settings


def hash_usuario(identificador: str | None) -> str | None:
    """LGPD: guarda só um hash salgado e truncado; o identificador original é descartado."""
    if not identificador:
        return None
    digest = hashlib.sha256(f"{settings.hash_salt}:{identificador.strip().lower()}".encode()).hexdigest()
    return digest[:16]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre duas coordenadas."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
