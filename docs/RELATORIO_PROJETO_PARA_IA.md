# Relatorio Tecnico Estruturado do Projeto para IA

Data da analise: 07/04/2026  
Projeto analisado: `c:\Projetos\NL`

## 1. Resumo Executivo

Este repositorio implementa um sistema operacional/logistico grande, centrado em FastAPI, SQLModel e templates Jinja2, com uma arquitetura hibrida:

- Backend monolitico em `main.py`, complementado por alguns modulos de rotas especializados.
- Frontend server-rendered com HTML Jinja2, CSS compilado por Tailwind e varias ilhas de JavaScript por pagina.
- Operacao desktop e mobile no mesmo sistema, com sessao administrativa e sessao de colaborador.
- Banco de dados dual: PostgreSQL remoto em ambientes Render e SQLite local em desenvolvimento.
- Forte foco em operacao de entregas, devolucoes, smart flow, checklists, portaria, BI e gestao de pessoas.

Estatisticas levantadas no scan local:

- 85 arquivos Python proprios.
- 103 templates HTML.
- 370 rotas registradas no app FastAPI quando a aplicacao sobe.
- `main.py` com aproximadamente 29.330 linhas.
- `models.py` com 60 entidades SQLModel.
- 13 arquivos de teste com 68 testes automatizados.

## 2. Verdade Arquitetural do Repositorio

### 2.1 Stack real

- Framework web: FastAPI.
- Templating: Jinja2.
- ORM/modelagem: SQLModel sobre SQLAlchemy.
- Banco: PostgreSQL remoto ou SQLite local.
- Upload/importacao: `python-multipart`, `pandas`, `openpyxl`, `xlrd`.
- Frontend: Tailwind compilado para `static/styles.css`, CSS complementar em `static/css/*`, JS modular e JS inline em templates.
- Mapas/graficos: ApexCharts, Chart.js, Leaflet.
- IA: integracao ativa com Google Gemini para parecer de turnover; dependencia `openai` existe em `requirements.txt`, mas nao apareceu como parte ativa do runtime analisado.

### 2.2 Como a aplicacao sobe

O ponto de entrada real e `main.py`.

No startup, o app:

- Carrega `.env`.
- Valida variaveis de ambiente do Render.
- Cria tabelas e executa migracoes incrementais.
- Garante compatibilidade de schema para colunas novas.
- Semeia dados obrigatorios: admin padrao, devolucoes, setores de documentos.
- Sincroniza configuracoes operacionais.
- Inicia loop de autoclose de sessoes antigas de entrega.

O app registra:

- Routers especializados: BI, devolucoes, documentos, escalas, gamificacao, geocodificacao.
- `SessionMiddleware` para autenticacao baseada em sessao.
- `ProxyHeadersMiddleware` em ambiente produtivo/proxy.
- `StaticFiles` em `/static`.
- Middlewares de anti-cache e tratamento global de excecoes.

### 2.3 Regra critica de banco

`database.py` nao faz fallback silencioso para SQLite se houver `DATABASE_URL` configurada e a conexao remota falhar.

Comportamento real:

- Se houver URL remota configurada, o codigo tenta PostgreSQL e pode levantar erro fatal se ele estiver indisponivel.
- Para forcar SQLite local, e necessario definir `FORCE_LOCAL_DB=true`.

Isto e importante para qualquer IA que va rodar o projeto localmente.

### 2.4 Dois modelos de autenticacao

O sistema trabalha com dois perfis de sessao:

- Sessao administrativa/gestao: usuario salvo em `request.session` com `auth_user_id`, `auth_user_role`, `allowed_pages`.
- Sessao mobile de colaborador: colaborador salvo em `request.session["user_id"]`.

Regras principais:

- Usuarios administrativos podem ver desktop e, conforme papel/permissoes, rotas administrativas.
- Colaboradores mobile ficam restritos a `/mobile`, APIs e alguns endpoints especificos como `/escala`.
- Lideres usam filtro de `allowed_pages` por prefixo de rota.

## 3. Mapa de Diretorios

