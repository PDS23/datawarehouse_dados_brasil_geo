"""Sessão HTTP com retentativas; opção de TLS legado para servidores que só falam TLS 1.2 com cifras antigas."""
import ssl

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


def sessao(tls_legado=False):
    """requests.Session com retentativas em 429/5xx. tls_legado=True: só para hosts que recusam o handshake padrão
    (ex.: geoserver.car.gov.br aceita só TLS 1.2 com AES-GCM sem ECDHE; o OpenSSL 3 do contêiner recusa por padrão).
    Use apenas para DADOS PÚBLICOS: a conexão fica mais fraca que o padrão, o certificado segue verificado."""
    s = requests.Session()
    retentativas = Retry(total=5, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "HEAD"))
    adaptador = (_AdaptadorLegado if tls_legado else HTTPAdapter)(max_retries=retentativas)
    s.mount("https://", adaptador)
    s.headers["User-Agent"] = UA
    return s
