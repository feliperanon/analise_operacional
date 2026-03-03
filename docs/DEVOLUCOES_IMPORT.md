# Importação de Devoluções – Diagnóstico e Health

## Endpoint de saúde

`GET /api/devolucoes/health` retorna o estado dos cadastros necessários para importação.

### Exemplo de retorno (ok)

```json
{
  "ok": true,
  "diagnostics": {
    "employees_total": 50,
    "employees_with_seller_code": 12,
    "vendedor_by_code_size": 24,
    "clients_total": 500,
    "client_by_nb_size": 500,
    "motivos_total": 15,
    "responsabilidades_total": 3
  },
  "global_errors": [],
  "ok_vendedores": true,
  "ok_motivos": true,
  "ok_responsabilidades": true,
  "ok_clientes": true
}
```

### Exemplo de retorno (falha)

```json
{
  "ok": false,
  "diagnostics": {
    "employees_total": 50,
    "employees_with_seller_code": 0,
    "vendedor_by_code_size": 0,
    ...
  },
  "global_errors": [
    "Nenhum colaborador com seller_code preenchido (employees_with_seller_code=0). Preencha o campo 'Codigo do Vendedor' em Colaboradores para cada vendedor."
  ],
  "ok_vendedores": false,
  ...
}
```

## Contagens esperadas

| Campo | Descrição | Expectativa |
|-------|-----------|-------------|
| employees_total | Total de colaboradores (não demitidos) | > 0 |
| employees_with_seller_code | Colaboradores com seller_code preenchido | > 0 para importar por código |
| vendedor_by_code_size | Tamanho do índice de vendedores por código | > 0 |
| clients_total | Total de clientes | > 0 |
| client_by_nb_size | Clientes com nb (código) para lookup | > 0 |
| motivos_total | Motivos de devolução ativos | > 0 |
| responsabilidades_total | Responsabilidades ativas | > 0 |

## Erro global na importação

Se algum cadastro essencial estiver vazio, a importação retorna **erro global** (400) em vez de N erros por linha.

Exemplo de retorno do `POST /api/devolucoes/import`:

```json
{
  "ok": false,
  "error": "Nenhum colaborador com seller_code preenchido...",
  "global_errors": ["..."]
}
```

## Como corrigir

1. **Vendedores vazios**: Preencha o campo "Codigo do Vendedor" em Colaboradores.
2. **Motivos vazios**: Execute o seed de motivos de devolução.
3. **Responsabilidades vazias**: Execute o seed de responsabilidades.
4. **Clientes vazios**: Importe o cadastro de clientes antes.