- `main.py`: nucleo do sistema, grande concentrador de regras de negocio, rotas, auth, middlewares, migracoes auxiliares e views.
- `database.py`: resolucao de ambiente, criacao do engine e migracoes simples de schema.
- `models.py`: todos os modelos SQLModel do sistema.
- `templates/`: paginas HTML Jinja2.
- `static/`: CSS, JS, service worker, assets e uploads.
- `routers/`: routers menores, hoje com destaque para `admin_geocoding.py`.
- `services/`: servicos de apoio, como geocodificacao e parser.
- `utils/`: funcoes utilitarias para mobile hub, projection e geo.
- `tests/`: suite pytest.
- `docs/`: documentacao institucional e tecnica.
- `scripts/`: scripts de manutencao, limpeza, geocoding, migracao e verificacoes.
- `vendor/` e `node_modules/`: bibliotecas e templates de apoio ao frontend.
- `tamagotchi/`: miniapp/experimento isolado, nao apareceu ligado ao runtime principal.

## 4. Arquivos Backend Principais

### 4.1 Nucleo de runtime

- `main.py`: arquivo mais importante do repositorio. Centraliza rotas desktop, mobile, auth, dashboards, smart flow, employees, clients, vehicles, portaria, rankings, turnover, checklists, ordens de servico, gamificacao e dezenas de APIs.
- `database.py`: resolve a origem do banco, cria o engine, define pool e executa pequenas migracoes orientadas a compatibilidade.
- `models.py`: define toda a camada de persistencia; o schema inteiro esta concentrado aqui.
- `render_env_validation.py`: validacao preventiva de ambiente, especialmente no Render.

### 4.2 Modulos de rotas especializados

- `bi_delivery_routes.py`: BI de entregas, clientes, devolucoes e relatorio de avaliacao de motorista.
- `bi_motorista_routes.py`: camada de avaliacao de motorista reaproveitando o dataset do BI delivery.
- `devolucoes_routes.py`: telas e APIs do modulo de devolucoes; importa, valida, aprova, reprocessa e reconcilia devolucoes com rotas.
- `documentos_routes.py`: modulo de documentos institucionais; listagem, cadastro, edicao, detalhe, impressao e geracao automatica de codigo.
- `escalas_routes.py`: pagina desktop e mobile de escala operacional, mais APIs para leitura e atualizacao.
- `game_achievements_routes.py`: CRUD e concessao manual de conquistas da gamificacao.
- `game_audit_routes.py`: auditoria de XP, exportacao e analise de rotas para o sistema de game.
- `routers/admin_geocoding.py`: processamento administrativo de geocodificacao de clientes.

### 4.3 Servicos e utilitarios ativos

- `devolucoes_service.py`: servico pesado do dominio de devolucoes. Faz parse de Excel, validacao, normalizacao, reconciliacao, idempotencia, deduplicacao e sincronizacao com `Route`.
- `services/geocoding_service.py`: geocodificacao via Nominatim/OpenStreetMap, com rate limit e validacao de coordenadas.
- `client_import_utils.py`: normalizacao de endereco, telefone e chaves para importacao de clientes.
- `route_duration.py`: calculo de duracao e tempo decorrido de rotas.
- `utils/delivery_projection.py`: projecao de ETA e nivel de alerta de rotas em andamento.
- `utils/mobile_hub.py`: monta o perfil da home mobile dinamica com modulos e estatisticas.
- `utils/geo_utils.py`: validacoes geograficas.
- `backup_service.py`: criacao e listagem de backups.
- `services/fechamento_ponto_parser.py`: parser auxiliar para importacoes ligadas a fechamento/ponto.

### 4.4 Artefatos e arquivos que nao devem ser tratados como fonte principal

Estes arquivos existem, mas nao devem ser tratados como a fonte principal do sistema:

- `patch_*.py`: artefatos de patch/refactor historicos.
- `routes_to_append.py`: fragmento auxiliar, nao parece ser a fonte real das rotas atuais.
- `find_string.py`: utilitario, nao modulo de runtime.
- `operational_history_routes.py`: arquivo duplicado/stale; ha uma versao ativa das mesmas rotas dentro de `main.py`, e este arquivo esta estruturalmente inconsistente.
- `bi_motorista_test.html`, `tmp_*`, `diff.txt`: arquivos temporarios, comparativos ou de experimento.
- `README.md`: util, mas parcialmente desatualizado frente ao estado atual do codigo.

