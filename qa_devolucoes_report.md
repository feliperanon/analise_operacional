# QA Devolucoes - Relatorio Automatizado

- Data/Hora: 2026-03-03T11:50:37
- URL: http://127.0.0.1:8000/devolucoes
- Status geral: **Aprovado com ressalvas**
- Total de testes: 13 | Aprovados: 9 | Falhas/N/A: 4

## Evidencias
- `artifacts/devolucoes/01_home.png`
- `artifacts/devolucoes/02_filtro_data.png`
- `artifacts/devolucoes/03_filtro_turno_na.png`
- `artifacts/devolucoes/04_filtro_motorista.png`
- `artifacts/devolucoes/05_filtro_motivo.png`
- `artifacts/devolucoes/06_filtro_busca_textual.png`
- `artifacts/devolucoes/07_reset.png`
- `artifacts/devolucoes/08_sem_resultado_na.png`
- `artifacts/devolucoes/09_mobile.png`

## Achados
- DV-003 [MEDIO] UX/Funcional: Tabela/listagem n?o encontrada (evidencia: artifacts/devolucoes/01_home.png)
- DV-004 [MEDIO] Analytics/Produto: Filtros apenas no modal de lan?amento manual (evidencia: artifacts/devolucoes/01_home.png)
- DV-005 [MEDIO] BI: KPIs agregados n?o identificados (evidencia: artifacts/devolucoes/01_home.png)

## Detalhes dos testes
- OK - Autentica??o e acesso ? p?gina :: url=http://127.0.0.1:8000/devolucoes
- OK - Carregamento do m?dulo devolu??es :: 
- FALHA - Presen?a de tabela/listagem :: tables=0
- OK - A??es principais (manual/importar) :: 
- OK - Filtro por data (modal manual) :: 
- FALHA - Filtro por turno :: [N/A] filtro n?o existe na p?gina
- OK - Filtro por motorista (modal manual) :: value=1
- OK - Filtro por status/motivo (modal manual) :: motivo=1
- OK - Busca textual (observa??o modal) :: 
- OK - Reset de filtros/formul?rio :: 
- FALHA - Estado sem resultado (filtro extremo) :: [N/A] sem filtros da listagem
- OK - Responsividade mobile :: 
- FALHA - Consist?ncia KPI agregado vs detalhe :: [N/A] KPI agregado n?o identificado na p?gina

## Calculo
- Formula: SUM(valor_linhas_visiveis)
- Soma tabela: 0
- KPI agregado: None
- Validacao percentual: N/A