"""CPF/CNPJ de autuados e embargados: limpeza e hash (LGPD), comum a todas as fontes que trazem documento.

Regra do projeto (IBAMA, ICMBio, ...): o dado entra como a fonte publica, EXCETO o CPF de pessoa fisica, que nunca e guardado: vira HMAC-SHA256 dos 11 digitos,
com uma chave fora do banco e do git. A mesma chave vale para todas as fontes, entao um CPF consultado casa com o mesmo hash em qualquer tabela.
CNPJ (pessoa juridica) e texto que nao e documento entram como vem.

A chave: variavel DW_CHAVE_HASH_CPF, ou o arquivo ibama/embargos/segredo/chave_hash_cpf.key (fora do git e do Drive). Nunca e impressa nem registrada.
"""
import hashlib
import hmac
import os
import re
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[2]
ARQUIVO_CHAVE = RAIZ_REPO / "ibama" / "embargos" / "segredo" / "chave_hash_cpf.key"


def chave():
    """Bytes da chave do HMAC, ou None se nao houver (variavel ou arquivo)."""
    env = os.environ.get("DW_CHAVE_HASH_CPF")
    if env:
        return env.encode("utf-8")
    if ARQUIVO_CHAVE.exists():
        return ARQUIVO_CHAVE.read_text(encoding="utf-8").strip().encode("utf-8")
    return None


def hash_cpf(cpf, chave_bytes):
    """HMAC-SHA256 (hex) dos 11 digitos do CPF (so digitos; com zeros a esquerda)."""
    d = re.sub(r"\D", "", cpf).zfill(11)
    if len(d) != 11:
        raise ValueError("CPF deve ter 11 digitos")
    return hmac.new(chave_bytes, d.encode("ascii"), hashlib.sha256).hexdigest()


def cpf_valido(d):
    """d: 11 digitos. Confere os dois digitos verificadores (e recusa sequencias repetidas)."""
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if int(d[n]) != (soma * 10 % 11) % 10:
            return False
    return True


def cnpj_valido(d):
    """d: 14 digitos. Confere os dois digitos verificadores."""
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        r = sum(int(d[i]) * pesos[i] for i in range(n)) % 11
        if int(d[n]) != (0 if r < 2 else 11 - r):
            return False
    return True


FORMATADO = re.compile(r"^[\d.\-/\s]+$")


def classificar(valor):
    """Interpreta o campo de documento de uma fonte. Retorna (tipo, digitos, valido):
      tipo   'CPF' | 'CNPJ' | 'OUTRO' | None (vazio ou placeholder como '0' e '.')
      digitos CPF (11, com zeros a esquerda) ou CNPJ (14); para 'OUTRO' devolve None (o texto original e mantido por quem chama)
      valido  True se os digitos verificadores conferem (False: provavel erro de digitacao da fonte)
    Zeros a esquerda perdidos (planilha) sao repostos: um numero de ate 11 digitos e tratado como CPF; de 12 a 14 (ou 15 com um zero sobrando), como CNPJ.
    CPF invalido continua sendo tratado como CPF (e portanto nunca guardado em claro): na duvida, protege-se."""
    v = (valor or "").strip()
    if not v or v in (".", "-", "0"):
        return None, None, None
    if not FORMATADO.match(v):
        return "OUTRO", None, None                               # texto livre ('DESCONHECIDO', '201458X2787'): entra como vem
    d = re.sub(r"\D", "", v)
    n = d.lstrip("0")
    if not n:
        return None, None, None
    if len(d) >= 12:                                             # so pode ser CNPJ (um zero a mais ou a menos nas pontas e reposto)
        if len(n) > 14:
            return "OUTRO", None, None
        c = n.zfill(14)
        return "CNPJ", c, cnpj_valido(c)
    c11, c14 = d.zfill(11), d.zfill(14)
    if cpf_valido(c11):
        return "CPF", c11, True
    if cnpj_valido(c14):
        return "CNPJ", c14, True
    return "CPF", c11, False                                     # nem CPF nem CNPJ valido: trata como CPF (protege) e marca invalido