## 5. Modelo de Dados por Dominio

`models.py` e o centro semantico do projeto. As entidades estao organizadas, na pratica, nestas familias:

### 5.1 Operacao e RH

- `Shift`
- `HeadcountTarget`
- `Employee`
- `DailyOperation`
- `Event`
- `User`
- `SectorConfiguration`
- `CargoMaster`

### 5.2 Clientes, frota e entrega

- `ClientGroup`
- `Client`
- `ClientAuditLog`
- `ClientImportBatch`
- `ClientImportStaging`
- `Vehicle`
- `Route`
- `EscalaAlteracaoLog`
- `RouteInsertLog`
- `DeliverySession`
- `DeliveryAuthRequest`
- `VehicleLocation`
- `PortariaCheck`

### 5.3 Checklists, equipamentos e manutencao

- `TranspalletEquipment`
- `EquipmentTicket`
- `EquipmentTicketEvent`
- `ChecklistEmailRecipient`
- `AbsenceAlertRecipient`
- `AbsenceAlertLog`
- `TranspalletChecklist`

### 5.4 Smart Flow e alocacao operacional

- `Sector`
- `SubSector`
- `EmployeeAllocation`
- `EmployeeRoutine`

### 5.5 Gamificacao

- `XPLedger`
- `GameLevel`
- `GameXPTransaction`
- `GameAchievement`
- `EmployeeAchievement`
- `GameConfiguration`

### 5.6 Historico de substituicoes e ordens

- `SubstitutionHistory`
- `LeaderTask`
- `LeaderTaskResponse`
- `OperationalTask`
- `OperationalTaskExecution`

### 5.7 Devolucoes

- `DevolucaoResponsabilidade`
- `DevolucaoMotivo`
- `Devolucao`
- `DevolucaoImportBatch`
- `DevolucaoImportRowError`
- `DevolucaoStaging`
- `DevolucaoAjusteResponsabilidade`

### 5.8 Informativo/dashboard

- `InformativeBulletin`
- `InformativePanelConfig`
- `InformativeMonthlyReturn`

### 5.9 Documentos institucionais

- `DocSetor`
- `DocInstitucional`
- `DocInstitucionalRevisao`

## 6. Mapa Estruturado das Paginas

### 6.1 Layouts e componentes compartilhados

- `templates/base.html`: shell desktop padrao, inclui `_sidebar.html`, assets principais, modal de alertas do lider e estilos globais.
- `templates/base_gestao_avista.html`: shell desktop com stack visual TailAdmin/System CSS, usado por paginas de cadastro como `employees.html`.
- `templates/_sidebar.html`: menu lateral compartilhado e altamente central para navegacao.
- `templates/mobile/layout.html`: shell mobile/PWA; inclui header, tokens visuais, fila offline em IndexedDB, sincronizacao manual, helper de datas e registro do service worker.
- `templates/mobile/_app_header.html`: cabecalho reutilizado do mobile.
- `templates/mobile/_design_tokens.html`: tokens de cor, tipografia e superficies.
- `templates/mobile/_driver_guide.html`: bloco de orientacao reutilizado em algumas telas mobile.
- `templates/bi/_components.html`: partial de apoio visual ao BI.

### 6.2 Dashboards e paineis principais

- `/dashboard` -> `dashboard_informativo.html`: painel executivo "Gestao Avista". Mostra KPI do dia, comparativos de devolucao, carrossel de comunicados, aniversarios, progresso de rotas e dados agregados. Atualizacao parcial por `/api/dashboard/informativo-data`.
- `/dashboard/tv` -> `dashboard_tv.html`: mural operacional em tempo real, focado em rotas abertas, alertas, devolucoes do dia, ETA por motorista e estado da operacao.
- `/admin/informativo` -> `admin_informativo.html`: painel administrativo do informativo. Permite configurar tempo do carrossel, cadastrar devolucao mensal por ano, publicar avisos, listar/editar/excluir boletins.
- `/admin/informativo/{bulletin_id}/edit` -> `admin_informativo_edit.html`: tela de edicao de aviso. Usa o mesmo design system do painel admin, mas reduzida a um formulario unico.

### 6.3 Autenticacao e sistema

