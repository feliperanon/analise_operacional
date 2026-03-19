# Desempenho da aplicação

## Por que as páginas podem parecer lentas?

1. **Banco no exterior** — Se `DATABASE_URL` aponta para o Postgres da Render (EUA), cada consulta soma latência de rede (southern Brazil ↔ Virginia costuma ser dezenas a centenas de ms por ida e volta). Muitas páginas fazem várias consultas por request.

2. **Páginas BI** — Agregam muitas rotas e devoluções em memória. Quanto maior o intervalo de datas, mais linhas são lidas e processadas.

## O que já foi otimizado no código

- **BI Clientes** (`/bi/clientes`): em vez de carregar o período atual e o anterior com **duas** execuções completas do dataset de entregas, há **uma** leitura cobrindo os dois intervalos e o resultado é dividido em Python. Isso reduz idas ao banco.
- **Devoluções** (`/devolucoes`): não roda mais o backfill de duplicatas Excel em **cada** abertura da página (isso lia **todas** as devoluções do mês). O backfill roda **após gravar** o import (commit). Placas: em vez de carregar **todas** as rotas do mês, busca só as combinações cliente+motorista+dia da **página atual**. Cadastros nos selects: apenas `id`, `nome`, `nb` / `seller_code`. Padrão **250** linhas por página (antes 500).
- **Motivos / responsabilidades** (devolução): listas de referência ficam em **cache em memória** (~5 min) para não repetir `SELECT` em toda página BI.
- **Pool Postgres**: `pool_size=8`, `max_overflow=12` para reaproveitar conexões sob carga.

## Próximos passos possíveis (infra / produto)

| Ação | Efeito |
|------|--------|
| Postgres mais próximo do Brasil (ou região da equipe) | Menor latência em toda consulta |
| Índices em `route.date`, `route.type`, `devolucao.data_romaneio` | Consultas por período mais rápidas |
| Cache HTTP ou Redis para BI com TTL (ex.: 30–60 s) | Menos carga; dados podem atrasar alguns segundos |
| Reduzir intervalo padrão de datas nos BI | Menos linhas por página |
| Worker único + `workers=1` no Uvicorn em dev | Evita múltiplos processos disputando pool |

## Ambiente local

Com banco **local (SQLite)**, o gargalo costuma ser CPU ao montar o BI, não rede. Com banco **remoto**, a rede costuma dominar.

## Uvicorn “Reloading…” travado

- Causa comum: ao salvar `database.py`, o processo filho tenta **reconectar ao Postgres** sem limite de tempo e pode parecer congelado.
- **Correções no projeto:** timeout de conexão (`DB_CONNECT_TIMEOUT`, `DB_PROBE_TIMEOUT`), pool menor em dev, e `run.ps1` com `--reload-exclude database.py` (alterações em `database.py` → pare o servidor com Ctrl+C e suba de novo).
- Variáveis opcionais: `DB_CONNECT_TIMEOUT=12`, `DB_PROBE_TIMEOUT=8`, `ENV=production` + `DB_POOL_SIZE=8` em produção.
