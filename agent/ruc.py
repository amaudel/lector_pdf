"""Validación estructural de RUC ecuatoriano (13 dígitos)."""
import re

_COEF_SOCIEDAD_PRIVADA = (4, 3, 2, 7, 6, 5, 4, 3, 2)   # 3er dígito = 9
_COEF_SOCIEDAD_PUBLICA = (3, 2, 7, 6, 5, 4, 3, 2)      # 3er dígito = 6


def _modulo11(digitos, coef, verificador):
    suma = sum(d * c for d, c in zip(digitos, coef))
    esperado = 11 - (suma % 11)
    if esperado == 11:
        esperado = 0
    return esperado != 10 and esperado == verificador


def _modulo10(digitos):
    suma = 0
    for i, d in enumerate(digitos):
        p = d * (2 if i % 2 == 0 else 1)
        suma += p - 9 if p > 9 else p
    return (10 - suma % 10) % 10


def validar_ruc(ruc) -> dict:
    """Devuelve {valido, tipo, motivo}. Es solo una señal informativa: muchos RUC reales
    de sociedades recientes (p. ej. 1793...) NO pasan el módulo 11 (17 de 37 en el maestro
    actual), así que un fallo no descarta un RUC; lo que lo respalda es la evidencia web."""
    ruc = re.sub(r"\D", "", str(ruc or ""))
    if len(ruc) != 13:
        return {"valido": False, "tipo": None, "motivo": "No tiene 13 dígitos"}
    d = [int(c) for c in ruc]
    prov = int(ruc[:2])
    if not (1 <= prov <= 24 or prov == 30):
        return {"valido": False, "tipo": None, "motivo": f"Código de provincia inválido ({ruc[:2]})"}
    tercero = d[2]
    if tercero == 9:
        ok = _modulo11(d[:9], _COEF_SOCIEDAD_PRIVADA, d[9]) and int(ruc[10:]) >= 1
        tipo = "SOCIEDAD_PRIVADA"
    elif tercero == 6:
        ok = _modulo11(d[:8], _COEF_SOCIEDAD_PUBLICA, d[8]) and int(ruc[9:]) >= 1
        tipo = "SOCIEDAD_PUBLICA"
    elif tercero < 6:
        ok = _modulo10(d[:9]) == d[9] and int(ruc[10:]) >= 1
        tipo = "PERSONA_NATURAL"
    else:
        return {"valido": False, "tipo": None, "motivo": f"Tercer dígito inválido ({tercero})"}
    return {"valido": ok, "tipo": tipo, "motivo": "OK" if ok else "Dígito verificador no coincide"}