- `/login` -> `login.html`: login administrativo/gestao.
- `/admin/users` -> `admin_users.html`: cadastro e administracao de usuarios internos.
- `/admin/users/{user_id}/edit` -> `admin_user_edit.html`: edicao de usuario, papel, paginas permitidas, senha e vinculo com colaborador.
- `templates/error_500.html`: pagina de erro customizada do sistema.
- `templates/reset_request.html` e `templates/reset_password.html`: templates de reset existem, mas nao apareceram como rotas ativas no scan atual.

### 6.4 Cadastros e RH

- `/employees` -> `employees.html`: base de colaboradores, estatisticas por centro de custo, filtros, importacao e administracao de quadro.
- `/employees/{employee_id}` -> `employee_detail.html`: detalhe rico do colaborador, com historico, eventos, ferias e integracao com blocos de Smart Flow.
- `/funcoes` -> `funcoes.html`: cadastro de cargos/funcoes.
- `/people-intelligence` -> `people_intelligence.html`: analise de ausencias, atestados, afastamentos, risco por setor e reincidencias.
- `/people-intelligence/report` -> `people_intelligence_report.html`: versao imprimivel do modulo de people intelligence.
- `/import-medical-certificates` -> `import_medical_certificates.html`: importacao de atestados medicos.
- `/admin/substitutions` -> `admin_substitutions.html`: historico de substituicoes e trocas de colaborador.
- `/admin/turnover-analysis` -> `admin_turnover_analysis.html`: analise de turnover/rotatividade, com possibilidade de gerar parecer executivo por IA Gemini.

### 6.5 Clientes e frota

- `/clients` -> `clients.html`: banco de clientes, com filtros por status, movimentacao, segmento e precadastro.
- `/clients/{client_id}` -> `client_details.html`: detalhe do cliente, historico e informacoes cadastrais.
- `/clients/import/conflicts/{batch_id}` -> `clients_import_conflicts.html`: tratamento de conflitos de importacao.
- `/vehicles` -> `vehicles.html`: cadastro de frota com visao geral e distribuicao por tipo.
- `/vehicles/odometer` -> `vehicles_odometer.html`: visao da frota focada em KM atual e historico.
- `/vehicles/new` e `/vehicles/{vehicle_id}` -> `vehicle_detail.html`: criacao/edicao de veiculo.
- `/vehicles/{vehicle_id}/history` -> `vehicle_history.html`: historico do veiculo.

### 6.6 Operacao desktop

- `/separacao` -> `routes.html`: modulo desktop de separacao/entregas. Exibe rotas por colaborador, grupos de entrega, status de abertura, produtividade, devolucao, importacao e sincronizacao com `DeliverySession`.
- `/smart-flow` -> `smart_flow.html`: quadro visual de alocacao operacional. Trabalha com setores, subsetores, presenca, ausencias, vagas, metas e movimentacao de colaboradores.
- `/smart-flow/organogram` -> `organogram_report.html`: relatorio imprimivel do organograma operacional.
- `/routine/report` -> `report_pdf.html`: relatorio operacional/impressao do turno.
- `/portaria` -> `portaria.html`: historico desktop de saidas e chegadas confirmadas pela portaria.
- `/operational/history` -> `operational_history.html`: historico operacional de rotas com capacidade de consulta e edicao via API.
- `/documentos` -> `documentos_institucionais.html`: repositorio de documentos institucionais.
- `/documentos/novo` -> `documento_form.html`: novo documento institucional.
- `/documentos/{doc_id}` -> `documento_detalhe.html`: detalhe do documento.
- `/documentos/{doc_id}/editar` -> `documento_editar.html`: edicao de documento.
- `/documentos/{doc_id}/print` -> `documento_print.html`: versao de impressao do documento.

### 6.7 BI e analytics

