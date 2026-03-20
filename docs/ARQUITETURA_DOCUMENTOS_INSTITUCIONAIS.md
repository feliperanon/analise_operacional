# Arquitetura do Módulo de Documentos Institucionais

## 1. Visão Geral

Módulo corporativo de padronização documental com identidade visual única, rastreabilidade e controle de versões. Duas frentes:

- **Documentos Padronizados Operacionais**: POP, IT, FOR, COM, POL, CHK
- **Relatórios**: REL (conteúdo flexível, mesma base institucional)

---

## 2. Arquitetura da Solução

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (Templates + Alpine.js)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  /documentos           Página hub (lista por tipo, busca, filtros)           │
│  /documentos/novo      Criar documento (seleção de tipo → formulário)        │
│  /documentos/{id}      Visualizar / editar documento                         │
│  /documentos/{id}/pdf  Exportar PDF                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  Componentes:                                                                 │
│  - DocumentoBase (cabeçalho, rodapé, controle)                               │
│  - Templates por tipo: POP, IT, FOR, REL, COM, POL, CHK                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BACKEND (FastAPI)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  GET  /documentos              Listar (filtros: tipo, setor, status, busca)  │
│  GET  /documentos/novo         Formulário novo documento                     │
│  POST /documentos              Criar documento                               │
│  GET  /documentos/{id}         Detalhe / edição                              │
│  PUT  /documentos/{id}         Atualizar                                     │
│  POST /documentos/{id}/revisar Nova revisão                                  │
│  GET  /documentos/{id}/pdf     Exportar PDF                                  │
│  GET  /api/documentos/codigo   Gerar próximo código (ex: POP-LOG-002)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BANCO DE DADOS (SQLModel/SQLAlchemy)                │
├─────────────────────────────────────────────────────────────────────────────┤
│  doc_institucional          Tabela principal de documentos                   │
│  doc_institucional_revisao  Histórico de revisões                            │
│  doc_setor                  Áreas/setores (LOG, RH, OP, …)                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Estrutura do Banco de Dados

### 3.1 Tabela `doc_setor`

Configuração de setores para geração de códigos documentais.

| Coluna   | Tipo        | Descrição                |
|----------|-------------|--------------------------|
| id       | INTEGER PK  |                          |
| sigla    | VARCHAR(10) | Ex: LOG, RH, OP, DIR     |
| nome     | VARCHAR(100)| Nome completo do setor   |
| ativo    | BOOLEAN     |                          |

### 3.2 Tabela `doc_institucional`

| Coluna           | Tipo        | Descrição                                  |
|------------------|-------------|--------------------------------------------|
| id               | INTEGER PK  |                                            |
| tipo_documento   | VARCHAR(3)  | POP, IT, FOR, REL, COM, POL, CHK           |
| codigo           | VARCHAR(50) | Ex: POP-LOG-001 (único)                    |
| titulo           | VARCHAR(255)| Nome do documento                          |
| versao           | INTEGER     | Versão atual (1, 2, 3…)                    |
| data_emissao     | DATE        |                                            |
| area_responsavel | VARCHAR(50) | Sigla do setor                             |
| elaborado_por    | VARCHAR(100)|                                            |
| revisado_por     | VARCHAR(100)| nullable                                   |
| aprovado_por     | VARCHAR(100)| nullable                                   |
| classificacao    | VARCHAR(50) | Ex: Interno, Confidencial                  |
| status           | VARCHAR(20) | rascunho, em_revisao, aprovado, obsoleto, arquivado |
| conteudo         | JSONB/TEXT  | Conteúdo específico do tipo                |
| created_at       | TIMESTAMP   |                                            |
| updated_at       | TIMESTAMP   |                                            |
| created_by_id    | INTEGER FK  | user_id ou employee_id                     |

### 3.3 Tabela `doc_institucional_revisao`

| Coluna           | Tipo        | Descrição                      |
|------------------|-------------|--------------------------------|
| id               | INTEGER PK  |                                |
| documento_id     | INTEGER FK  | doc_institucional.id           |
| versao           | INTEGER     | Versão desta revisão           |
| alteracao        | TEXT        | Descrição da alteração         |
| responsavel      | VARCHAR(100)|                                |
| data_revisao     | TIMESTAMP   |                                |

---

## 4. Regras de Negócio

1. **Código documental**: `{TIPO}-{SETOR}-{SEQ}` — ex: `POP-LOG-001`. O sequencial é por tipo+setor.
2. **Status**:
   - `rascunho` → edição livre
   - `em_revisao` → bloqueia edição até aprovação/rejeição
   - `aprovado` → somente leitura; nova alteração exige nova revisão
   - `obsoleto` / `arquivado` → somente leitura
3. **Revisão**: cada mudança relevante gera registro em `doc_institucional_revisao` e incremento de `versao`.
4. **Exportação PDF**: usa layout institucional único (cabeçalho, rodapé, identidade visual).
5. **Permissões**: criar/editar conforme perfil (admin, gestor de processos); visualização pode ser restrita por setor.

---

## 5. Estrutura Base Padrão de Todos os Documentos

