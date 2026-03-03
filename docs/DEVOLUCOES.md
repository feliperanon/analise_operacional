# Módulo Devoluções

Registro de devoluções e ocorrências de entrega. O sistema valida rigorosamente contra os cadastros (Clientes, Vendedores, Motoristas, Motivos, Responsabilidades) e calcula campos derivados automaticamente.

## Acesso

- **Web (gestão):** [http://127.0.0.1:8000/devolucoes](http://127.0.0.1:8000/devolucoes)
- **Mobile:** Módulo "Devoluções" no dashboard (para colaboradores com acesso a separação)
- **Menu:** Processos → Devoluções

## Formas de alimentar

1. **Upload Excel** – `.xlsx`, `.xls`, `.xlsm` (até 10MB)
2. **Lançamento manual** – formulário na tela
3. **API** – `POST /api/devolucoes` (usado por mobile/web)

## Estrutura do Excel

Colunas obrigatórias (flexíveis a espaços/acentos):

| Coluna | Descrição | Exemplo |
|--------|-----------|---------|
| DATA ROMANEIO | dd/mm/aaaa | 02/02/2026 |
| DATA ENTREGA | dd/mm/aaaa | 02/02/2026 |
| CODIGO | Código do cliente | 61/50 |
| NOME DO CLIENTE | Texto | FIMA CENTRAL DE COMPRA |
| VENDEDOR | Código vendedor | 110 |
| MOTORISTA | Nome | GILMAR |
| VALOR | pt-BR (vírgula, milhar) | 702,77 ou 1.115,67 |
| MOTIVO | Padronizado | CLIENTE DESISTIU DA COMPRA |
| RESPONSABILIDADE | MERCADO, COMERCIAL ou LOGÍSTICA | MERCADO |
| OBSERVAÇÃO | Opcional | - |
| AJUDANTE | Opcional | - |

### Campos calculados (automáticos)

- **DIA** – dia do mês de DATA ROMANEIO
- **SEMANA** – número da semana ISO baseado em DATA ROMANEIO
- **ACIMA DE R$ 300** – SIM ou NAO
- **CLUSTER** – faixa de valor: 0-50, 50-100, …, 1.100-1.200, Acima 1.200

## Fluxo de importação (Preview → Commit)

1. Envie o arquivo Excel
2. O sistema mostra: quantidade válida, inválida e erros por linha
3. Confirme para gravar apenas as linhas válidas
4. Linhas inválidas não são gravadas (falta de cadastro)

## Validações

- **Cliente:** por CODIGO (campo `nb` no cadastro)
- **Vendedor:** por código (`seller_code` do Employee)
- **Motorista:** por nome (match flexível)
- **Motivo:** normalizado contra cadastro
- **Responsabilidade:** MERCADO, COMERCIAL ou LOGÍSTICA
- **Ajudante:** se informado, deve existir

## Idempotência

Chave: `data_romaneio + client_id + vendedor_id + motorista_id + valor + motivo_id`  
Duplicatas são ignoradas no commit.

## API

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | /api/devolucoes | Lista devoluções (filtros: start_date, end_date) |
| POST | /api/devolucoes | Lançamento manual (JSON) |
| POST | /api/devolucoes/import | Upload Excel (preview) |
| POST | /api/devolucoes/import/commit | Confirma gravação do preview |

### Payload manual (POST /api/devolucoes)

```json
{
  "data_romaneio": "2026-02-02",
  "data_entrega": "2026-02-02",
  "client_id": 1,
  "vendedor_id": 2,
  "motorista_id": 3,
  "valor": 702.77,
  "motivo_id": 1,
  "responsabilidade_id": 1,
  "observacao": null,
  "ajudante_id": null
}
```