- `/strategy` -> `strategy.html`: modulo estrategico com KPI consolidados, graficos e APIs especificas.
- `/operations/performance` e `/rankings` -> `rankings.html`: ranking/avaliacao operacional. Classifica colaboradores por score, Kg/h, regularidade, consistencia, liga de experiencia e outras variaveis.
- `/operations/performance/analysis` -> `operations_performance_report.html`: relatorio analitico ampliado.
- `/operations/performance/report` -> `rankings_report_pdf.html`: versao exportavel/imprimivel do ranking.
- `/gamificacao/entregas` -> `delivery_gamification.html`: visao de premiacao/gamificacao de entregas.
- `/bi/delivery` -> `bi_delivery.html`: BI premium de entregas.
- `/bi/clientes` -> `bi_clientes.html`: custo operacional por cliente.
- `/bi/devolucoes` -> `bi_devolucoes.html`: BI de devolucoes.
- `/bi/motorista` -> `bi_motorista.html`: BI de avaliacao de motoristas.
- `/relatorio-avaliacao-motorista` -> `relatorio_avaliacao_motorista.html`: relatorio detalhado para avaliacao de motoristas.

### 6.8 Lideranca, GM e ordens

- `/lider/checklists` -> `lider_checklists.html`: visao de checklists para lideranca.
- `/lider/rotas` -> `lider_rotas.html`: acompanhamento de rotas e avaliacao da equipe.
- `/lider/rotas/relatorio` -> `lider_rotas_relatorio.html`: relatorio de ausencias/rotas.
- `/lider/tarefas` -> `lider_tarefas.html`: criacao e acompanhamento de tarefas.
- `/lider/minhas-ordens` -> `lider_minhas_ordens.html`: ordens operacionais atribuidas ao lider.
- `/gm/ordens-servico` -> `gm_ordens_servico.html`: criacao e gerenciamento de ordens de servico.
- `/gm/ordens-servico/historico` -> `gm_ordens_historico.html`: historico de execucoes.
- `/gm/ordens-servico/kpis` -> `gm_ordens_kpis.html`: KPI das ordens/execucoes.
- `/gm/performance-operacional` -> `gm_performance_operacional.html`: visao de performance operacional para gestao.
- `/gm/mapa-realtime` -> `gm_mapa_realtime.html`: mapa em tempo real com Leaflet.

### 6.9 Devolucoes, checklist, equipamentos e administracao operacional

- `/devolucoes` -> `devolucoes.html`: modulo principal de devolucoes, com importacao, conciliacao e operacao diaria.
- `/devolucoes/avaliar` -> `devolucoes_avaliar.html`: tela de avaliacao/consolidacao das devolucoes.
- `/admin/delivery-auth-requests` -> `admin_delivery_auth_requests.html`: autorizacoes de entrega fora da area/raio esperado.
- `/admin/routine/checklists/dashboard` -> `admin_routine_checklists_dashboard.html`: painel agregador dos checklists operacionais.
- `/admin/routine/checklists/settings` -> `admin_routine_checklists_settings.html`: configuracoes de e-mail/equipamento do modulo de checklist.
- `/admin/routine/checklists` -> `admin_routine_checklists.html`: listagem administrativa de checklists.
- `/admin/routine/checklists/{checklist_id}` -> `admin_routine_checklist_detail.html`: detalhe, revisao, aprovacao e reprova de checklist.
- `/admin/equipment/tickets` -> `admin_equipment_tickets.html`: chamados de equipamento.
- `/admin/equipment/tickets/{ticket_id}` -> `admin_equipment_ticket_detail.html`: detalhe do chamado.
- `/admin/equipment/history` -> `admin_equipment_history.html`: historico de equipamento/manutencao.
- `/admin/tools/reset-delivery` -> `admin_reset_delivery.html`: tela perigosa de reset operacional.
- `/admin/tools/email-test` -> `admin_email_test.html`: teste SMTP.
- `/admin/game` -> `admin_game.html`: dashboard do game master.
- `/admin/game/achievements` -> `admin_achievements.html`: CRUD de conquistas.
- `/admin/game/audit` -> `admin_game_audit.html`: auditoria de XP/transacoes.
- `/admin/game/audit/employee/{employee_id}` -> `admin_game_employee_detail.html`: detalhe do historico gamificado do colaborador.
- `/admin/game/settings` -> `admin_game_settings.html`: configuracoes da gamificacao.
- `/admin/absence-alerts/settings` e `/admin/alerts/settings` -> `admin_absence_alerts_settings.html`: painel de destinatarios e regras de alerta de ausencia/manutencao.

### 6.10 Mobile

