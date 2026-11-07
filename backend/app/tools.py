"""Simulated network and device checks.

Results are derived from the session world. They never contact a network,
a directory, or a printer.
"""

from __future__ import annotations


def _result(tool: str, ok: bool, summary_en: str, summary_es: str, evidence: dict) -> dict:
    return {
        "tool": tool,
        "ok": ok,
        "safe": True,
        "summary_en": summary_en,
        "summary_es": summary_es,
        "evidence": evidence,
    }


def check_wifi(world: dict) -> dict:
    wifi = world["wifi"]
    ok = bool(wifi.get("associated") and wifi.get("internet"))
    device = world.get("laptop") or world.get("device")
    if ok:
        en = f"Wi-Fi is associated to {wifi.get('ssid')} and internet egress is up on {device}."
        es = f"El Wi-Fi está asociado a {wifi.get('ssid')} y la salida a internet está activa en {device}."
    else:
        en = f"Wi-Fi or internet egress is down on {device}."
        es = f"El Wi-Fi o la salida a internet está caída en {device}."
    return _result(
        "check_wifi",
        ok,
        en,
        es,
        {
            "associated": wifi.get("associated"),
            "internet": wifi.get("internet"),
            "ssid": wifi.get("ssid"),
            "lease": wifi.get("lease"),
            "device": device,
        },
    )


def check_vpn(world: dict) -> dict:
    vpn = world["vpn"]
    ok = vpn.get("tunnel") == "up"
    device = world.get("device")
    code = vpn.get("error_code")
    if ok:
        en = f"VPN tunnel is up on {device}. No active VPN error code."
        es = f"El túnel VPN está activo en {device}. No hay un código de error VPN activo."
    else:
        en = f"VPN tunnel is down on {device} with {code}. Client state: {vpn.get('client')}."
        es = f"El túnel VPN está caído en {device} con {code}. Estado del cliente: {vpn.get('client')}."
    return _result(
        "check_vpn",
        ok,
        en,
        es,
        {
            "tunnel": vpn.get("tunnel"),
            "client": vpn.get("client"),
            "error_code": code,
            "device": device,
        },
    )


def check_dns(world: dict) -> dict:
    dns = world["dns"]
    ok = bool(dns.get("resolves"))
    device = world.get("laptop") or world.get("device")
    code = dns.get("error_code")
    if ok:
        en = f"DNS resolves on {device} through synthetic resolver {dns.get('resolver')}."
        es = f"El DNS resuelve en {device} por el resolver sintético {dns.get('resolver')}."
    else:
        en = f"DNS does not resolve on {device}. {code} at resolver {dns.get('resolver')}."
        es = f"El DNS no resuelve en {device}. {code} en el resolver {dns.get('resolver')}."
    return _result(
        "check_dns",
        ok,
        en,
        es,
        {
            "resolves": dns.get("resolves"),
            "resolver": dns.get("resolver"),
            "error_code": code,
            "flushed": dns.get("flushed"),
            "device": device,
        },
    )


def check_printer(world: dict) -> dict:
    printer = world["printer"]
    ok = bool(printer.get("online") and printer.get("queue") == "ready")
    name = printer.get("name")
    code = printer.get("error_code")
    if ok:
        en = f"{name} is online and the queue is ready."
        es = f"{name} está en línea y la cola está lista."
    else:
        en = f"{name} is offline with {code}. Queue: {printer.get('queue')}. Power observed: {printer.get('powered')}."
        es = f"{name} está fuera de línea con {code}. Cola: {printer.get('queue')}. Energía observada: {printer.get('powered')}."
    return _result(
        "check_printer",
        ok,
        en,
        es,
        {
            "online": printer.get("online"),
            "queue": printer.get("queue"),
            "error_code": code,
            "name": name,
            "powered": printer.get("powered"),
        },
    )


def reset_password(world: dict) -> dict:
    """Queue a synthetic SSO reauth. Never accepts or returns a password."""
    world["password_reset_queued"] = True
    device = world.get("device")
    return _result(
        "reset_password",
        True,
        f"Queued a synthetic SSO reauthentication for {device}. No password was collected or stored.",
        f"Encolé una reautenticación SSO sintética para {device}. No se pidió ni se guardó ninguna contraseña.",
        {"device": device, "sso": world.get("auth", {}).get("sso"), "secret_stored": False},
    )


def run_checks(world: dict) -> list[dict]:
    return [check_wifi(world), check_vpn(world), check_dns(world), check_printer(world)]
