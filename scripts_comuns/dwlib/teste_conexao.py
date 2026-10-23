"""Teste de fumaça do contêiner etl: conecta como o papel de serviço e mostra o que ele pode e não pode.
   docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl scripts_comuns/dwlib/teste_conexao.py
"""
import psycopg

from dwlib import db

conn = db.conectar()
with conn.cursor() as cur:
    cur.execute("SELECT current_user, current_database(), inet_server_addr()::text, version()")
    usuario, banco, ip, versao = cur.fetchone()
    print(f"conectado: usuario={usuario} banco={banco} servidor={ip}\n{versao.split(',')[0]}")
    cur.execute("SELECT (SELECT count(*) FROM dim.municipios), (SELECT count(*) FROM dim.estados), "
                "(SELECT count(*) FROM catalogo.datasets)")
    print("leitura (dim.municipios, dim.estados, catalogo.datasets):", cur.fetchone())
for rotulo, sql_ in (("ler o SICAR (o ETL nao precisa)", "SELECT count(*) FROM vetorial.sicar_imoveis"),
                     ("DROP de tabela", "DROP TABLE dim.municipios"),
                     ("DELETE em dim.municipios", "DELETE FROM dim.municipios WHERE false"),
                     ("UPDATE no SICAR", "UPDATE vetorial.sicar_imoveis SET id_estado = id_estado WHERE false"),
                     ("CREATE TABLE em tabular", "CREATE TABLE tabular._teste (x int)"),
                     ("ler pg_authid (hashes)", "SELECT rolpassword FROM pg_authid LIMIT 1")):
    try:
        with conn.cursor() as cur:
            cur.execute(sql_)
        print(f"  {rotulo}: PERMITIDO (inesperado)")
    except psycopg.errors.InsufficientPrivilege as e:
        print(f"  {rotulo}: negado ({str(e).splitlines()[0][:60]})")
    conn.rollback()
conn.close()