- `/mobile/login` -> `mobile/login.html`: login do colaborador.
- `/mobile/dashboard` -> `mobile/dashboard.html`: home mobile principal, montada dinamicamente conforme flags de acesso do colaborador.
- `/mobile/dashboard-preview` -> `mobile/dashboard_preview.html`: template existe para preview, mas a rota atual redireciona para `/mobile/entregas`.
- `/mobile/delivery` -> `mobile/delivery.html`: rota ativa de entregas.
- `/mobile/returns` -> `mobile/returns.html`: avaliacao e indicador de devolucao no mobile.
- `/mobile/entregas` e `/mobile/historico-entregas` -> `mobile/entregas.html`: historico de entregas.
- `/mobile/portaria` -> `mobile/portaria.html`: fluxo mobile da portaria.
- `/mobile/portaria/historico` -> `mobile/portaria_historico.html`: historico da portaria para o colaborador.
- `/mobile/routine/checklist` -> `mobile/routine_checklist.html`: checklist operacional mobile.
- `/mobile/routine/history` -> `mobile/routine_history.html`: historico de checklist.
- `/mobile/tarefas` -> `mobile/tarefas.html`: tarefas do colaborador.
- `/mobile/equipment/tickets` -> `mobile/tickets_list.html`: lista de chamados do colaborador.
- `/mobile/equipment/tickets/new` -> `mobile/equipment_ticket_new.html`: abertura de chamado.
- `/mobile/equipment/tickets/{ticket_id}` -> `mobile/tickets_detail.html`: detalhe do chamado.
- `/mobile/escala` -> `escala_mobile.html`: visao mobile do modulo de escala.
- `/mobile/achievements` -> `mobile/achievements.html`: conquistas/gamificacao.
- `/mobile/admin/routes` -> `mobile/admin_routes.html`: monitoramento mobile de rotas para perfis de gestao.

### 6.11 Templates existentes mas sem evidencias de uso direto no runtime atual

- `templates/index.html`: existe no repositorio, mas nao apareceu como template efetivamente renderizado pelas rotas ativas atuais.
- `templates/mobile/game.html`: template existente, mas sem rota registrada no scan atual.
- `templates/reset_request.html` e `templates/reset_password.html`: templates prontos, mas sem rota ativa localizada no scan atual.

## 7. Principais Fluxos de Negocio

### 7.1 Informativo e dashboard executivo

Fluxo:

- Gestor publica boletins em `/admin/informativo`.
- Dados vao para `InformativeBulletin`, `InformativePanelConfig` e `InformativeMonthlyReturn`.
- `/dashboard` e `/api/dashboard/informativo-data` combinam comunicados, devolucao, aniversarios, ferias e progresso de rotas.
- `dashboard_informativo.html` exibe o painel executivo.

### 7.2 Painel TV / comando operacional

Fluxo:

- `/dashboard/tv` consolida colaboradores, rotas do dia, sessoes abertas, ETA, alertas e devolucoes.
- `utils/delivery_projection.py` calcula ETA, slack e nivel de alerta.
- `dashboard_tv.html` mostra motoristas em tempo real, status da rota e alertas de cliente parado.

### 7.3 Separacao e operacao de entrega

Fluxo:

- `/separacao` monta grupos de entrega por colaborador e periodo.
- Rotas `Route` sao combinadas com `DeliverySession`, veiculos e ajudantes.
- O mesmo dominio conversa com a operacao mobile de entrega.
- Os estados de entrega impactam dashboard, BI, portaria, devolucoes e gamificacao.

### 7.4 Smart Flow

Fluxo:

- `/smart-flow` carrega `DailyOperation`, metas, configuracao de setores e attendance log.
- JS modular em `static/js/smart-flow/*` controla estado, renderizacao, eventos, drag-and-drop e persistencia.
- APIs `/api/smart-flow/*` sustentam save/load, setores, subsetores, rotinas e alocacoes.

### 7.5 Devolucoes

Fluxo:

- Importacao Excel em `devolucoes_routes.py`.
- Parse/validacao pesada em `devolucoes_service.py`.
- Regras de deduplicacao, vinculo com rota, vendedor, motorista e motivo.
- BI e dashboards leem a mesma base de devolucoes para analise financeira e operacional.

### 7.6 Portaria

