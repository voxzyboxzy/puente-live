"""Language detection, entity extraction, polarity, and scenario matching.

Polarity is clause-local so contrastive reports survive translation:
"internet works but the VPN does not" and
"el internet funciona pero la VPN no" both mean internet=up, vpn=down.
"""

from __future__ import annotations

import re

ERROR_CODE = re.compile(r"\b([A-Za-z]{2,10}-ERR-\d{3,6})\b", re.I)

DEVICE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthinkpad-t14\b", re.I), "ThinkPad-T14"),
    (re.compile(r"\bcorp-laptop-(\d+)\b", re.I), "CORP-LAPTOP"),
    (re.compile(r"\bhp-laserjet-(m\d+)\b", re.I), "HP-LaserJet"),
]

ES_WORDS = {
    "el", "la", "los", "las", "que", "pero", "funciona", "funcionan", "está",
    "esta", "están", "estan", "páginas", "paginas", "impresora", "contraseña",
    "contrasena", "reinicié", "reinicie", "conexión", "conexion", "hola",
    "gracias", "fuera", "línea", "linea", "ya", "cliente", "inicio", "sesión",
    "sesion", "abierto", "empresa", "código", "codigo", "cargan", "carga",
    "conectado", "conectada", "cola", "impresión", "impresion", "volví",
    "volvi", "entrar", "también", "tambien", "ahora", "sigue", "túnel",
    "tunel", "equipo", "dispositivo", "con", "del", "una", "para", "por",
    "vacíe", "vacie", "caché", "cache", "reanudé", "reanude", "páginas",
    "sitios", "no",
}
# "no" is shared; it is not a language marker. Remove it if added above.
ES_WORDS.discard("no")

EN_WORDS = {
    "the", "my", "is", "but", "does", "not", "works", "working", "please",
    "websites", "website", "printer", "offline", "connected", "cannot",
    "reopen", "reopened", "device", "code", "on", "load", "loading", "flushed",
    "rejoined", "signed", "through", "company", "queue", "hand", "this",
    "now", "won't", "wont", "client", "while", "still", "computer", "error",
    "just", "tell", "give", "what", "disable", "turn", "open", "pages",
}

SERVICES: dict[str, re.Pattern[str]] = {
    "internet": re.compile(r"\binternet\b", re.I),
    "vpn": re.compile(r"\bvpn\b|\bt[uú]nel\b", re.I),
    "wifi": re.compile(r"(?<![\w-])wi-?fi\b", re.I),
    "dns": re.compile(r"\bdns\b|\bwebsites?\b|\bp[aá]ginas\b|\bsitios\b", re.I),
    "printer": re.compile(r"\bprinter\b|\bimpresora\b", re.I),
}

NEG = re.compile(
    r"\b(not|no|never|won't|wont|cannot|can't|doesn'?t|does not|isn'?t|is not|"
    r"offline|down|fails?|failed|without|sin|fuera|desconectad[oa]|ca[ií]d[oa]|"
    r"pausad[oa]|stale|vencid[oa]|won’t)\b",
    re.I,
)
POS = re.compile(
    r"\b(works|working|connected|conectad[oa]|online|funciona|funcionan|"
    r"carga|cargan|loading|loads|load|resolves|resolving|resuelve|"
    r"en\s+l[ií]nea|activo|activa|cleared|restored|restablecid[oa]|up)\b",
    re.I,
)

CLAUSE_SPLIT = re.compile(
    r"[.;!?]|\bpero\b|\bbut\b|\bhowever\b|\baunque\b|\bsin embargo\b|"
    r",?\s+\band\b|,?\s+\by\b",
    re.I,
)

FIXED = re.compile(
    r"(?i)\b(it works(?: now)?|works now|fixed|all set|websites load|"
    r"pages load|ya funciona|ya carga|ya cargan|ya imprime|"
    r"ya est[aá] en l[ií]nea|printer is online|vpn works)\b"
)
GENERIC_DONE = re.compile(
    r"(?i)\b(done|i did it|i did that|finished that|completed that|"
    r"listo|ya lo hice|hecho)\b"
)
HUMAN = re.compile(
    r"(?i)\b(technician|hand(?:\s+this)?\s+to|hand ?off|escalate|"
    r"t[eé]cnico|al t[eé]cnico|pasa el paquete|paquete al)\b"
)
GREETING = re.compile(
    r"(?i)^\s*(hi|hello|hey|good morning|good afternoon|hola|buenas|buenos d[ií]as)\s*[!.]*\s*$"
)


def detect_language(text: str) -> tuple[str, float]:
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", text.lower())
    if not tokens:
        return "und", 0.0
    es_hits = 0
    en_hits = 0
    for token in tokens:
        if any(ch in token for ch in "áéíóúüñ"):
            es_hits += 1
            continue
        if token in ES_WORDS:
            es_hits += 1
        if token in EN_WORDS:
            en_hits += 1
    if es_hits == 0 and en_hits == 0:
        return "und", 0.0
    if es_hits > en_hits:
        return "es", round(es_hits / len(tokens), 3)
    if en_hits > es_hits:
        return "en", round(en_hits / len(tokens), 3)
    return "und", round(max(es_hits, en_hits) / len(tokens), 3)


