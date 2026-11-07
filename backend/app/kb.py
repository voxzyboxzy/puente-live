"""Bilingual knowledge base and overlap retrieval."""

from __future__ import annotations

import re

ARTICLES: list[dict] = [
    {
        "id": "NET-VPN-014",
        "scenario_id": "vpn_down",
        "title_en": "VPN-ERR-4012 while internet still works",
        "title_es": "VPN-ERR-4012 cuando el internet sí funciona",
        "source_label": "Puente KB · NET-VPN-014",
        "body_en": (
            "Use this note when a laptop still opens public sites but Puente Tunnel "
            "reports VPN-ERR-4012. The internet path is up and the VPN tunnel is not. "
            "The usual cause is a stopped client or a stale company SSO token. "
            "Safe sequence: quit and reopen the Puente Tunnel client, then complete the "
            "SSO prompt on the device. Do not disable the firewall. Do not paste a "
            "password into the chat. When the client is running and the token is fresh, "
            "the tunnel comes back and VPN-ERR-4012 clears. ThinkPad-T14 is the reference device."
        ),
        "body_es": (
            "Usa esta nota cuando un portátil aún abre sitios públicos pero Puente Tunnel "
            "informa VPN-ERR-4012. El internet está activo y el túnel VPN no. "
            "La causa habitual es un cliente detenido o un token SSO de la empresa vencido. "
            "Secuencia segura: cierra y vuelve a abrir el cliente Puente Tunnel, y completa "
            "el aviso de SSO en el equipo. No desactives el firewall. No pegues una "
            "contraseña en el chat. Cuando el cliente está en ejecución y el token está fresco, "
            "el túnel vuelve y VPN-ERR-4012 desaparece. ThinkPad-T14 es el equipo de referencia."
        ),
    },
    {
        "id": "NET-DNS-008",
        "scenario_id": "dns_failure",
        "title_en": "DNS-ERR-2201 with Wi-Fi associated",
        "title_es": "DNS-ERR-2201 con el Wi-Fi asociado",
        "source_label": "Puente KB · NET-DNS-008",
        "body_en": (
            "Wi-Fi can be connected while websites still fail with DNS-ERR-2201. "
            "On CORP-LAPTOP-04 the synthetic resolver 10.8.8.8 stops answering when the "
            "CORP-WIFI lease is stale and the local DNS cache is dirty. "
            "Safe sequence: flush the local DNS cache, then disconnect and rejoin CORP-WIFI. "
            "Do not point the laptop at an unknown public resolver. Do not disable the firewall. "
            "After both steps, name resolution works and DNS-ERR-2201 clears."
        ),
        "body_es": (
            "El Wi-Fi puede estar conectado y aun así las páginas fallan con DNS-ERR-2201. "
            "En CORP-LAPTOP-04 el resolver sintético 10.8.8.8 deja de responder cuando el "
            "arrendamiento de CORP-WIFI está viejo y la caché DNS local está sucia. "
            "Secuencia segura: vacía la caché DNS local y luego desconecta y vuelve a CORP-WIFI. "
            "No apuntes el equipo a un resolver público desconocido. No desactives el firewall. "
            "Después de los dos pasos, la resolución de nombres funciona y DNS-ERR-2201 se limpia."
        ),
    },
    {
        "id": "END-PRT-021",
        "scenario_id": "printer_offline",
        "title_en": "PRT-ERR-3308 printer queue paused",
        "title_es": "PRT-ERR-3308 cola de impresora en pausa",
        "source_label": "Puente KB · END-PRT-021",
        "body_en": (
            "HP-LaserJet-M404 reports PRT-ERR-3308 when the queue is paused. "
            "The printer can be powered on and still look offline from CORP-LAPTOP-04. "
            "Safe sequence: confirm power is on, then resume the print queue. "
            "Do not install an unsigned driver. Do not disable endpoint protection. "
            "When the queue is ready, the printer is online and PRT-ERR-3308 clears."
        ),
        "body_es": (
            "HP-LaserJet-M404 informa PRT-ERR-3308 cuando la cola está en pausa. "
            "La impresora puede estar encendida y aun así verse fuera de línea desde CORP-LAPTOP-04. "
            "Secuencia segura: confirma que hay energía y reanuda la cola de impresión. "
            "No instales un controlador sin firma. No desactives la protección del equipo. "
            "Cuando la cola está lista, la impresora queda en línea y PRT-ERR-3308 se limpia."
        ),
    },
    {
        "id": "SAFE-001",
        "scenario_id": None,
        "title_en": "Safe troubleshooting boundaries",
        "title_es": "Límites del diagnóstico seguro",
        "source_label": "Puente KB · SAFE-001",
        "body_en": (
            "Never disable the firewall, antivirus, or MFA to force a fix. "
            "Never reveal, repeat, or request a password. Never open all ports. "
            "Never format a disk to repair VPN, DNS, or a printer. "
            "Stay on the scenario checklist and hand the redacted packet to a technician "
            "when the checks do not clear."
        ),
        "body_es": (
            "Nunca desactives el firewall, el antivirus ni el MFA para forzar un arreglo. "
            "Nunca reveles, repitas ni pidas una contraseña. Nunca abras todos los puertos. "
            "Nunca formatees un disco para reparar la VPN, el DNS o una impresora. "
            "Sigue la lista del escenario y entrega el paquete redactado a un técnico "
            "cuando las comprobaciones no se limpien."
        ),
    },
]

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "when", "then", "into",
    "your", "una", "para", "con", "por", "del", "las", "los", "que", "esta",
    "está", "el", "la", "en", "un", "al", "se", "su", "es", "de", "lo", "ya",
}


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9áéíóúüñ]{2,}", text.lower())
    return {token for token in raw if token not in _STOP}


def search(utterance: str, scenario_id: str | None = None, limit: int = 2) -> list[dict]:
    query = _tokens(utterance)
    ranked: list[dict] = []
    for article in ARTICLES:
        document = _tokens(
            " ".join(
                [
                    article["title_en"],
                    article["title_es"],
                    article["body_en"],
                    article["body_es"],
                    article["id"],
                ]
            )
        )
        overlap = len(query & document) / len(query | document) if query and document else 0.0
        prior = 0.2 if scenario_id and article["scenario_id"] == scenario_id else 0.0
        ranked.append({**article, "overlap": round(overlap, 4), "rank_score": round(overlap + prior, 4)})
    ranked.sort(key=lambda item: item["rank_score"], reverse=True)
    chosen = ranked[:limit]
    if scenario_id:
        must = next((item for item in ranked if item["scenario_id"] == scenario_id), None)
        if must and must["id"] not in {item["id"] for item in chosen}:
            chosen.append(must)
    return chosen


def cite(article: dict, language: str) -> dict:
    body = article["body_es"] if language == "es" else article["body_en"]
    title = article["title_es"] if language == "es" else article["title_en"]
    excerpt = body[:240].rstrip()
    if len(body) > 240:
        excerpt += "…"
    return {
        "id": article["id"],
        "title": title,
        "title_en": article["title_en"],
        "title_es": article["title_es"],
        "excerpt": excerpt,
        "language": language,
        "source_label": article["source_label"],
        "overlap": article.get("overlap", 0),
        "rank_score": article.get("rank_score", 0),
        "scenario_id": article["scenario_id"],
    }


def article_by_id(article_id: str) -> dict | None:
    return next((item for item in ARTICLES if item["id"] == article_id), None)
