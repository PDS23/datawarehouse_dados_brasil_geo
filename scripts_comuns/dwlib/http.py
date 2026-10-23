"""Sessão HTTP com retentativas; opção de TLS legado para servidores que só falam TLS 1.2 com cifras antigas e opção de
certificado intermediário extra para servidores que não o enviam na conexão."""
import ssl
from pathlib import Path

import certifi

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = "data-warehouse-gis/1.0 (coleta automatizada de dados abertos)"


class _AdaptadorLegado(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()          # verificação do certificado CONTINUA ligada
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")        # só afrouxa as cifras aceitas (RSA sem sigilo de encaminhamento)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


CERTS = Path(__file__).resolve().parent / "certs"      # intermediárias PÚBLICAS de CAs (não são segredo), uma por servidor que precisa


class _AdaptadorCAExtra(HTTPAdapter):
    """Verifica o certificado normalmente (CAs do certifi) e acrescenta uma intermediária que o servidor não envia.
    Navegadores e o Windows buscam a intermediária sozinhos (campo AIA do certificado); o Python não."""
    def __init__(self, *args, ca_extra, **kwargs):
        self._ca_extra = str(ca_extra)
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.load_verify_locations(cafile=self._ca_extra)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def sessao(tls_legado=False, ca_extra=None):
    """requests.Session com retentativas em 429/5xx. tls_legado=True: só para hosts que recusam o handshake padrão
    (ex.: geoserver.car.gov.br aceita só TLS 1.2 com AES-GCM sem ECDHE; o OpenSSL 3 do contêiner recusa por padrão).
    Use apenas para DADOS PÚBLICOS: a conexão fica mais fraca que o padrão, o certificado segue verificado.
    ca_extra="arquivo.pem" (em dwlib/certs/): servidor que NÃO envia o certificado intermediário (erro "unable to get local issuer
    certificate", ex.: geoserver.funai.gov.br); a verificação continua ligada, só ganha a intermediária que faltava."""
    s = requests.Session()
    retentativas = Retry(total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "HEAD"))
    if ca_extra:
        adaptador = _AdaptadorCAExtra(max_retries=retentativas, ca_extra=CERTS / ca_extra)
    else:
        adaptador = (_AdaptadorLegado if tls_legado else HTTPAdapter)(max_retries=retentativas)
    s.mount("https://", adaptador)
    s.headers["User-Agent"] = UA
    return s
