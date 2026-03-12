# Importação de Faltas e Atestados (Fechamento de Ponto)

## Arquivo de Entrada

Envie o arquivo Excel **"Fechamento de Ponto"** (.xls ou .xlsx) contendo várias abas mensais:

- Janeiro 2025  
- Fevereiro 2025  
- Março 2025  
- … (uma aba por mês)

## Estrutura das Planilhas

As colunas são identificadas **pelo texto do cabeçalho**, não por posição fixa:

| Coluna                  | Cabeçalhos aceitos                     |
|-------------------------|----------------------------------------|
| Funcionário             | NOME COMPLETO, FUNCIONÁRIO, NOME       |
| Dias (Atestados)        | ATESTADOS, DIAS (ATESTADOS)            |
| Dias (Faltas)           | FALTAS S/J, DIAS (FALTAS), FALTAS      |

## Interpretação dos Campos

### Datas explícitas (gerar lançamento por dia)

| Formato no Excel   | Datas geradas                           |
|--------------------|-----------------------------------------|
| 1 dia (05/01)      | 05/01/ANO_DA_ABA                        |
| 2 dias (05 e 07/01)| 05/01 e 07/01                           |
| 5 dias (02 a 06/01)| 02, 03, 04, 05, 06/01                   |
| 3 dias (01 a 03/01) + 1 dia (10/01) | 01, 02, 03, 10/01                |

### Texto sem datas

| Valor          | Tratamento                             |
|----------------|----------------------------------------|
| INSS, AFASTADO, JUSTIÇA, LICENÇA | Classificado como AFASTAMENTO. Não gera datas individuais. |
| Tudo Falta     | Todos os dias úteis do mês             |

### Campos vazios

- `0`, `-` ou vazio → ignorar

## Formato de Saída

O sistema gera **uma linha por dia**:

```
MATRICULA | NOME | DATA | OCORRÊNCIA
```

Exemplo:

- 1092 | JOAO SILVA | 05/01/2025 | Falta  
- 1092 | JOAO SILVA | 06/01/2025 | Falta  
- 1092 | JOAO SILVA | 10/01/2025 | Atestado  

## Regras

- Lê **todas as abas** do arquivo.
- O **ano** é obtido do nome da aba (ex.: "Janeiro 2025" → 2025).
- NUNCA agrupa várias datas em uma única linha.
- Não inventa datas nem estima períodos não explícitos.
- Cruza FUNCIONÁRIO com colaboradores cadastrados por **nome**.
- Ignora colaboradores não cadastrados.
- Ocorrências anteriores para o mesmo dia são sobrescritas.

## Como Importar

1. Acesse **Colaboradores** → **Importar** → **Ocorrências**.
2. Selecione o arquivo Excel (.xls ou .xlsx).
3. Clique em **Processar Ocorrências**.

O sistema processa as abas, extrai as datas e cria os lançamentos de rotina e eventos no histórico.
