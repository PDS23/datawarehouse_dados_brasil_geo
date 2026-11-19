"""Testes do servidor MCP de consulta: ferramentas, perguntas de referência, ataques que precisam ser barrados e o protocolo MCP de ponta a ponta.

  docker compose -f infra/docker-compose.stack.yml -f infra/docker-compose.consulta_ia.yml run --rm -T --entrypoint python consulta_ia \\
      servicos/consulta_ia/scripts/testar.py

Sai com código 1 se algum teste falhar. Não usa IA: testa o que o servidor entrega a qualquer IA.
"""
import asyncio
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consulta as c  # noqa: E402

RESULTADOS = []


def caso(nome, funcao):
    try:
        detalhe = funcao()
        RESULTADOS.append((True, nome, detalhe or ""))
    except Exception as e:  # noqa: BLE001
        RESULTADOS.append((False, nome, f"{type(e).__name__}: {e}"))


def deve_falhar(sql, trecho=None):
    def f():
        try:
            c.consultar(sql)
        except c.ErroConsulta as e:
            if trecho and trecho.lower() not in str(e).lower():
                raise AssertionError(f"falhou, mas sem '{trecho}': {e}") from e
            return f"barrado: {str(e)[:90]}"
        raise AssertionError("a consulta passou e devia ter sido barrada")
    return f


# --- ferramentas ----------------------------------------------------------------------------------------------------------------------
def t_listar_fontes():
    r = c.listar_fontes()["datasets"]
    assert len(r) >= 20, len(r)
    sicar = next(d for d in r if d.get("tabela") == "vetorial.sicar_imoveis")
    assert "ultima_coleta" in sicar and "retencao" in sicar, sicar
    return f"{len(r)} datasets; SICAR coletado em {sicar['ultima_coleta'][:10]}"


def t_listar_tabelas():
    r = c.listar_tabelas()["tabelas"]
    assert len(r) >= 30 and not any(t["tabela"].startswith("analises.") for t in r)
    return f"{len(r)} tabelas/views"


def t_descrever_pessoal():
    r = c.descrever_tabela("vetorial.ibama_embargos")
    ocultas = r["colunas_ocultas"]["colunas"]
    visiveis = {col["coluna"] for col in r["colunas"]}
    assert "nome_embargado" in ocultas and "cpf_cnpj_embargado" in ocultas and not visiveis & set(ocultas)
    return f"{len(visiveis)} visíveis, {len(ocultas)} ocultas"


def t_descrever_sicar():
    r = c.descrever_tabela("vetorial.sicar_imoveis")
    assert r["versionada"] and r["geometria"] and r["geometria"][0]["srid"] == 4674
    assert any(i["metodo"] == "gist" for i in r["indices"]), "sem índice espacial"
    return f"{len(r['colunas'])} colunas, {len(r['chaves'])} chaves, {len(r['indices'])} índices"


def t_doc_lista():
    docs = c.ler_documentacao()["documentos"]
    assert not any(d.startswith(("projetos/", "infra/tailscale", "infra/colab")) or "pg_hba" in d for d in docs), docs
    assert any("sicar" in d for d in docs)
    return f"{len(docs)} documentos"


def t_doc_sicar():
    r = c.ler_documentacao("sicar_imoveis")
    assert len(r["texto"]) > 500
    return r["documento"]


def t_doc_bloqueada():
    for nome in ("projetos", "pg_hba", "../.env"):
        try:
            c.ler_documentacao(nome)
        except c.ErroConsulta:
            continue
        raise AssertionError(f"'{nome}' devia ser barrado")
    return "projetos/, pg_hba e .env barrados"


def t_timeout():
    original = c.LIM["tempo_maximo_s"]
    c.LIM["tempo_maximo_s"] = 2
    try:
        return deve_falhar("SELECT pg_sleep(5)", "cancelada")()
    finally:
        c.LIM["tempo_maximo_s"] = original


def t_set_config_nao_vaza():
    c.consultar("SELECT set_config('statement_timeout', '0', false) AS x")
    r = c.consultar("SELECT current_setting('statement_timeout') AS t, current_setting('transaction_read_only') AS ro")
    assert r["linhas"][0][0] in (f"{c.LIM['tempo_maximo_s']}s", "1min") and r["linhas"][0][1] == "on", r["linhas"]
    return f"depois do set_config: {r['linhas'][0]}"


