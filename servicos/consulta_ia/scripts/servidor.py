"""Servidor MCP de consulta do data warehouse: a IA do analista (Claude, ChatGPT, modelo local...) consulta o banco por aqui.

MCP (Model Context Protocol) é um protocolo aberto: o servidor declara FERRAMENTAS (funções com nome, descrição e parâmetros), PROMPTS e
RECURSOS; o cliente de IA lê essas declarações e decide sozinho quando chamar cada ferramenta. Por isso a docstring de cada função abaixo
não é comentário para humanos: é exatamente o texto que a IA lê para decidir. Escreva-a como instrução.

Transporte desta fase: stdio (o cliente inicia o processo e conversa pela entrada/saída padrão). Regra de ouro do stdio: NADA pode ser
escrito em stdout além do protocolo; avisos vão para stderr. A lógica fica em consulta.py (testável sem MCP); aqui só a vitrine.

  docker compose -f infra/docker-compose.stack.yml -f infra/docker-compose.consulta_ia.yml run --rm -T consulta_ia
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

import consulta  # noqa: E402

REGRAS = (consulta.PASTA / "regras_do_banco.md").read_text(encoding="utf-8")
SO_LEITURA = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

servidor = MCPServer(
    name="consulta-dw",
    title="Data warehouse GIS: dados públicos do Brasil",
    description="Consulta somente leitura, sem dado pessoal, a um PostGIS com fontes públicas versionadas (CAR, PRODES, DETER, IBGE...).",
    instructions=REGRAS,   # enviado na conexão: os clientes que suportam passam isto à IA antes de tudo
    version="0.1.0",
)


def _chamar(funcao, *args):
    try:
        return funcao(*args)
    except consulta.ErroConsulta as e:
        raise ToolError(str(e)) from e     # vira resultado de erro legível para a IA, que pode corrigir e tentar de novo


@servidor.tool(annotations=SO_LEITURA)
def listar_fontes() -> dict:
    """Lista os datasets do banco: fonte oficial, tabela, última coleta, primeira coleta registrada, cobertura e por quanto tempo as
    versões antigas são guardadas. Comece por aqui para saber o que existe e quão atual está."""
    return _chamar(consulta.listar_fontes)


@servidor.tool(annotations=SO_LEITURA)
def listar_tabelas(schema: str | None = None) -> dict:
    """Lista as tabelas e views que este acesso pode ler, com descrição, tamanho estimado e se são versionadas ou espaciais.
    schema (opcional): vetorial, tabular, dim, resultados ou catalogo."""
    return _chamar(consulta.listar_tabelas, schema)


@servidor.tool(annotations=SO_LEITURA)
def descrever_tabela(tabela: str) -> dict:
    """Descreve uma tabela antes de consultá-la: colunas com tipo e descrição (o que é e de onde vem), chaves e chaves estrangeiras
    (como juntar com dim.municipios, dim.estados...), índices (o GIST é o espacial), geometria e SRID, versionamento e colunas ocultas.
    tabela: no formato schema.nome, ex.: vetorial.sicar_imoveis."""
    return _chamar(consulta.descrever_tabela, tabela)


@servidor.tool(annotations=SO_LEITURA)
def ler_documentacao(nome: str | None = None) -> dict:
    """Lê a documentação do projeto: sem nome, lista os documentos; com nome (caminho ou parte dele, ex.: 'sicar', 'ibge/sidra',
    'ARQUITETURA'), devolve o texto. Use para metodologia, cobertura, limitações e decisões de cada fonte."""
    return _chamar(consulta.ler_documentacao, nome)


@servidor.tool(annotations=SO_LEITURA)
def consultar(sql: str, limite: int | None = None) -> dict:
    """Executa UM comando SELECT (ou WITH ... SELECT) somente leitura no PostGIS e devolve colunas, linhas, as fontes lidas com a data
    da última coleta (proveniencia) e avisos. Leia descrever_tabela antes. Regras: retrato atual = vigente_ate IS NULL; área em ha =
    ST_Area(geom::geography)/10000; junte território pelos códigos IBGE (id_municipio, id_estado); agregue no banco.
    Geometrias voltam resumidas (tipo, área, centroide). Consultas caras são recusadas com a explicação de como reescrever.
    limite: linhas devolvidas (padrão 50, máximo 500)."""
    return _chamar(consulta.consultar, sql, limite)


@servidor.prompt(title="Regras do banco")
def regras_do_banco() -> str:
    """Regras para consultar este banco: versões, geometria, códigos territoriais, cobertura e dado pessoal."""
    return REGRAS


@servidor.resource("dw://regras", name="regras_do_banco", title="Regras do banco", mime_type="text/markdown")
def recurso_regras() -> str:
    """As mesmas regras do prompt, como recurso legível."""
    return REGRAS


if __name__ == "__main__":
    servidor.run("stdio")
