"""Cadastro de Empregadores do MTE (lista suja do trabalho escravo) -> tabular.mte_cadastro_empregadores, como ESPELHO VERSIONADO (sem geometria).

Baixa o CSV oficial do portal gov.br do MTE (Windows-1252, separador ';') e reconcilia igual às outras fontes (regras em dwlib/espelho.py com com_geometria=False): empregador novo
entra; alterado fecha a versão antiga e insere a nova; o que a edição nova não traz (o MTE retira os nomes ao fim de 2 anos) tem a versão fechada (nada é apagado); o que sumiu e
voltou idêntico tem a versão reaberta. "Está na lista hoje" = vigente_ate IS NULL.

DADO PESSOAL (mesma decisão do IBAMA): nome como a fonte publica; CPF de pessoa física NÃO é guardado, só o HMAC-SHA256 (dwlib/documento.py, mesma chave); CNPJ como vem.
Sem a chave do hash o pipeline para.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl mte/cadastro_empregadores/scripts/cadastro_empregadores.py [opções]

  OPÇÕES: --simular | --aceitar-queda | --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)
"""
import argparse
import csv
import hashlib
import io
import re
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from dwlib import db, documento, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # mte/cadastro_empregadores
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))

CAMPOS = ["chave_linha", "id_arquivo", "ano_acao_fiscal", "uf", "id_estado", "empregador", "cpf_cnpj", "tipo_doc_empregador", "doc_valido", "cpf_empregador_hash",
          "estabelecimento", "trabalhadores_envolvidos", "cnae", "decisao_administrativa", "decisao_administrativa_data", "inclusao_cadastro", "inclusao_cadastro_data"]
COLS_STAGE = {"id_arquivo": "integer", "ano_acao_fiscal": "smallint", "id_estado": "smallint", "doc_valido": "boolean", "trabalhadores_envolvidos": "integer",
              "decisao_administrativa_data": "date", "inclusao_cadastro_data": "date"}
COMPARAR = [c for c in CAMPOS if c not in ("chave_linha", "id_arquivo")]
DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def log(*a):
    print(*a, flush=True)


def texto(v):
    v = (v or "").strip()
    return v or None


def inteiro(v):
    v = texto(v)
    return int(v) if v and v.isdigit() else None


