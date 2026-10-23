"""Cliente mínimo da API de valores do SIDRA (IBGE), sem autenticação.

Usa SÓ o host apisidra.ibge.gov.br: o host de metadados (servicodados.ibge.gov.br) serve um
certificado sem o intermediário e quebra a verificação TLS em clientes Python.

Padrão da URL:
  https://apisidra.ibge.gov.br/values/t/<tabela>/n<nível>/<territórios>/v/<variáveis>/p/<períodos>/c<classif>/<categorias>

A API recusa pedidos com mais de 50.000 valores ("excedeu o limite"). `valores` divide o pedido
sozinha (variáveis, depois períodos, depois categorias) e junta o resultado.
"""
import json
import threading
import unicodedata

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL_VALORES = "https://apisidra.ibge.gov.br/values"
_local = threading.local()      # uma Session por thread (a Session compartilhada nao e garantida como segura)


class LimiteExcedido(Exception):
    """A API recusou o pedido por passar de 50.000 valores."""


def sessao():
    if getattr(_local, "sessao", None) is None:
        s = requests.Session()
        retentativas = Retry(total=5, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                             allowed_methods=("GET",))
        s.mount("https://", HTTPAdapter(max_retries=retentativas))
        s.headers["User-Agent"] = "data-warehouse-gis/1.0 (coleta automatizada de dados abertos do IBGE)"
        _local.sessao = s
    return _local.sessao


def _get(caminho):
    r = sessao().get(f"{URL_VALORES}/{caminho}", timeout=180)
    if r.status_code == 400 and "excedeu o limite" in r.text:
        raise LimiteExcedido(r.text.strip())
    if r.status_code >= 400:
        raise RuntimeError(f"SIDRA HTTP {r.status_code} em {caminho}: {r.text[:200]}")
    return json.loads(r.content)  # bytes: a API responde em UTF-8


def _lista(x):
    return [str(i) for i in (x if isinstance(x, (list, tuple)) else [x])]


def valores(tabela, nivel, variaveis, periodos, classificacao=None, categorias="all", territorios="all"):
    """Registros da API (sem a linha de cabeçalho). Campos úteis: D1C (território), D2C (variável),
    D3C (período), D4C (categoria), MN (unidade declarada), V (valor, texto)."""
    variaveis, periodos, categorias = _lista(variaveis), _lista(periodos), _lista(categorias)
    caminho = f"t/{tabela}/{nivel}/{territorios}/v/{','.join(variaveis)}/p/{','.join(periodos)}"
    if classificacao is not None:
        caminho += f"/c{classificacao}/{','.join(categorias)}"
    try:
        return _get(caminho)[1:]
    except LimiteExcedido:
        if len(variaveis) > 1:
            meio = len(variaveis) // 2
            return (valores(tabela, nivel, variaveis[:meio], periodos, classificacao, categorias, territorios)
                    + valores(tabela, nivel, variaveis[meio:], periodos, classificacao, categorias, territorios))
        if len(periodos) > 1 and periodos != ["all"]:
            meio = len(periodos) // 2
            return (valores(tabela, nivel, variaveis, periodos[:meio], classificacao, categorias, territorios)
                    + valores(tabela, nivel, variaveis, periodos[meio:], classificacao, categorias, territorios))
        if len(categorias) > 1 and categorias != ["all"]:
            meio = len(categorias) // 2
            return (valores(tabela, nivel, variaveis, periodos, classificacao, categorias[:meio], territorios)
                    + valores(tabela, nivel, variaveis, periodos, classificacao, categorias[meio:], territorios))
        raise


def valores_cubo(tabela, nivel, variaveis, periodos, classificacoes, territorios="all"):
    """Como `valores`, mas para tabelas com VÁRIAS classificações (ex.: censo agropecuário).

    classificacoes: {"227": ["4961"], "220": ["111543", "111544", ...], "829": ["46302"]} (códigos explícitos;
    "all" também vale, mas não pode ser dividido). Se passar de 50.000 valores, divide ao meio a dimensão
    com mais itens e junta o resultado. Campos úteis: D1C (território), D2C (variável), D3C (período) e
    D4C... (uma por classificação, na ordem em que a tabela as declara; confira no chamador)."""
    variaveis, periodos = _lista(variaveis), _lista(periodos)
    classificacoes = {str(c): _lista(cats) for c, cats in classificacoes.items()}
    caminho = f"t/{tabela}/{nivel}/{territorios}/v/{','.join(variaveis)}/p/{','.join(periodos)}"
    for c, cats in classificacoes.items():
        caminho += f"/c{c}/{','.join(cats)}"
    try:
        return _get(caminho)[1:]
    except LimiteExcedido:
        dims = [("v", variaveis)] + [("p", periodos)] + [(c, cats) for c, cats in classificacoes.items()]
        dims = [(n, itens) for n, itens in dims if len(itens) > 1 and itens != ["all"]]
        if not dims:
            raise
        nome, itens = max(dims, key=lambda d: len(d[1]))
        meio = len(itens) // 2
        resultado = []
        for parte in (itens[:meio], itens[meio:]):
            v, p, cl = variaveis, periodos, dict(classificacoes)
            if nome == "v":
                v = parte
            elif nome == "p":
                p = parte
            else:
                cl[nome] = parte
            resultado += valores_cubo(tabela, nivel, v, p, cl, territorios)
        return resultado


def cabecalho(tabela, variavel, periodo, classificacoes):
    """Linha de cabeçalho da API: nomes das dimensões (D4N = nome da 1ª classificação pedida, D5N = da 2ª...), nome do
    nível, da variável e do período. Pedido mínimo: Brasil, 1 variável, 1 período, 1 categoria por classificação
    (classificacoes: {codigo: primeira_categoria})."""
    caminho = f"t/{tabela}/n1/all/v/{variavel}/p/{periodo}"
    for c, cat in classificacoes.items():
        caminho += f"/c{c}/{cat}"
    return _get(caminho)[0]


def parse_valor(v):
    """Texto da API -> float ou None.  '-' = zero (o fenômeno existe e vale zero);
    '...', '..', 'X' e vazio = sem dado/inibido (None)."""
    v = (v or "").strip()
    if v == "-":
        return 0.0
    if v in ("", "...", "..", "X"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def normaliza(texto):
    """minúsculas, sem acento, sem asterisco de nota e sem espaços nas pontas"""
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return s.replace("*", "").strip().lower()


def categorias(tabela, classificacao, variavel):
    """{codigo: nome} das categorias de uma classificação (ex.: produtos da PAM, c782)."""
    registros = valores(tabela, "n1", [variavel], ["all"], classificacao, "all")
    return {r["D4C"]: r["D4N"] for r in registros}


def nacional(tabela, variaveis, classificacao):
    """Totais do Brasil para todos os períodos e categorias: {(categoria, período, variável): float|None}.
    Serve para saber quais combinações têm dado e para validar a soma dos municípios."""
    registros = valores(tabela, "n1", variaveis, ["all"], classificacao, "all")
    return {(r["D4C"], r["D3C"], r["D2C"]): parse_valor(r["V"]) for r in registros}
