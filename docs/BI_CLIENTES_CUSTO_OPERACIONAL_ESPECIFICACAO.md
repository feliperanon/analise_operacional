# BI Clientes · Custo Operacional (Dashboard executivo)

Documento de arquitetura, UX, lógica analítica e contrato de dados para evolução da página `/bi/clientes`.

## 1. Objetivo do produto

- Separar **causa real** da perda (comercial, cadastro, logística, cliente, financeiro).
- Mostrar **custo de servir**, **tempo improdutivo** e **clientes destrutivos**.
- Servir **operação diária** e **reunião gerencial** (modo apresentação).

### Regra de duração (tempo)

- **Minutos de visita** no BI e no relatório de avaliação do motorista entram **somente** quando há **início e fim pelo app** (`driver_lat_start`/`driver_lon_start` e `driver_lat_end`/`driver_lon_end` preenchidos).
- Rotas **marcadas como entregue/devolução só pela web** (separação, fechamento em massa) **não geram duração** para essas métricas.
- Ao **reabrir** a parada (mobile ou web), os GPS de início/fim são **zerados** para não reaproveitar ciclo anterior.

## 2. Ordem dos blocos (implementação sugerida)

1. Header executivo  
2. Resumo executivo (KPIs grandes)  
3. Leitura executiva imediata (headlines)  
4. Faixas de tempo  
5. Scatter valor × tempo (bubble)  
6. Cliente caro para servir  
7. Origem real das perdas (macrocausas)  
8. Tempo desperdiçado  
9. Clientes destrutivos (score)  
10. Falsos vilões da logística  
11. Ação gerencial  
12. Comparativo períodos  
13. Matrizes decisórias (2)  
14. Mapa de calor — desgaste regional (2 abas)  
15. Tabela principal + drill-through cliente  

## 3. Payload JSON sugerido (`executive_payload`)

```json
{
  "period": { "from": "2025-01-01", "to": "2025-01-31", "previous_label": "...", "current_label": "..." },
  "kpis": {
    "delivered_value": 0,
    "returned_value": 0,
    "return_pct_value": 0,
    "total_duration_min": 0,
    "unproductive_duration_min": 0,
    "monitored_clients": 0,
    "deliveries_count": 0,
    "clients_with_returns": 0,
    "clients_avg_over_60": 0,
    "clients_avg_over_90": 0,
    "deltas": { "delivered_value_pct": 0, "return_pct_value_pp": 0, "..." : 0 }
  },
  "headlines": ["string"],
  "duration_buckets": [
    { "label": "≤20", "visits": 0, "pct_visits": 0, "delivered_value": 0, "avg_value": 0, "total_min": 0, "returns_count": 0, "return_pct": 0, "unproductive_min": 0 }
  ],
  "scatter_clients": [
    { "id": 1, "name": "", "avg_duration_m": 0, "delivered_value": 0, "visits": 0, "return_rate_value": 0, "quadrant": "efficient|strategic_heavy|destructive|low_impact" }
  ],
  "serve_cost_ranking": [ { "client_id": 0, "min_per_1000_brl": 0, "logistic_weight": 0, "est_operational_cost": 0, "est_balance": 0, "unproductive_min": 0, "return_per_hour": 0 } ],
  "macro_loss": {
    "by_macro": [ { "macro": "Comercial", "pct_value": 0, "returned_value": 0, "lost_minutes": 0 } ],
    "top_clients_by_macro": {},
    "top_drivers_by_macro": {}
  },
  "unproductive": {
    "productive_min": 0,
    "unproductive_min": 0,
    "pct_waste": 0,
    "top_clients": [],
    "top_causes": [],
    "top_drivers": []
  },
  "wear_ranking": [ { "client_id": 0, "score": 0, "tier": "Saudável|Atenção|Crítico|Destrutivo", "dominant_macro": "", "primary_action": "", "main_driver": "" } ],
  "false_logistics_villains": [ { "client_id": 0, "city": "", "returned_value": 0, "lost_min": 0, "dominant_macro": "", "driver": "", "suggested_action": "" } ],
  "managerial_actions": [ { "category": "comercial|logistica|cadastro|financeira|conjunta", "text": "", "client_name": "" } ],
  "period_compare": { "metrics": [] },
  "matrices": { "value_time": [], "return_origin": [] },
  "heatmap_regional": {
    "tab_duration": { "cities": [], "buckets": [], "cells": [[0]] },
    "tab_cause": { "cities": [], "causes": [], "cells": [[0]] },
    "metric_mode": "count|pct|total_min|avg_min"
  },
  "heatmap_city_kpis": []
}
```

## 4. Classificação macrocausa (lookup)

Normalizar `motivo` e `responsabilidade`; priorizar campo estruturado se existir. Macros: `Comercial`, `Logística`, `Cadastro / planejamento`, `Cliente / mercado`, `Financeiro / pagamento`. Manter tabela editável (admin ou JSON).

## 5. Score de desgaste

Ver seção “Parte 3” no chat / normalização por percentil no período; tiers: Saudável, Atenção, Crítico, Destrutivo.

## 6. Modo reunião

- Query: `?mode=presentation` ou toggle Alpine `presentationMode`.
- CSS: ocultar filtros secundários, tabela completa, reduzir número de gráficos secundários; ampliar KPIs e headlines.

## 7. Arquivos a alterar/criar

- `bi_delivery_routes.py`: funções `_executive_bi_clientes_*`, agregações cidade/faixa/causa, macro mapping.
- `templates/bi_clientes.html` ou nova rota `bi_clientes_v2` durante transição.
- `static/css/bi_delivery_premium.css` ou utilitários Tailwind em `base` se migrar.
- Testes em `tests/test_bi_clientes_dataset.py` para novas agregações.
