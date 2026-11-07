import pytest

from app.nlu import (
    detect_language,
    extract_entities,
    infer_polarities,
    match_scenario,
    polarities_contradict,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My internet works but the VPN does not.", {"internet": "up", "vpn": "down"}),
        ("el internet funciona pero la VPN no", {"internet": "up", "vpn": "down"}),
        ("Wi-Fi is connected but websites won't load.", {"wifi": "up", "dns": "down"}),
        ("El Wi-Fi está conectado pero las páginas no cargan.", {"wifi": "up", "dns": "down"}),
        ("The printer HP-LaserJet-M404 is offline.", {"printer": "down"}),
        ("La impresora está fuera de línea.", {"printer": "down"}),
        ("La VPN ya funciona.", {"vpn": "up"}),
    ],
)
def test_contrast_polarities(text, expected):
    assert infer_polarities(text) == expected


def test_error_code_is_not_a_vpn_mention():
    assert "vpn" not in infer_polarities("Error code VPN-ERR-4012 on ThinkPad-T14.")


def test_entities_keep_codes_and_devices():
    text = "Error vpn-err-4012 on device ThinkPad-T14 and CORP-LAPTOP-04. Printer HP-LaserJet-M404."
    found = extract_entities(text)
    assert found["error_codes"] == ["VPN-ERR-4012"]
    assert found["devices"] == ["ThinkPad-T14", "CORP-LAPTOP-04", "HP-LaserJet-M404"]


@pytest.mark.parametrize(
    "text,language",
    [
        ("My internet works but the VPN does not. Error code VPN-ERR-4012 on device ThinkPad-T14.", "en"),
        ("El internet funciona pero la VPN no. Código VPN-ERR-4012 en el equipo ThinkPad-T14.", "es"),
        ("Reinicié el cliente de VPN.", "es"),
        ("I reopened the Puente Tunnel client.", "en"),
        ("Vacié la caché DNS.", "es"),
        ("I rejoined CORP-WIFI.", "en"),
    ],
)
def test_language_detection(text, language):
    detected, confidence = detect_language(text)
    assert detected == language
    assert confidence > 0


def test_language_unknown_on_code_only():
    assert detect_language("VPN-ERR-4012")[0] == "und"


@pytest.mark.parametrize(
    "text,scenario",
    [
        ("My internet works but the VPN does not. VPN-ERR-4012", "vpn_down"),
        ("El internet funciona pero la VPN no.", "vpn_down"),
        ("Wi-Fi is connected but websites won't load. DNS-ERR-2201", "dns_failure"),
        ("La impresora está fuera de línea. PRT-ERR-3308", "printer_offline"),
        ("hello there", None),
    ],
)
def test_scenario_match(text, scenario):
    assert match_scenario(text) == scenario


def test_contradiction_detects_a_flip():
    reason = polarities_contradict(
        "The internet is not working, and the VPN is working.",
        {"internet": "up", "vpn": "down"},
    )
    assert reason
    assert (
        polarities_contradict(
            "The internet is working, and the VPN is not working.",
            {"internet": "up", "vpn": "down"},
        )
        is None
    )