def extract_entities(text: str) -> dict:
    found: list[tuple[int, str, str]] = []
    for match in ERROR_CODE.finditer(text):
        found.append((match.start(), "code", match.group(1).upper()))
    for pattern, kind in DEVICE_RULES:
        for match in pattern.finditer(text):
            if kind == "ThinkPad-T14":
                token = "ThinkPad-T14"
            elif kind == "CORP-LAPTOP":
                token = f"CORP-LAPTOP-{match.group(1)}"
            else:
                token = f"HP-LaserJet-{match.group(1).upper()}"
            found.append((match.start(), "device", token))
    found.sort()
    codes: list[str] = []
    devices: list[str] = []
    for _pos, kind, token in found:
        if kind == "code" and token not in codes:
            codes.append(token)
        if kind == "device" and token not in devices:
            devices.append(token)
    return {"error_codes": codes, "devices": devices}


def _polarity_window(window: str) -> str | None:
    window = ERROR_CODE.sub(" ", window)
    negatives = list(NEG.finditer(window))
    positives = list(POS.finditer(window))
    if not negatives and not positives:
        return None
    if negatives and positives:
        for neg in negatives:
            for pos in positives:
                gap = pos.start() - neg.start()
                if 0 <= gap <= 24:
                    return "down"
        if positives[0].start() < negatives[0].start():
            return "up"
        return "down"
    if negatives:
        return "down"
    return "up"


def _mentions(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for service, pattern in SERVICES.items():
        for match in pattern.finditer(text):
            if re.match(r"-ERR-", text[match.end() : match.end() + 5], re.I):
                continue
            found.append((match.start(), match.end(), service))
    found.sort()
    filtered: list[tuple[int, int, str]] = []
    for start, end, service in found:
        if filtered and filtered[-1][2] == service and start - filtered[-1][1] < 12:
            continue
        filtered.append((start, end, service))
    return filtered


def _polarities_in_span(text: str) -> dict[str, str]:
    mentions = _mentions(text)
    result: dict[str, str] = {}
    if not mentions:
        return result
    for index, (start, end, service) in enumerate(mentions):
        prev_end = mentions[index - 1][1] if index else 0
        next_start = mentions[index + 1][0] if index + 1 < len(mentions) else len(text)
        left = 0 if index == 0 else (prev_end + start) // 2
        right = len(text) if index + 1 == len(mentions) else (end + next_start) // 2
        polarity = _polarity_window(text[left:right])
        if polarity and service not in result:
            result[service] = polarity
    return result


def infer_polarities(text: str) -> dict[str, str]:
    """Map service -> up|down. Contrastive clauses stay independent."""
    if not text:
        return {}
    parts = [part.strip() for part in CLAUSE_SPLIT.split(text) if part and part.strip()]
    if not parts:
        parts = [text]
    merged: dict[str, str] = {}
    for part in parts:
        for service, polarity in _polarities_in_span(part).items():
            merged[service] = polarity
    return merged


def clause_polarities(text: str) -> list[dict[str, str]]:
    parts = [part.strip() for part in CLAUSE_SPLIT.split(text) if part and part.strip()]
    if not parts:
        return []
    return [infer_polarities(part) for part in parts]


def polarities_contradict(text: str, reported: dict[str, str]) -> str | None:
    """Return a reason if text flips or drops a reported polarity."""
    if not reported:
        return None
    clauses = clause_polarities(text)
    for service, polarity in reported.items():
        seen = False
        for clause in clauses:
            if service not in clause:
                continue
            seen = True
            if clause[service] != polarity:
                return f"{service} flipped to {clause[service]}"
        if not seen:
            return f"{service} missing"
    return None


def split_facts(text: str) -> tuple[str, str]:
    match = re.search(r"(Incident facts:|Datos del incidente:)", text, re.I)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start() :]


def match_scenario(text: str, entities: dict | None = None) -> str | None:
    entities = entities or extract_entities(text)
    lowered = text.lower()
    scores = {"vpn_down": 0, "dns_failure": 0, "printer_offline": 0}
    if re.search(r"\bvpn\b|t[uú]nel|tunel|vpn-err", lowered):
        scores["vpn_down"] += 2
    if re.search(r"\bdns\b|website|p[aá]gina|pagina|sitios|no carg|won't load|wont load", lowered):
        scores["dns_failure"] += 2
    if re.search(r"printer|impresora|prt-err|print queue|cola de impres", lowered):
        scores["printer_offline"] += 2
    for code in entities.get("error_codes", []):
        if code.startswith("VPN"):
            scores["vpn_down"] += 3
        elif code.startswith("DNS"):
            scores["dns_failure"] += 3
        elif code.startswith("PRT"):
            scores["printer_offline"] += 3
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] == 0 or ranked[0] == ranked[1]:
        return None
    return max(scores, key=scores.get)


def is_greeting(text: str) -> bool:
    return bool(GREETING.match(text or ""))


def claims_fixed(text: str, phase: str) -> bool:
    if phase not in {"guide", "verify", "resolved", "handoff"}:
        return False
    if any(value == "down" for value in infer_polarities(text).values()):
        return False
    return bool(FIXED.search(text or ""))


def is_generic_done(text: str) -> bool:
    return bool(GENERIC_DONE.search(text or ""))


def requests_human(text: str) -> bool:
    return bool(HUMAN.search(text or ""))