def datas(v):
    """Todas as datas DD/MM/AAAA de um texto (a inclusao pode ser uma lista de datas e periodos)."""
    out = []
    for d, m, a in DATA.findall(v or ""):
        try:
            out.append(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    return out


def baixar():
    r = http.sessao().get(CFG["url_csv"], timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    b = r.content
    if len(b) < CFG["tamanho_minimo_bytes"]:
        raise RuntimeError(f"arquivo com {len(b)} bytes (esperado mais de {CFG['tamanho_minimo_bytes']}): o MTE trocou o arquivo? NADA gravado")
    try:
        txt = b.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = b.decode("cp1252")
    return b, txt


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="MTE, Cadastro de Empregadores (lista suja) -> espelho versionado de tabular.mte_cadastro_empregadores")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    chave = documento.chave()
    if chave is None:
        raise RuntimeError("sem a chave do HMAC do CPF (DW_CHAVE_HASH_CPF ou ibama/embargos/segredo/chave_hash_cpf.key): NADA gravado")
    t0 = time.time()
    bruto, txt = baixar()
    hash_arq = hashlib.sha256(bruto).hexdigest()
    linhas = list(csv.reader(io.StringIO(txt), delimiter=";"))
    if [c.strip() for c in linhas[0]] != CFG["cabecalho_esperado"]:
        raise RuntimeError(f"cabecalho diferente do esperado (o MTE mudou o arquivo?): {linhas[0]}: NADA gravado")
    dados = [l for l in linhas[1:] if any(c.strip() for c in l)]
    if any(len(l) != len(CFG["cabecalho_esperado"]) for l in dados):
        raise RuntimeError("linha com numero de colunas diferente do cabecalho: NADA gravado")
    if len(dados) < CFG["linhas_minimas"]:
        raise RuntimeError(f"so {len(dados)} linhas (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
    log(f"== MTE, Cadastro de Empregadores: {len(dados)} linhas ({len(bruto) / 1e3:.0f} KB, sha256 {hash_arq[:16]}...)")

    registros, cpfs, cnpjs, outros, invalidos = [], 0, 0, 0, 0
    for l in dados:
        reg = {c: None for c in CAMPOS}
        reg.update(id_arquivo=inteiro(l[0]), ano_acao_fiscal=inteiro(l[1]), uf=texto(l[2]), empregador=texto(l[3]), cpf_cnpj=texto(l[4]), estabelecimento=texto(l[5]),
                   trabalhadores_envolvidos=inteiro(l[6]), cnae=texto(l[7]), decisao_administrativa=texto(l[8]), inclusao_cadastro=texto(l[9]))
        tipo, digitos, valido = documento.classificar(reg["cpf_cnpj"])
        reg["tipo_doc_empregador"], reg["doc_valido"] = tipo, valido
        if tipo == "CPF":
            reg["cpf_empregador_hash"], reg["cpf_cnpj"] = documento.hash_cpf(digitos, chave), None      # CPF de pessoa fisica NAO e guardado
            cpfs += 1
        elif tipo == "CNPJ":
            reg["cpf_cnpj"] = digitos
            cnpjs += 1
        elif tipo == "OUTRO":
            outros += 1
        invalidos += valido is False
        d = datas(reg["decisao_administrativa"])
        reg["decisao_administrativa_data"] = d[-1] if d else None
        i = datas(reg["inclusao_cadastro"])
        reg["inclusao_cadastro_data"] = max(i) if i else None
        registros.append(reg)
    grupos = {}
    for reg in registros:
        base = "|".join([reg["cpf_empregador_hash"] or reg["cpf_cnpj"] or "", str(reg["ano_acao_fiscal"] or ""), reg["estabelecimento"] or ""])
        grupos.setdefault(base, []).append(reg)
    repetidas = 0
    for base, regs in grupos.items():
        regs.sort(key=lambda r: (r["id_arquivo"] or 0))
        for k, reg in enumerate(regs):
            reg["chave_linha"] = base if k == 0 else f"{base}#{k + 1}"
        repetidas += len(regs) - 1
    log(f"  CPF (so hash): {cpfs} | CNPJ: {cnpjs} | texto/outro: {outros} | documentos com digito verificador errado: {invalidos} | chaves repetidas (ordinal): {repetidas}")

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    with Carga(conn, "mte_cadastro_empregadores", dataset=T, parametros={**vars(args), "sha256": hash_arq}, simular=args.simular) as carga:
        cur = conn.cursor()
        cols = ", ".join(f"{c} {COLS_STAGE.get(c, 'text')}" for c in CAMPOS)
        cur.execute(f"CREATE TEMP TABLE _stage ({cols}) ON COMMIT DROP")
        with cur.copy(f"COPY _stage ({', '.join(CAMPOS)}) FROM STDIN") as copia:
            for reg in registros:
                copia.write_row([reg[c] for c in CAMPOS])
        carga.lidas += len(registros)
        cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = upper(trim(s.uf))")
        cur.execute("SELECT count(*) FILTER (WHERE id_estado IS NULL) FROM _stage")
        sem_uf = cur.fetchone()[0]
        if sem_uf:
            carga.avisos.append(f"{sem_uf} registro(s) sem id_estado")
        cur.execute("CREATE UNIQUE INDEX ON _stage (chave_linha)")
        cur.execute("ANALYZE _stage")
        stats = espelho.reconciliar(conn, T, ["chave_linha"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                    aceitar_queda=args.aceitar_queda, simular=args.simular, com_geometria=False, log=log)
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
            return 0
        cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                    "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (T, "todas", "MTE (Cadastro de Empregadores)", CFG["url_csv"], "CSV oficial do portal gov.br do MTE", len(registros), len(registros), stats["novos"],
                     stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                     f"sha256 {hash_arq}; CPF so como hash; {invalidos} documentos com digito errado; {repetidas} chaves repetidas (ordinal)", stats["reabertos"]))
        registrar_dataset(conn, "MTE - Cadastro de Empregadores (lista suja do trabalho escravo)", T, fonte, ano_referencia=date.today().year, licenca=CFG["licenca"], tipo="tabular",
                          observacoes="CSV do portal gov.br do MTE, atualizado semestralmente. CPF so como HMAC (mesma chave do IBAMA). Ver mte/cadastro_empregadores/LEIAME_cadastro_empregadores.md.")
        conn.commit()
        carga.inseridas += stats["inseridos"]
        carga.atualizadas += stats["ausentes"]
        log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']} versoes inseridas, {stats['reabertos']} reabertas, {stats['ausentes']} fechadas por ausencia)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