Fluxo:

- `DeliverySession` e `PortariaCheck` sustentam a ida/volta dos motoristas.
- O mobile coleta confirmacoes de saida/chegada.
- `/portaria` mostra historico consolidado desktop.
- `_build_mobile_gatehouse_data()` monta a fila de pendencias de saida/chegada.

### 7.7 Checklists, tickets e manutencao

Fluxo:

- O motorista preenche checklist mobile.
- O admin revisa em `/admin/routine/checklists/*`.
- Tickets de equipamento podem ser abertos no mobile e fechados no admin.
- O modulo conversa com e-mail SMTP, transpaleteiras e historico de manutencao.

### 7.8 Turnover com IA

Fluxo:

- `/admin/turnover-analysis` calcula metricas de rotatividade.
- `/admin/turnover-analysis/ai-report` usa Gemini para gerar parecer executivo.
- Existe tambem ajuste manual/automatico de datas de desligamento.

### 7.9 Mobile hub dinamico

Fluxo:

- `_render_mobile_dashboard_template()` detecta o colaborador autenticado.
- `utils/mobile_hub.py` monta a home conforme flags como `mobile_access_separation`, `mobile_access_returns`, `mobile_access_gatehouse`, `mobile_access_escala`, `mobile_access_admin_start`.
- `mobile/layout.html` implementa comportamento de PWA/offline.

## 8. Frontend: JS e CSS Importantes

### 8.1 CSS

- `static/styles.css`: bundle principal compilado do Tailwind.
- `static/css/system-tokens.css`: tokens semanticos.
- `static/css/system-layout.css`: regras de layout.
- `static/css/system-components.css`: componentes compartilhados.
- `static/css/system-utilities.css`: utilitarios visuais.
- `static/css/dashboard-tailadmin.css`: camada visual inspirada no TailAdmin.
- `static/css/pages/admin-informativo.css`: estilos da administracao de informativo.
- `static/css/pages/dashboard-informativo.css`: estilos do painel executivo.
- `static/css/pages/dashboard-tv.css`: estilos do mural TV.
- `static/css/pages/employees.css`: estilos especificos da pagina de colaboradores.
- `static/css/mobile.css`: base visual mobile.

### 8.2 JavaScript de pagina

- `static/js/smart-flow/api.js`: fetch para APIs do smart flow.
- `static/js/smart-flow/store.js`: store central e source of truth do smart flow.
- `static/js/smart-flow/render.js`: renderizacao da UI do smart flow.
- `static/js/smart-flow/events.js`: interacoes, drag-and-drop e acoes globais.
- `static/js/smart-flow/main.js`: bootstrap do app smart flow.
- `static/js/smart-flow/*`: demais modulos de relogio, KPI, setores, modais e CRUD.
- `static/js/escala.js`: comportamento da pagina de escala.
- `static/js/bi_delivery_premium.js`: interacoes do BI de entrega/motorista.
- `static/js/utils/format-br.js`: formatacoes brasileiras reutilizaveis.

### 8.3 PWA e offline

- `static/sw.js`: service worker.
- `templates/mobile/layout.html`: IndexedDB para fila offline, contagem de itens pendentes, reenvio em lote para `/api/mobile/delivery/sync-batch`.

## 9. Testes Automatizados

A cobertura automatizada atual esta concentrada em regras de negocio e utilitarios, nao tanto em telas HTML.

Areas cobertas:

- `tests/test_devolucoes_service.py`: parse, datas, vendedor, duplicidade, persistencia, sincronizacao com rota.
- `tests/test_mobile_delivery_return_action.py`: regras de devolucao mobile, validacoes obrigatorias e reabertura.
- `tests/test_mobile_delivery_history.py`: historico mobile considerando devolucoes.
- `tests/test_mobile_hub.py`: priorizacao e montagem da home mobile.
- `tests/test_delivery_projection.py`: ETA e severidade das rotas.
- `tests/test_delivery_returns_metrics.py`: metrica de devolucao e gamificacao.
- `tests/test_bi_clientes_dataset.py`: dataset de BI por cliente.
- `tests/test_bi_delivery_financial_consolidation.py`: KPI financeiro do BI delivery.
- `tests/test_admin_cleanup_checklists.py`: limpeza administrativa de checklists.
- `tests/test_finish_route.py`: idempotencia e estados de conclusao de rota.
- `tests/test_render_env_validation.py`: validacao de ambiente Render.
- `tests/test_copy_postgres_data.py`: copia de dados entre bancos.
- `tests/test_employees_seller_code.py`: seller code de colaboradores.