```
┌─────────────────────────────────────────────────────────────────┐
│ [LOGO]  NOME DA EMPRESA                                         │
│─────────────────────────────────────────────────────────────────│
│ TIPO | CÓDIGO | VERSÃO | DATA | PÁGINA | ÁREA                    │
│ Elaborado: ___ | Revisado: ___ | Aprovado: ___ | Classificação  │
├─────────────────────────────────────────────────────────────────┤
│ CONTEÚDO ESPECÍFICO (por tipo)                                   │
├─────────────────────────────────────────────────────────────────┤
│ Controle de Revisão | Assinaturas                                │
├─────────────────────────────────────────────────────────────────┤
│ Rodapé institucional padrão                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Campos mínimos obrigatórios em todos os tipos:**
- tipo_documento, titulo, codigo, versao, data_emissao
- area_responsavel, elaborado_por, revisado_por (opc), aprovado_por (opc)
- classificacao, status, conteudo (JSON ou texto estruturado)

---

## 6. Estrutura Específica por Tipo

### POP – Procedimento Operacional Padrão
- objetivo
- aplicacao
- responsabilidades
- definicoes
- procedimento (texto ou etapas)
- pontos_atencao
- controle_revisao

### IT – Instrução de Trabalho
- objetivo
- aplicacao
- passo_a_passo (lista)
- cuidados
- observacoes

### FOR – Formulário
- dados_identificacao
- campos_preenchiveis (array de {nome, tipo, obrigatorio})
- assinaturas
- data
- observacoes

### REL – Relatório
- titulo
- contexto
- objetivo
- descricao_desenvolvimento
- evidencias_fatos
- analise
- conclusao
- responsavel
- data
- anexos (array opcional)

### COM – Comunicado
- titulo
- data
- destinatarios
- mensagem_principal
- orientacoes
- responsavel

### POL – Política Interna
- objetivo
- diretrizes
- regras
- aplicacao
- responsabilidades
- penalidades_desvios (opcional)

### CHK – Checklist
- titulo
- area
- itens_verificacao (array de {item, status, obs})
- responsavel
- data
- observacoes

---

## 7. Fluxo de Criação e Revisão

```
[Criar] → rascunho
   │
   ├─ [Salvar rascunho] → permanece rascunho
   │
   └─ [Enviar para revisão] → em_revisao
         │
         ├─ [Aprovar] → aprovado (registra revisão, incrementa versão)
         └─ [Rejeitar] → rascunho

[Documento aprovado]
   │
   └─ [Nova alteração] → nova revisão → em_revisao → (aprovado | rascunho)

[Obsoletar] → obsoleto
[Arquivar]  → arquivado
```

---

## 8. Modelo Visual (Identidade Institucional)

- **Cabeçalho**: logo, nome da empresa, linha de separação
- **Bloco identificação**: tipo, código, versão, data, página, área, responsáveis
- **Corpo**: conteúdo do tipo específico
- **Rodapé**: "Documento institucional – [Empresa] – Confidencial/Interno – Página X de Y"
- **Tipografia**: serifada para títulos, sans-serif para corpo; hierarquia clara
- **Impressão**: margens adequadas, quebras de página inteligentes

---

## 9. Nomenclatura Sugerida

| Elemento           | Nomenclatura                 |
|--------------------|------------------------------|
| Rotas              | `/documentos`, `/documentos/{id}`, `/documentos/novo` |
| API                | `/api/documentos`, `/api/documentos/{id}`, `/api/documentos/gerar-codigo` |
| Tabelas            | `doc_institucional`, `doc_institucional_revisao`, `doc_setor` |
| Componentes UI     | `DocumentoBase`, `DocumentoHeader`, `DocumentoConteudoPOP`, etc. |
| Templates HTML     | `documentos_institucionais.html`, `documento_detalhe.html`, `documento_form_pop.html` |

---

## 10. Exemplos de Códigos e Títulos

| Tipo | Código     | Título exemplo                               |
|------|------------|----------------------------------------------|
| POP  | POP-LOG-001| Procedimento de separação de pedidos         |
| IT   | IT-MAN-002 | Instrução de manuseio de cargas perigosas    |
| FOR  | FOR-RH-003 | Formulário de solicitação de férias          |
| REL  | REL-OP-004 | Relatório de desempenho operacional – Jan/25 |
| COM  | COM-DIR-005| Comunicado – Mudança de horário de expediente|
| POL  | POL-ADM-006| Política de uso de equipamentos              |
| CHK  | CHK-EXP-007| Checklist de expedição de mercadorias        |

---

## 11. Estratégia de Exportação PDF

1. **Backend**: usar biblioteca (ex: WeasyPrint, ReportLab, ou html2pdf) para gerar PDF a partir de HTML renderizado.
2. **Template único**: um template Jinja compartilhado que recebe o documento e renderiza:
   - cabeçalho institucional
   - bloco de identificação
   - bloco de conteúdo (variável por tipo)
   - rodapé
3. **CSS print**: media `@media print` para garantir layout limpo na impressão.

---

## 12. Controle de Permissões

- **Admin**: acesso total (criar, editar, aprovar, obsoletar, arquivar)
- **Gestor de processos** (novo perfil ou página): criar e editar documentos do seu setor
- **Colaborador**: visualização conforme classificação e setor
- **Auditoria**: registrar em log quem alterou o quê e quando

---

## 13. Próximos Passos de Implementação

1. Criar modelos SQLModel (`DocSetor`, `DocInstitucional`, `DocInstitucionalRevisao`)
2. Migração de banco (nova tabela)
3. Implementar rotas CRUD em `main.py` ou blueprint dedicado
4. Criar templates de formulário por tipo (POP, IT, FOR, etc.)
5. Implementar geração de código automática
6. Implementar exportação PDF
7. Configurar permissões por página (`padronizacao` já está em PAGE_OPTIONS)
