"""Three polished scenarios and the simulated world they drive.

Every check is synthetic. Nothing here touches a real network or account.
"""

from __future__ import annotations

import copy

SCENARIOS: dict[str, dict] = {
    "vpn_down": {
        "id": "vpn_down",
        "kb_id": "NET-VPN-014",
        "title_en": "Internet works, VPN does not",
        "title_es": "El internet funciona, la VPN no",
        "default_device": "ThinkPad-T14",
        "default_code": "VPN-ERR-4012",
        "prompt_en": "My internet works but the VPN does not. Error code VPN-ERR-4012 on device ThinkPad-T14.",
        "prompt_es": "El internet funciona pero la VPN no. Código VPN-ERR-4012 en el equipo ThinkPad-T14.",
        "steps": [
            {
                "id": "reopen_client",
                "en": "Quit and reopen the Puente Tunnel client. Leave the firewall on.",
                "es": "Cierra y vuelve a abrir el cliente Puente Tunnel. Deja el firewall activo.",
                "phrases": [
                    "reopen",
                    "reopened",
                    "restarted the client",
                    "opened the client",
                    "quit and reopen",
                    "reinicié",
                    "reinicie",
                    "volví a abrir",
                    "volvi a abrir",
                    "abrí el cliente",
                    "abri el cliente",
                    "cerré y abrí",
                    "cerre y abri",
                    "cliente de vpn",
                ],
            },
            {
                "id": "sso_reauth",
                "en": "Complete the company SSO prompt on the device. Do not paste a password here.",
                "es": "Completa el aviso de SSO de la empresa en el equipo. No pegues una contraseña aquí.",
                "phrases": [
                    "signed in",
                    "sso",
                    "reauthenticated",
                    "logged in",
                    "inicié sesión",
                    "inicie sesion",
                    "inicio de sesión",
                    "inicio de sesion",
                    "volví a entrar",
                    "volvi a entrar",
                    "me autentic",
                    "autenticación",
                    "autenticacion",
                ],
            },
        ],
    },
    "dns_failure": {
        "id": "dns_failure",
        "kb_id": "NET-DNS-008",
        "title_en": "Wi-Fi is up, websites do not load",
        "title_es": "El Wi-Fi está conectado y las páginas no cargan",
        "default_device": "CORP-LAPTOP-04",
        "default_code": "DNS-ERR-2201",
        "prompt_en": "Wi-Fi is connected but websites won't load. Error DNS-ERR-2201 on device CORP-LAPTOP-04.",
        "prompt_es": "El Wi-Fi está conectado pero las páginas no cargan. Error DNS-ERR-2201 en el equipo CORP-LAPTOP-04.",
        "steps": [
            {
                "id": "flush_dns",
                "en": "Flush the local DNS cache. Do not switch to an unknown public resolver.",
                "es": "Vacía la caché DNS local. No cambies a un resolver público desconocido.",
                "phrases": [
                    "flushed",
                    "flush",
                    "dns cache",
                    "vacié la caché",
                    "vacie la cache",
                    "vacié la cache",
                    "limpié el dns",
                    "limpie el dns",
                    "caché dns",
                    "cache dns",
                ],
            },
            {
                "id": "rejoin_wifi",
                "en": "Disconnect and rejoin the CORP-WIFI network.",
                "es": "Desconecta y vuelve a unirte a la red CORP-WIFI.",
                "phrases": [
                    "rejoined",
                    "rejoin",
                    "corp-wifi",
                    "volví a conectar",
                    "volvi a conectar",
                    "me reconecté",
                    "me reconecte",
                    "reconecté",
                    "reconecte",
                ],
            },
        ],
    },
    "printer_offline": {
        "id": "printer_offline",
        "kb_id": "END-PRT-021",
        "title_en": "Printer shows offline",
        "title_es": "La impresora figura fuera de línea",
        "default_device": "HP-LaserJet-M404",
        "default_code": "PRT-ERR-3308",
        "prompt_en": "The printer HP-LaserJet-M404 is offline. Error PRT-ERR-3308. My computer is CORP-LAPTOP-04.",
        "prompt_es": "La impresora HP-LaserJet-M404 está fuera de línea. Error PRT-ERR-3308. Mi equipo es CORP-LAPTOP-04.",
        "steps": [
            {
                "id": "resume_queue",
                "en": "Resume the print queue for HP-LaserJet-M404. The simulated check already sees the printer powered on.",
                "es": "Reanuda la cola de impresión de HP-LaserJet-M404. La comprobación simulada ya ve la impresora encendida.",
                "phrases": [
                    "resumed",
                    "resume the queue",
                    "resume the print",
                    "resumed the print",
                    "print queue",
                    "reanudé",
                    "reanude",
                    "cola de impresión",
                    "cola de impresion",
                    "activé la cola",
                    "active la cola",
                ],
            }
        ],
    },
}