# --- perguntas de referência ----------------------------------------------------------------------------------------------------------
def pergunta(p):
    def f():
        r = c.consultar(p["sql"])
        v = p.get("verificacoes", {})
        primeira = r["linhas"][0][0] if r["linhas"] else None
        if "colunas" in v:
            assert r["colunas"] == v["colunas"], r["colunas"]
        if "linhas_min" in v:
            assert r["n_linhas"] >= v["linhas_min"], r["n_linhas"]
        if "valor_min" in v:
            assert primeira is not None and primeira >= v["valor_min"], primeira
        if "valor_max" in v:
            assert primeira <= v["valor_max"], primeira
        if "aviso" in v:
            assert any(v["aviso"] in a for a in r["avisos"]), r["avisos"]
        if v.get("sem_aviso"):
            assert not r["avisos"], r["avisos"]
        if "tabela_lida" in v:
            assert any(x["tabela"] == v["tabela_lida"] for x in r["proveniencia"]), r["proveniencia"]
        if "geometria_resumida" in v:
            g = r["linhas"][0][r["colunas"].index(v["geometria_resumida"])]
            assert isinstance(g, dict) and "area_ha" in g, g
        return f"{r['linhas'][0] if r['linhas'] else '-'} em {r['tempo_ms']} ms"
    return f


# --- protocolo MCP (o mesmo caminho que o Claude Desktop usa) ----------------------------------------------------------------------------
def t_protocolo():
    from mcp import Client, StdioServerParameters

    async def rodar():
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("servidor.py"))], env=dict(os.environ))
        async with Client(params) as cliente:
            ferramentas = sorted(t.name for t in (await cliente.list_tools()).tools)
            assert ferramentas == ["consultar", "descrever_tabela", "ler_documentacao", "listar_fontes", "listar_tabelas"], ferramentas
            ok = await cliente.call_tool("consultar", {"sql": "SELECT count(*) AS n FROM dim.estados"})
            assert not ok.is_error and "27" in str(ok.content), ok
            erro = await cliente.call_tool("consultar", {"sql": "SELECT nome_embargado FROM vetorial.ibama_embargos"})
            assert erro.is_error and "permissão" in str(erro.content), erro
            prompts = [p.name for p in (await cliente.list_prompts()).prompts]
            assert "regras_do_banco" in prompts, prompts
            return f"{len(ferramentas)} ferramentas, prompt e erro legível pelo protocolo"
    return asyncio.run(rodar())


def main():
    caso("listar_fontes", t_listar_fontes)
    caso("listar_tabelas (sem o schema analises)", t_listar_tabelas)
    caso("descrever_tabela oculta dado pessoal", t_descrever_pessoal)
    caso("descrever_tabela do SICAR", t_descrever_sicar)
    caso("ler_documentacao: lista sem material interno", t_doc_lista)
    caso("ler_documentacao: LEIAME do SICAR", t_doc_sicar)
    caso("ler_documentacao: caminhos proibidos", t_doc_bloqueada)

    ataques = [
        ("coluna pessoal", "SELECT nome_embargado FROM vetorial.ibama_embargos LIMIT 1", "permissão"),
        ("SELECT * em tabela com dado pessoal", "SELECT * FROM vetorial.icmbio_areas_embargadas LIMIT 1", "permissão"),
        ("hash de CPF", "SELECT cpf_empregador_hash FROM tabular.mte_cadastro_empregadores", "permissão"),
        ("escrita", "DELETE FROM dim.estados", None),
        ("DDL", "CREATE TABLE vetorial.x (a int)", None),
        ("dois comandos", "SELECT 1; DROP TABLE dim.estados", None),
        ("fechar a subconsulta e emendar comando", "SELECT 1) AS _x; SET statement_timeout = 0; SELECT (1", None),
        ("schema analises", "SELECT count(*) FROM analises.desmatamento_imovel", None),
        ("ler arquivo do servidor", "SELECT pg_read_file('/etc/passwd')", None),
        ("cruzamento de uma UF inteira (custo)",
         "SELECT sum(ST_Area(ST_Intersection(s.geom, p.geom)::geography)) FROM vetorial.sicar_imoveis s "
         "JOIN vetorial.prodes_desmatamento p ON ST_Intersects(s.geom, p.geom) "
         "WHERE s.vigente_ate IS NULL AND p.vigente_ate IS NULL AND s.id_estado = 51", "custo"),
    ]
    for nome, sql_, trecho in ataques:
        caso(f"barra: {nome}", deve_falhar(sql_, trecho))
    caso("barra: consulta longa (tempo)", t_timeout)
    caso("set_config não sobrevive à chamada", t_set_config_nao_vaza)

    refs = yaml.safe_load((c.PASTA / "perguntas_referencia.yaml").read_text(encoding="utf-8"))["perguntas"]
    for p in refs:
        caso(f"ref: {p['pergunta']}", pergunta(p))
    caso("protocolo MCP por stdio", t_protocolo)

    falhas = [r for r in RESULTADOS if not r[0]]
    for ok, nome, detalhe in RESULTADOS:
        print(f"{'ok   ' if ok else 'FALHA'} {nome}: {detalhe}")
    print(f"\n{len(RESULTADOS) - len(falhas)} de {len(RESULTADOS)} passaram")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
