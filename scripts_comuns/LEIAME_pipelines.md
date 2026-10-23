# Coleta automatizada (pipelines)

Diretriz do projeto (2026-10-14): dado novo entra por **pipeline que coleta direto na fonte e grava no
PostGIS**, não por download manual + script avulso. Assim qualquer pessoa reproduz o banco e a atualização
é rodar de novo o mesmo comando.

## Peças

| Onde | O que é |
|---|---|
| `scripts_comuns/dwlib/` | biblioteca comum: `db` (conexão e upsert idempotente), `sidra` (API do SIDRA/IBGE), `bruto` (guarda o bruto com data e hash), `catalogo` (registro de cada carga) |
| `<fonte>/<tema>/scripts/` | o pipeline daquela fonte (ex.: `ibge/PAM/scripts/pam.py`) |
| `<fonte>/<tema>/sql/` | a DDL das tabelas que ele alimenta (rodada por administrador) |
| `<fonte>/<tema>/config.yaml` | o que muda sem mexer no código (tabela, variáveis, regras de unidade) |
| `<fonte>/<tema>/bruto/` | o dado coletado (`.jsonl.gz` + manifesto); **fora do git** |
| `infra/docker-compose.etl.yml`, `infra/etl/` | o contêiner `etl` (Python 3.13 e as bibliotecas) |
| `infra/postgres/etl_base.sql`, `infra/scripts/criar_papel_etl.ps1` | o papel de serviço `etl` e o registro de cargas |

## Como rodar (a partir de `infra/`)

```powershell
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/PAM/scripts/pam.py --desde 2023
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/municipios/scripts/localidades.py --geometria
```

Todo pipeline aceita `--simular` (faz tudo numa transação desfeita: não grava nada). Use sempre antes
de uma carga nova. **Nunca use `--remove-orphans`** nesse compose: o contêiner `dw-tailscale` é de outro
arquivo e seria removido (defina `COMPOSE_IGNORE_ORPHANS=true` para silenciar o aviso).

## Montagem do ambiente do zero (para quem clona o repositório)

1. Subir a stack: `docker compose -f docker-compose.stack.yml up -d` (precisa de `infra/.env`; modelo em `.env.example`).
2. Criar o papel de serviço: `Get-Content infra\postgres\etl_base.sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1`
   e `.\infra\scripts\criar_papel_etl.ps1` (gera a senha aleatória em `infra\.env`, sem exibi-la).
3. Criar as tabelas do pipeline (`sql/`) e rodar o pipeline.

## Regras de um pipeline (o que `pam.py` e `localidades.py` seguem)

- **Idempotente:** reexecutar não duplica nem reescreve o que não mudou (`db.upsert`).
- **Nada se perde em silêncio:** o que a carga rejeita (ex.: município fora da dimensão) é contado, listado
  e vai para `catalogo.cargas.mensagem`.
- **Valores como a fonte entrega.** Quando a fonte rotula errado (a API do PAM diz "toneladas" para tudo),
  não se corrige o número: registra-se a unidade real em coluna própria, com a evidência na configuração.
- **Menor privilégio:** o papel `etl` só tem INSERT/UPDATE nas tabelas que alimenta. Não cria, não apaga,
  não lê o que não precisa (ex.: não lê o SICAR).
- **Auditável:** cada execução fica em `catalogo.cargas` (parâmetros, linhas lidas/inseridas/atualizadas/
  rejeitadas, status) e o dataset em `catalogo.datasets`; o bruto guarda a data da coleta e o SHA-256.
- **Validação embutida:** cada pipeline confere o que carregou (ex.: soma dos municípios contra o total
  nacional) e há um teste de regressão contra uma coleta manual conhecida (`ibge/PAM/scripts/validar_mate_rs.py`).
- **Só `apisidra.ibge.gov.br`** para a API do IBGE: o host `servicodados.ibge.gov.br` serve um certificado
  sem o intermediário e falha na verificação TLS em Python.

## Para acrescentar uma fonte

1. Pasta `<fonte>/<tema>/` com `LEIAME`, `config.yaml`, `sql/`, `scripts/`.
2. DDL em `sql/` seguindo `ARQUITETURA.md` (dimensão antes do fato; chave = código oficial; `id_fonte` e `importado_em`),
   com `GRANT INSERT, UPDATE` só ao papel `etl` nas tabelas novas.
3. Script que usa `dwlib` (conexão, upsert, `Carga`, `registrar_dataset`) e aceita `--simular`.
4. Um teste de regressão contra um número conhecido da fonte.
5. Registrar o dataset em `catalogo.datasets` (o próprio pipeline faz) e documentar no `LEIAME` da fonte.
