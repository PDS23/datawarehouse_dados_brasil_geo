"""PAM (Produção Agrícola Municipal, IBGE/SIDRA tabela 5457) -> dim.cultura e tabular.ibge_pam.

SOB DEMANDA: o pipeline só carrega o que for pedido. Para trazer um produto, rode com --culturas; para
manter atualizado o que já está no banco, rode com --atualizar. Nada de carga completa por padrão.

Coleta direto da API do SIDRA (nenhum download manual), guarda o bruto, grava de forma idempotente
(reexecutar não duplica nem reescreve o que não mudou) e registra a execução em catalogo.cargas.

Uso (no contêiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/PAM/scripts/pam.py <o que carregar> [janela] [opções]

  O QUE CARREGAR (exatamente um):
    --culturas 40147,soja_em_grao   só estas (código SIDRA c782 ou slug). Série inteira, a menos que limite a janela
    --atualizar                     as culturas que JÁ estão em tabular.ibge_pam, nos últimos 3 anos publicados
    --todas-culturas                as 85 culturas (exige janela explícita ou --confirmar-carga-completa)
    --listar                        mostra as culturas do IBGE e o que já está carregado (não grava nada)

  JANELA (opcional): --desde 2020 | --ate 2023 | --anos 2023,2024
  OPÇÕES: --simular (transação desfeita: nada é gravado nem guardado) | --sem-bruto

Regras de gravação (ver ibge/PAM/config.yaml):
  - uma linha por município x cultura x ano, só quando alguma das 5 variáveis é > 0;
    ausência de linha = o IBGE informou zero ('-') ou nada ('...');
  - '-' vira 0, '...' vira NULL; valores como o IBGE devolve (a unidade real vai em unidade_*);
  - município que não existe em dim.municipios NÃO é descartado em silêncio: é contado e listado
    (a dimensão se atualiza com ibge/municipios/scripts/localidades.py);
  - cada cultura x ano é confirmada sozinha; interromper (docker stop) não deixa nada pela metade.
"""
import argparse
import re
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import islice
from pathlib import Path

import yaml

from dwlib import bruto, db, sidra
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # ibge/PAM
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
TABELA, CLASSIF = CFG["tabela"], CFG["classificacao"]
VARIAVEIS = CFG["variaveis"]                              # {"8331": "area_plantada_ha", ...}
_percentuais = set(VARIAVEIS) & set(CFG.get("variaveis_ignoradas", {}))
if _percentuais:                                          # trava: percentual não se coleta
    raise SystemExit(f"config.yaml pede variável percentual (ignorada de propósito): {sorted(_percentuais)}")
COLUNAS = ["id_municipio", "id_cultura", "ano", "area_plantada_ha", "area_colhida_ha", "quantidade_produzida",
           "unidade_quantidade", "rendimento_medio", "unidade_rendimento", "valor_producao_mil_reais",
           "unidade_valor", "id_fonte", "importado_em"]
CHAVE = ["id_municipio", "id_cultura", "ano"]
ATUALIZAR = [c for c in COLUNAS if c not in CHAVE]


def log(*a):
    print(*a, flush=True)


def unidades(cod, ano):
    """(unidade_quantidade, unidade_rendimento) para a cultura e o ano."""
    if cod in CFG["unidade_a_confirmar"]:
        return CFG["texto_a_confirmar"], CFG["texto_a_confirmar"]
    q = CFG["quebras_unidade"].get(cod)
    if q and ano <= q["ate"]:
        return q["quantidade"], q["rendimento"]
    return CFG["unidade_padrao"]["quantidade"], CFG["unidade_padrao"]["rendimento"]


def linhas_dim_cultura(cats, fonte):
    linhas, usados = [], set()
    for cod, nome in sorted(cats.items(), key=lambda kv: int(kv[0])):
        if cod == "0":  # Total: soma dos demais
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", sidra.normaliza(nome)).strip("_")
        if slug in usados:
            slug = f"{slug}_{cod}"
        usados.add(slug)
        linhas.append((int(cod), nome.replace("*", "").strip(), slug, "*" in nome, fonte, date.today()))
    return linhas