def initial_world(scenario_id: str, devices: list[str]) -> dict:
    primary = devices[0] if devices else SCENARIOS[scenario_id]["default_device"]
    printer_name = next((item for item in devices if item.startswith("HP-")), "HP-LaserJet-M404")
    laptop = next((item for item in devices if item.startswith("CORP-LAPTOP") or item.startswith("ThinkPad")), primary)
    world = {
        "device": laptop if scenario_id != "printer_offline" else printer_name,
        "laptop": laptop,
        "wifi": {"associated": True, "internet": True, "ssid": "CORP-WIFI", "lease": "fresh"},
        "vpn": {"tunnel": "up", "client": "running", "error_code": None},
        "dns": {"resolves": True, "resolver": "10.8.8.8", "error_code": None, "flushed": False},
        "printer": {
            "online": True,
            "queue": "ready",
            "error_code": None,
            "name": printer_name,
            "powered": True,
        },
        "auth": {"sso": "fresh"},
        "password_reset_queued": False,
    }
    if scenario_id == "vpn_down":
        world["device"] = next((item for item in devices if item.startswith("ThinkPad")), "ThinkPad-T14")
        world["vpn"] = {"tunnel": "down", "client": "stopped", "error_code": "VPN-ERR-4012"}
        world["auth"] = {"sso": "stale"}
    elif scenario_id == "dns_failure":
        world["device"] = next((item for item in devices if item.startswith("CORP-LAPTOP")), "CORP-LAPTOP-04")
        world["dns"] = {
            "resolves": False,
            "resolver": "10.8.8.8",
            "error_code": "DNS-ERR-2201",
            "flushed": False,
        }
        world["wifi"]["lease"] = "stale"
    elif scenario_id == "printer_offline":
        world["printer"] = {
            "online": False,
            "queue": "paused",
            "error_code": "PRT-ERR-3308",
            "name": printer_name,
            "powered": True,
        }
    return world


def apply_step(world: dict, scenario_id: str, step_id: str) -> None:
    if scenario_id == "vpn_down" and step_id == "reopen_client":
        world["vpn"]["client"] = "running"
        if world["auth"]["sso"] == "fresh":
            world["vpn"]["tunnel"] = "up"
            world["vpn"]["error_code"] = None
    elif scenario_id == "vpn_down" and step_id == "sso_reauth":
        world["auth"]["sso"] = "fresh"
        world["password_reset_queued"] = True
        if world["vpn"]["client"] == "running":
            world["vpn"]["tunnel"] = "up"
            world["vpn"]["error_code"] = None
    elif scenario_id == "dns_failure" and step_id == "flush_dns":
        world["dns"]["flushed"] = True
        if world["wifi"]["lease"] == "fresh":
            world["dns"]["resolves"] = True
            world["dns"]["error_code"] = None
    elif scenario_id == "dns_failure" and step_id == "rejoin_wifi":
        world["wifi"]["lease"] = "fresh"
        world["wifi"]["associated"] = True
        if world["dns"]["flushed"]:
            world["dns"]["resolves"] = True
            world["dns"]["error_code"] = None
    elif scenario_id == "printer_offline" and step_id == "resume_queue":
        world["printer"]["queue"] = "ready"
        world["printer"]["online"] = True
        world["printer"]["error_code"] = None


def matched_steps(scenario_id: str, text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for step in SCENARIOS[scenario_id]["steps"]:
        if any(phrase in lowered for phrase in step["phrases"]):
            found.append(step["id"])
    return found


def next_step_id(state: dict) -> str | None:
    done = set(state.get("steps_done") or [])
    for step in SCENARIOS[state["scenario_id"]]["steps"]:
        if step["id"] not in done:
            return step["id"]
    return None


def step_copy(scenario_id: str, step_id: str, language: str) -> str:
    for step in SCENARIOS[scenario_id]["steps"]:
        if step["id"] == step_id:
            return step["es"] if language == "es" else step["en"]
    return ""


def is_resolved(scenario_id: str, world: dict) -> bool:
    if scenario_id == "vpn_down":
        return (
            world["vpn"]["tunnel"] == "up"
            and world["wifi"]["internet"]
            and world["dns"]["resolves"]
        )
    if scenario_id == "dns_failure":
        return world["dns"]["resolves"] and world["wifi"]["associated"]
    if scenario_id == "printer_offline":
        return world["printer"]["online"] and world["printer"]["queue"] == "ready"
    return False


def clone_world(world: dict) -> dict:
    return copy.deepcopy(world)
