"""Regras de negócio da triagem. Funções puras: fáceis de testar e de auditar."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

TIPOS_VALIDOS = {
    "buraco",
    "carro_na_calcada",
    "entulho_lixo",
    "poste_obstaculo",
    "degrau_sem_rampa",
    "iluminacao",
    "outro",
}
PERFIS_PRIORITARIOS = {"pcd", "idoso"}

# Códigos das regras de prioridade (aparecem nos logs no lugar de dados do cidadão)
R1_ALTA = "R1"  # perfil prioritário E obstáculo junto a ponto de ônibus
R2_MEDIA = "R2"  # perfil prioritário OU obstáculo junto a ponto de ônibus
R3_NORMAL = "R3"  # demais casos


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre duas coordenadas (fórmula de haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ler_data(valor: str | None) -> datetime | None:
    """Converte a data ISO da API. Datas sem fuso são tratadas como UTC."""
    if not valor:
        return None
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=UTC)


def validar(relato: dict, area: tuple[float, float, float, float], agora: datetime) -> list[str]:
    """Devolve os motivos de rejeição. Lista vazia = relato válido."""
    motivos = []
    if relato.get("tipo") not in TIPOS_VALIDOS:
        motivos.append("tipo_desconhecido")
    lat, lon = relato.get("lat"), relato.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        motivos.append("coordenada_ausente")
    else:
        lat_min, lat_max, lon_min, lon_max = area
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            motivos.append("fora_da_area_atendida")
    criado = ler_data(relato.get("criado_em"))
    if criado is None:
        motivos.append("data_invalida")
    elif criado > agora + timedelta(minutes=5):
        motivos.append("data_no_futuro")
    return motivos


def encontrar_duplicado(
    relato: dict, candidatos: list[dict], raio_m: float, janela_dias: int, agora: datetime
) -> tuple[int, float] | None:
    """Procura um relato em aberto do mesmo tipo dentro do raio. Devolve (id, distância) do mais próximo."""
    limite = agora - timedelta(days=janela_dias)
    melhor: tuple[int, float] | None = None
    for c in candidatos:
        if c["id"] == relato["id"] or c.get("tipo") != relato.get("tipo"):
            continue
        criado = ler_data(c.get("criado_em"))
        if criado is not None and criado < limite:
            continue
        d = distancia_m(relato["lat"], relato["lon"], c["lat"], c["lon"])
        if d <= raio_m and (melhor is None or d < melhor[1]):
            melhor = (c["id"], d)
    return melhor


def ponto_mais_proximo(relato: dict, pontos: list[dict]) -> tuple[dict, float] | None:
    melhor: tuple[dict, float] | None = None
    for p in pontos:
        d = distancia_m(relato["lat"], relato["lon"], p["lat"], p["lon"])
        if melhor is None or d < melhor[1]:
            melhor = (p, d)
    return melhor


def definir_prioridade(perfil: str | None, distancia_ponto_m: float | None, raio_ponto_m: float) -> tuple[str, str]:
    """Regra de decisão da triagem. Devolve (prioridade, código da regra)."""
    prioritario = perfil in PERFIS_PRIORITARIOS
    junto_ao_ponto = distancia_ponto_m is not None and distancia_ponto_m <= raio_ponto_m
    if prioritario and junto_ao_ponto:
        return "alta", R1_ALTA
    if prioritario or junto_ao_ponto:
        return "media", R2_MEDIA
    return "normal", R3_NORMAL


def gerar_protocolo(relato_id: int, agora: datetime) -> str:
    """Protocolo determinístico: o mesmo relato no mesmo dia gera sempre o mesmo número."""
    return f"PL-{agora:%Y%m%d}-{relato_id:05d}"