def registrar_equivalencia(conn):
    """Cultura nova da PAM entra como categoria da c782 na camada do SIDRA e aponta para si mesma em dim.cultura_equivalencia
    (ibge/sidra/sql/03_cultura_equivalencia.sql: onde a PAM tem a cultura, o id canônico é o próprio código c782)."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO dim.sidra_categoria (id_classificacao, codigo_sidra, nome, ordem) "
                    "SELECT 782, c.id_cultura, c.nome, row_number() OVER (ORDER BY c.id_cultura) FROM dim.cultura c WHERE c.id_cultura < 900000 "
                    "ON CONFLICT (id_classificacao, codigo_sidra) DO NOTHING")
        cur.execute("INSERT INTO dim.cultura_equivalencia (id_categoria, id_cultura) "
                    "SELECT g.id_categoria, c.id_cultura FROM dim.sidra_categoria g JOIN dim.cultura c ON c.id_cultura = g.codigo_sidra "
                    "WHERE g.id_classificacao = 782 AND c.id_cultura < 900000 ON CONFLICT (id_categoria) DO NOTHING")


def transformar(registros, cod, ano, municipios_dim, fonte, hoje):
    """Registros da API (um produto, um ano, todos os municípios) -> (linhas largas, somas, rejeitados)."""
    por_mun = defaultdict(dict)
    for r in registros:
        v = sidra.parse_valor(r["V"])
        if v is not None:
            por_mun[int(r["D1C"])][r["D2C"]] = v
    u_qtd, u_rend = unidades(cod, ano)
    uv = CFG["unidade_valor"]
    u_valor = uv["antiga"] if ano <= uv["ate"] else uv["atual"]
    linhas, somas, rejeitados = [], defaultdict(float), []
    for mun, vals in por_mun.items():
        for var, v in vals.items():
            somas[var] += v
        if not any(v > 0 for v in vals.values()):
            continue                                     # só zeros: ausência de linha
        if mun not in municipios_dim:
            rejeitados.append(mun)
            continue
        g = lambda var: vals.get(var)
        linhas.append((mun, int(cod), ano, g("8331"), g("216"), g("214"), u_qtd, g("112"), u_rend, g("215"), u_valor, fonte, hoje))
    return linhas, somas, rejeitados


def listar(conn, cats, fonte):
    carregado = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id_cultura, min(ano), max(ano), count(DISTINCT ano), count(*) FROM tabular.ibge_pam GROUP BY 1")
        for c, a, b, n, linhas in cur.fetchall():
            carregado[c] = (a, b, n, linhas)
    log(f"{len(cats) - 1} culturas na tabela {TABELA} do IBGE (código SIDRA c{CLASSIF}); '*' = nota de rodapé do IBGE")
    log(f"{'código':>7}  {'slug':<34} {'nome':<38} carregada")
    for cod, nome, slug, nota, *_ in linhas_dim_cultura(cats, fonte):
        c = carregado.get(cod)
        estado = f"{c[0]}-{c[1]} ({c[2]} anos, {c[3]:,} linhas)".replace(",", ".") if c else "-"
        log(f"{cod:>7}  {slug:<34} {nome + ('*' if nota else ''):<38} {estado}")
    log(f"\ncarregadas: {len(carregado)} de {len(cats) - 1}")


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="PAM (IBGE/SIDRA 5457) -> tabular.ibge_pam, sob demanda")
    ap.add_argument("--culturas", help="códigos SIDRA c782 ou slugs, separados por vírgula")
    ap.add_argument("--atualizar", action="store_true", help="as culturas já carregadas, nos últimos 3 anos publicados")
    ap.add_argument("--todas-culturas", action="store_true")
    ap.add_argument("--confirmar-carga-completa", action="store_true", help="necessário para --todas-culturas sem janela")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--desde", type=int)
    ap.add_argument("--ate", type=int)
    ap.add_argument("--anos")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--paralelo", type=int, default=1, metavar="N",
                    help="pedidos simultaneos ao SIDRA (1 a 4; padrao 1). Mais que isso arrisca bloqueio pela API")
    args = ap.parse_args()
    if not 1 <= args.paralelo <= 4:
        ap.error("--paralelo deve ficar entre 1 e 4 (o SIDRA nao documenta limite; acima disso pode bloquear o IP)")
    paralelo = args.paralelo

    escolhas = [bool(args.culturas), args.atualizar, args.todas_culturas, args.listar]
    if sum(escolhas) != 1:
        ap.error("informe exatamente um entre --culturas, --atualizar, --todas-culturas ou --listar "
                 "(use --listar para ver as culturas; nada é carregado por padrão)")
    janela_explicita = bool(args.anos or args.desde or args.ate)
    if args.todas_culturas and not janela_explicita and not args.confirmar_carga_completa:
        ap.error("--todas-culturas sem janela é a carga completa (85 culturas x 52 anos, ~3.200 pedidos, horas). "
                 "Informe --desde/--ate/--anos, ou --confirmar-carga-completa se for isso mesmo.")

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    cats = sidra.categorias(TABELA, CLASSIF, "216")
    if args.listar:
        listar(conn, cats, fonte)
        conn.close()
        return

    with Carga(conn, "ibge_pam", dataset="tabular.ibge_pam", parametros=vars(args), simular=args.simular) as carga:
        hoje = date.today()
        por_slug = {slug: str(c) for c, _, slug, *_ in linhas_dim_cultura(cats, fonte)}

        log(f"== 1) dim.cultura a partir das categorias do SIDRA (tabela {TABELA}, c{CLASSIF})")
        # Só toca em dim.cultura quando algo mudou: um upsert de linhas iguais ainda trava as linhas,
        # e duas cargas (ou uma simulação com transação aberta) ficariam esperando uma pela outra.
        with conn.cursor() as cur:
            cur.execute("SELECT id_cultura, nome, slug, nota_ibge, id_fonte FROM dim.cultura")
            existentes = {r[0]: tuple(r[1:]) for r in cur.fetchall()}
        mudou = [l for l in linhas_dim_cultura(cats, fonte) if existentes.get(l[0]) != tuple(l[1:5])]
        ins, atu = db.upsert(conn, "dim", "cultura", ["id_cultura", "nome", "slug", "nota_ibge", "id_fonte", "importado_em"],
                             mudou, chave=["id_cultura"], atualizar=["nome", "slug", "nota_ibge", "id_fonte", "importado_em"])
        log(f"  {len(cats) - 1} culturas no IBGE; dim.cultura: {ins} nova(s), {atu} atualizada(s)")
        registrar_equivalencia(conn)
        conn.commit() if not args.simular else None

        log("== 2) totais nacionais (dizem onde há dado e servem para validar a soma dos municípios)")
        nac = sidra.nacional(TABELA, list(VARIAVEIS), CLASSIF)
        anos_disp = sorted({int(a) for (_, a, _) in nac})
        anos_da_cultura = defaultdict(set)               # cultura -> {anos com algum valor nacional > 0}
        for (cod, ano, _var), v in nac.items():
            if cod != "0" and v is not None and v > 0:
                anos_da_cultura[cod].add(int(ano))
        log(f"  anos publicados: {anos_disp[0]} a {anos_disp[-1]}")

        if args.culturas:
            culturas = {por_slug.get(x.strip(), x.strip()) for x in args.culturas.split(",")}
            desconhecidas = culturas - set(cats)
            if desconhecidas:
                raise SystemExit(f"culturas desconhecidas: {sorted(desconhecidas)} (use --listar)")
        elif args.atualizar:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT id_cultura FROM tabular.ibge_pam")
                culturas = {str(r[0]) for r in cur.fetchall()}
            if not culturas:
                raise SystemExit("nada carregado ainda em tabular.ibge_pam: use --culturas para trazer um produto")
        else:
            culturas = set(cats) - {"0"}

        def anos_alvo(cod):
            todos = sorted(anos_da_cultura[cod])
            if args.anos:
                pedidos = {int(a) for a in args.anos.split(",")}
                return [a for a in todos if a in pedidos]
            if janela_explicita:
                return [a for a in todos if (not args.desde or a >= args.desde) and (not args.ate or a <= args.ate)]
            if args.atualizar:
                return [a for a in todos if a >= anos_disp[-1] - 2]
            return todos                                   # --culturas sem janela: série inteira

        plano = {cod: anos_alvo(cod) for cod in sorted(culturas, key=int)}
        total_pares = sum(len(v) for v in plano.values())
        nomes = {str(c): n for c, n, *_ in linhas_dim_cultura(cats, fonte)}
        log(f"  plano: {len(plano)} cultura(s), {total_pares} pedido(s) cultura x ano: "
            + ", ".join(f"{nomes.get(c, c)} ({v[0]}-{v[-1]})" for c, v in list(plano.items())[:6] if v)
            + (" ..." if len(plano) > 6 else ""))

        with conn.cursor() as cur:
            cur.execute("SELECT id_municipio FROM dim.municipios")
            municipios_dim = {r[0] for r in cur.fetchall()}

        log("== 3) coleta municipal (um pedido por cultura x ano, 5 variáveis) e carga")
        divergencias, rejeitados_total = [], defaultdict(int)
        feitos, t0, ultimo_ano = 0, time.time(), None
        for cod, anos in plano.items():
            if not anos:
                log(f"  {nomes.get(cod, cod)}: sem dado na janela pedida")
                continue
            bruto_cultura = []
            # Download em paralelo (so o pedido a API; a gravacao segue uma por vez, em ordem de ano, numa unica conexao).
            # No maximo `paralelo` pedidos em voo, para nao sobrecarregar o SIDRA.
            ex = ThreadPoolExecutor(max_workers=paralelo)
            busca = lambda a: sidra.valores(TABELA, "n6", list(VARIAVEIS), [str(a)], CLASSIF, cod)
            fila, restantes = deque(), iter(anos)
            for a in islice(restantes, paralelo):
                fila.append((a, ex.submit(busca, a)))
            try:
              while fila:
                ano, futuro = fila.popleft()
                regs = futuro.result()
                proximo = next(restantes, None)
                if proximo is not None:
                    fila.append((proximo, ex.submit(busca, proximo)))
                carga.lidas += len(regs)
                linhas, somas, rejeitados = transformar(regs, cod, ano, municipios_dim, fonte, hoje)
                ins, atu = db.upsert(conn, "tabular", "ibge_pam", COLUNAS, linhas, CHAVE, ATUALIZAR)
                carga.inseridas += ins
                carga.atualizadas += atu
                if rejeitados:
                    carga.rejeitadas += len(rejeitados)
                    for m in rejeitados:
                        rejeitados_total[m] += 1
                if not args.simular:
                    conn.commit()
                    if not args.sem_bruto:
                        bruto_cultura += [r for r in regs if r["V"] not in ("-", "...", "..", "X", "")]
                for var in CFG["validacao"]["variaveis_aditivas"]:
                    n = nac.get((cod, str(ano), var))
                    if n is not None and abs(somas.get(var, 0.0) - n) > max(1.0, CFG["validacao"]["tolerancia_relativa"] * abs(n)):
                        divergencias.append((cod, ano, var, somas.get(var, 0.0), n))
                feitos += 1
                if feitos % 25 == 0 or feitos == total_pares:
                    log(f"  {feitos}/{total_pares} ({time.time() - t0:.0f} s) {nomes.get(cod, cod)} {ano}: "
                        f"{carga.inseridas} novas, {carga.atualizadas} atualizadas")
            finally:
                ex.shutdown(wait=False, cancel_futures=True)   # interrupcao (SIGTERM): nao espera pedidos em voo
            if bruto_cultura:
                destino, n = bruto.salvar_jsonl_gz(
                    RAIZ / "bruto" / f"sidra_{TABELA}", f"pam_{cod}_{anos[0]}-{anos[-1]}", bruto_cultura,
                    fonte=f"https://apisidra.ibge.gov.br/values/t/{TABELA}/n6/all/v/{','.join(VARIAVEIS)}/p/<ano>/c{CLASSIF}/{cod}",
                    filtro="células '-' (zero) e '...' (sem dado) omitidas; as demais como a API devolveu",
                    extra={"cultura": cod, "nome": nomes.get(cod), "anos": anos})
                log(f"  bruto {destino.name}: {n} registros")

        log("== 4) conferência")
        if rejeitados_total:
            aviso = f"{len(rejeitados_total)} município(s) do PAM fora de dim.municipios (linhas com dado NÃO gravadas): {dict(list(rejeitados_total.items())[:10])}"
            log("  AVISO:", aviso)
            carga.avisos.append(aviso)
        if divergencias:
            divergencias.sort(key=lambda d: -abs(d[3] - d[4]) / max(abs(d[4]), 1))
            aviso = f"{len(divergencias)} divergência(s) entre a soma dos municípios e o total nacional (> {CFG['validacao']['tolerancia_relativa']:.1%})"
            log("  AVISO:", aviso)
            for cod, ano, var, soma, n in divergencias[:12]:
                log(f"    cultura {cod} ano {ano} v{var}: soma municipal {soma:,.0f} x nacional {n:,.0f}")
            carga.avisos.append(aviso)
        else:
            log("  soma dos municípios = total nacional em todas as combinações (variáveis aditivas)")

        if not args.simular and feitos:
            ultimo = max(max(v) for v in plano.values() if v)
            registrar_dataset(conn, "IBGE - PAM (Produção Agrícola Municipal, SIDRA 5457)", "tabular.ibge_pam", fonte,
                              ano_referencia=ultimo, licenca="Dados abertos do IBGE (citar a fonte); confirmar termos",
                              observacoes="Sob demanda: só as culturas pedidas (ver --listar). Largo: município x cultura x ano, só com valor > 0. "
                                          "A API rotula tudo como toneladas; unidade_quantidade/unidade_rendimento registram a unidade real "
                                          "quando conhecida. Ver ibge/PAM/LEIAME_PAM.md.")
            conn.commit()
        log(f"== fim: {carga.lidas} valores lidos; {carga.inseridas} linhas novas, {carga.atualizadas} atualizadas, "
            f"{carga.rejeitadas} rejeitadas; {time.time() - t0:.0f} s")
        if args.simular:
            conn.rollback()
            log("SIMULAÇÃO: nada foi gravado.")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