Lacunas aparentes:

- Pouca cobertura de UI server-rendered.
- Poucos testes de integracao ponta-a-ponta para auth/sessao.
- `main.py` concentra muita logica que hoje depende mais de validacao manual e testes indiretos.

## 10. Observacoes Importantes para Outra IA

### 10.1 Fonte da verdade

Se outra IA for trabalhar neste repositorio, a ordem de confianca recomendada e:

1. `main.py`
2. `models.py`
3. `database.py`
4. modulos de rotas especializados
5. templates efetivamente renderizados
6. scripts e docs historicos

### 10.2 Pontos que merecem cautela

- `README.md` nao descreve todo o estado atual do sistema.
- `main.py` e o centro real do dominio; muitos fluxos importantes nao foram totalmente extraidos para modulos.
- Existem arquivos historicos/stale que podem confundir uma IA.
- Nem todo template e localizado por busca simples, porque alguns sao escolhidos dinamicamente por variavel.
- O sistema mistura pagina server-rendered, fetch incremental e APIs JSON no mesmo fluxo.
- O boot local pode falhar se `DATABASE_URL` remoto estiver configurado e indisponivel; usar `FORCE_LOCAL_DB=true`.

### 10.3 Anomalias tecnicas encontradas no scan

- `operational_history_routes.py` parece uma copia antiga/inconsistente do que hoje vive em `main.py`; nao trate esse arquivo como modulo ativo confiavel.
- A rota `/employees` contem um trecho com `user = "debug_admin"` em vez de `require_login(request)`, o que sugere vestigio de debug/hardcode e merece atencao se a proxima IA for mexer em autenticacao/seguranca.
- `mobile/api/ai/today` ainda parece placeholder simples, nao um fluxo de IA robusto.
- A dependencia `openai` existe, mas a integracao de IA encontrada em uso e Gemini.

## 11. Resumo Pronto para Colar em Outra IA

```text
Projeto FastAPI monolitico de operacao/logistica com desktop + mobile PWA.
Fonte principal: main.py (29k+ linhas), models.py (60 modelos), database.py.
Dominios principais: dashboard executivo, painel TV, separacao/entregas, devolucoes, smart flow, portaria, checklists/equipamentos, BI, gamificacao, clientes, colaboradores, frota, documentos institucionais e turnover com Gemini.
Frontend: Jinja2 + Tailwind compilado + CSS proprios + JS modular por pagina.
Autenticacao: sessao administrativa e sessao mobile de colaborador.
Banco: PostgreSQL remoto ou SQLite local; se DATABASE_URL remoto falhar, usar FORCE_LOCAL_DB=true.
Arquivos ativos alem de main.py: bi_delivery_routes.py, bi_motorista_routes.py, devolucoes_routes.py, devolucoes_service.py, documentos_routes.py, escalas_routes.py, game_achievements_routes.py, game_audit_routes.py, routers/admin_geocoding.py, services/geocoding_service.py, utils/mobile_hub.py, utils/delivery_projection.py, route_duration.py, client_import_utils.py.
Arquivos que nao devem ser tratados como fonte principal: patch_*.py, routes_to_append.py, operational_history_routes.py, find_string.py, tmp_*, diff.txt.
```

## 12. Conclusao

Este nao e um projeto pequeno nem puramente API-first no sentido estrito. Ele e um sistema operacional completo, com uma grande quantidade de regras de negocio embarcadas no backend, interfaces especializadas para escritorio e mobile, e varios subdominios que se alimentam do mesmo conjunto de entidades centrais: colaboradores, rotas, clientes, entregas, devolucoes e sessoes operacionais.

Para qualquer IA futura trabalhar bem aqui, ela precisa partir de `main.py` e `models.py`, entender que o mobile e fortemente orientado por flags de acesso no cadastro do colaborador, e distinguir com cuidado o que e runtime vivo do que e artefato historico.
