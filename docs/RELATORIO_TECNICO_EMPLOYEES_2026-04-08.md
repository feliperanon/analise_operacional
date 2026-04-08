# Relatório Técnico Completo da Página /employees

Data da análise: 2026-04-08
Ambiente analisado: http://127.0.0.1:8000/employees
Página analisada: Colaboradores · Gestão Avista

## 1. Objetivo do relatório

Este documento descreve, com base em inspeção real da página em execução e leitura direta do código-fonte, tudo o que está sendo utilizado na página /employees em termos de:

- tecnologias e ferramentas
- arquitetura de backend e frontend
- padrão de implementação
- layout e composição visual
- sistema de design
- tipografia, pesos, escalas e comportamento responsivo
- interações, filtros, modais e fluxo de dados
- observações estruturais e inconsistências encontradas

O foco deste relatório é técnico e factual. Nada abaixo foi inferido sem evidência em código ou na renderização real.

## 2. Resumo executivo

A página /employees é uma tela SSR híbrida dentro de um monólito Python, construída com FastAPI no backend, Jinja2 na camada de renderização HTML e SQLModel/SQLAlchemy no acesso a dados. No frontend, o projeto combina Tailwind CSS compilado, um design system próprio em CSS por camadas, Alpine.js para microinterações pontuais e JavaScript inline em estilo Vanilla JS para filtros, ordenação, modais, importações em lote e chamadas fetch.

A arquitetura da tela segue um padrão que pode ser descrito como server-rendered com progressive enhancement:

- o backend monta os dados principais da página antes da renderização
- o template entrega a estrutura completa já funcional
- o JavaScript adiciona comportamento rico no cliente sem depender de um framework SPA
- as ações usam mistura de formulários HTML tradicionais e chamadas AJAX/fetch

Visualmente, a página pertence ao ecossistema Gestão Avista, usando base TailAdmin/Tailwind com uma camada autoral de design tokens e componentes de sistema. A composição é fortemente orientada a operação: hero executivo, KPIs clicáveis, barra de filtros, tabela operacional, modais de manutenção e visão agrupada por empresa.

## 3. Stack e tecnologias confirmadas

### 3.1 Backend

Dependências confirmadas em requirements.txt:

- FastAPI 0.128.0
- Uvicorn 0.40.0
- SQLModel 0.0.31
- SQLAlchemy 2.0.45
- Pydantic 2.12.5
- Jinja2 3.1.6
- python-multipart 0.0.21
- pandas 2.3.3
- openpyxl 3.1.5
- xlrd 2.0.2
- psycopg2-binary 2.9.11
- python-dotenv 1.2.1
- reportlab 4.2.2
- httpx e openai presentes no projeto

Conclusão técnica:

- backend Python moderno
- API e HTML servidos pelo mesmo aplicativo FastAPI
- camada ORM com SQLModel sobre SQLAlchemy
- suporte a importação de Excel nativo no fluxo operacional
- capacidade de integração com PostgreSQL em produção

### 3.2 Frontend

Dependências e assets confirmados:

- Tailwind CSS 3.4.17
- PostCSS 8.4.49
- Autoprefixer 10.4.20
- TailAdmin CSS vendor
- Alpine.js 3.14.3
- Lucide 0.563.0 para ícones
- CSS autoral do sistema: system-tokens, system-layout, system-components, system-utilities
- CSS específico da página: static/css/pages/employees.css

Scripts do package.json:

- build:css usando Tailwind CLI
- watch:css para desenvolvimento

Conclusão técnica:

- o frontend não usa React, Vue ou outro framework SPA nesta tela
- o projeto usa HTML server-side com enriquecimento via JavaScript nativo
- o pipeline CSS é compilado, mas a página depende também de CSS autoral fora da camada Tailwind utilitária

## 4. Arquitetura da tela /employees

### 4.1 Padrão arquitetural predominante

O padrão real da página é SSR híbrido com progressive enhancement.

Isso significa:

- a rota /employees monta os dados no servidor
- o template employees.html recebe coleções prontas para renderização
- a primeira pintura já sai completa, sem depender de chamada API para desenhar a página inteira
- interações posteriores usam JS local e fetch para ações pontuais

Não é uma SPA.
Não é um frontend desacoplado.
Também não é HTML puro e estático.

É um modelo híbrido, bastante pragmático para software operacional.

### 4.2 Backend da página

A rota principal está em main.py e segue este fluxo:

1. Atualiza status automáticos de férias com base na data atual.
2. Busca colaboradores não substituídos.
3. Busca também demitidos substituídos para que possam aparecer no filtro de demitidos.
4. Busca metas de quadro por centro de custo.
5. Consolida headcount efetivo, férias, afastamentos e vagas.
6. Monta estatísticas por centro com tema visual associado.
7. Calcula status globais de férias, afastados e demitidos.
8. Carrega cargos ativos para formulários de cadastro e edição.
9. Renderiza o template employees.html com todos os dados.

Essa decisão revela um backend orientado a view-model: a rota já prepara a informação no formato ideal para a tela.

### 4.3 Estrutura de camadas envolvidas

Camadas identificadas na renderização:

- FastAPI como orquestrador HTTP
- Jinja2Templates para SSR
- SQLModel/Session para consulta e persistência
- design system compartilhado para componentes base
- CSS específico da página para skin, layout e responsividade fina
- JS inline na própria view para lógica da página

### 4.4 Base de layout

employees.html estende base_gestao_avista.html.

A base carrega:

- styles.css
- vendor/tailadmin/style.css
- dashboard-tailadmin.css
- system-tokens.css
- system-layout.css
- system-components.css
- system-utilities.css
- gestao-avista-page.css
- lucide.js
- alpine.js

Ou seja, a página /employees não vive isolada. Ela se apoia em uma infraestrutura de UI mais ampla do sistema.

## 5. Ferramentas e bibliotecas efetivamente usadas na tela

### 5.1 FastAPI

Usada para:

- servir HTML via HTMLResponse
- servir APIs JSON da página
- tratar uploads e POSTs de formulário
- organizar endpoints de cadastro, férias, metas e importação

### 5.2 Jinja2

Usada para:

- herança de layout
- loops de KPIs e linhas da tabela
- injeção de dados estatísticos
- montagem de atributos data-* consumidos pelo JavaScript
- serialização do objeto do colaborador para uso direto em botões e modais

### 5.3 SQLModel/SQLAlchemy

Usado para:

- consultas de Employee, HeadcountTarget e CargoMaster
- filtros por status e substituição
- composição de estatísticas operacionais

### 5.4 Tailwind CSS

Usado como base utilitária em larga escala na marcação HTML:

- spacing com classes px, py, gap, mt, pt
- layout flex e grid
- tipografia utilitária
- rounded, shadow, border, responsive utilities
- dark:* classes espalhadas pelo template

### 5.5 TailAdmin

O projeto importa explicitamente a folha vendor/tailadmin/style.css.

Papel observado:

- base visual do dashboard
- tokens próprios do vendor
- importação da fonte Outfit do Google Fonts
- classes e convenções herdadas do ecossistema admin template

### 5.6 Alpine.js

Usado de forma pontual, não estrutural.

Na página /employees, o uso confirmado aparece principalmente no dropdown de importação:

- x-data
- @click
- x-show
- @click.away
- x-transition

Conclusão:

- Alpine.js atua como microframework de interações simples
- não gerencia o estado principal da página

### 5.7 Vanilla JavaScript

É a principal tecnologia comportamental da tela.

Usado para:

- ordenação de tabela
- filtros por status, busca e função
- montagem dinâmica da visão agrupada
- abertura e fechamento de modais
- chamadas fetch para APIs
- importações em lote
- máscaras de telefone
- leitura de data-* attributes como contrato entre HTML e JS

### 5.8 Lucide

Biblioteca de ícones carregada globalmente. Na página, há grande uso de SVG inline, o que indica uma abordagem mista:

- SVG embutido para ícones específicos de fluxo
- Lucide disponível para necessidades globais do sistema

## 6. Layout e composição visual da página

### 6.1 Estrutura macro da interface

A página está organizada em cinco blocos principais:

1. cabeçalho institucional da aplicação
2. hero executivo da página
3. linha de KPIs clicáveis
4. barra operacional de filtros
5. painel principal com tabela de colaboradores

Além disso, a tela contém vários modais operacionais:

- metas de quadro
- novo colaborador
- edição de colaborador
- importação de ocorrências
- atualização em massa de centro de custo
- programação de férias
- importação em lote de férias
- demissão
- retorno/reactivação

### 6.2 Cabeçalho

O cabeçalho superior do shell contém:

- breadcrumb operacional
- título principal Colaboradores
- subtítulo contextual da tela

Esse cabeçalho é sticky e faz parte do layout global.

### 6.3 Hero executivo

O hero é uma peça de dashboard premium com:

- ícone circular destacado
- eyebrow em caixa alta
- título principal da página
- texto de apoio
- chips de resumo rápido
- CTA de importação com menu dropdown
- CTA primário para novo cadastro

Linguagem visual do hero:

- superfície clara com degradê suave
- brilhos decorativos desfocados
- bordas suaves e sombra leve/elevada
- composição pensada para transmitir controle operacional e maturidade visual

### 6.4 KPIs

Os cards KPI são interativos e servem como filtros de contexto.

Itens encontrados na página em execução:

- Quadro
- Souza Pinto
- Exemplar
- Sem Centro
- Férias
- Afastados
- Demitidos

Características:

- o KPI não é apenas leitura, ele é mecanismo de navegação contextual
- cada card tem cor semântica própria
- há ênfase numérica com tabular nums
- cartões funcionam como atalhos operacionais

### 6.5 Barra de filtros

A barra contém:

- label de busca
- campo de pesquisa por nome, matrícula ou função
- dropdown de funções com múltipla seleção
- botão Ver todos
- link direto para Substituições

Padrão de UX:

- uma faixa operacional horizontal
- bloco primário à esquerda e bloco secundário à direita
- overflow-x controlado na faixa interna
- desenho otimizado para uso real em telas menores

### 6.6 Painel da tabela

O painel da tabela é apresentado como card de superfície do design system e traz:

- kicker Cadastro ativo
- título Lista de colaboradores
- texto auxiliar explicando comportamento em mobile
- observação de negócio sobre demitidos não aparecerem por padrão
- tabela com cabeçalho sticky e colunas ordenáveis

Colunas confirmadas:

- Colaborador
- Matrícula
- Cargo
- Empresa
- Horário
- Status
- Ações

### 6.7 Visão agrupada por empresa

O JavaScript implementa um modo agrupado por empresa, com cards de empresa e avatares dos colaboradores. Isso é gerado dinamicamente no cliente a partir das mesmas linhas já renderizadas na tabela.

Ponto relevante:

- a estrutura da visão agrupada existe no JavaScript
- o agrupamento usa groupedCenterConfigs vindo do backend
- os dados são reaproveitados do DOM existente
- isso evita round-trip extra para o servidor

## 7. Sistema de design e padrões visuais

### 7.1 Design system próprio

O projeto possui um design system real, não apenas um conjunto solto de utilitários.

Arquivos-base:

- system-tokens.css
- system-layout.css
- system-components.css
- system-utilities.css

Essa estrutura indica:

- separação entre token, layout, componente e utilitário
- padronização evolutiva
- tentativa clara de institucionalização visual

### 7.2 Tokens de design confirmados

O arquivo system-tokens.css define:

- espaçamentos oficiais baseados em 4px
- alturas de controle oficiais
- raios de borda
- sombras padronizadas
- paleta operacional
- estados semânticos
- tipografia sistêmica

Tokens importantes:

- --sys-control-height: 44px
- --sys-radius-lg: 12px
- --sys-radius-xl: 16px
- --sys-font-sans: Outfit, ui-sans-serif, system-ui, sans-serif
- --sys-text-xs: 11px
- --sys-text-sm: 13px
- --sys-text-base: 14px
- --sys-text-md: 16px
- --sys-text-lg: 18px

### 7.3 Paleta observada

Paleta-base do sistema:

- fundo claro operacional em tons de slate muito claros
- superfícies brancas
- texto principal em azul-ardósia escuro
- accent institucional em tons de sky/cyan
- semântica com verde para ok, âmbar para alerta e vermelho para crítico
- azul/índigo como cor de ação principal

Na página /employees isso aparece como:

- hero com fundo degradê claro
- CTA primário em índigo
- chips e badges com semântica operacional
- KPIs coloridos por tipo de informação

### 7.4 Padrões de componente

Classes de padrão encontradas:

- sys-card
- sys-btn
- sys-alert
- sys-input
- sys-select
- sys-section-heading
- sys-kpi-card
- sys-table-wrap

Isso mostra que a tela usa composição híbrida:

- system components como base
- classes específicas de employees como skin/contexto
- utilidades Tailwind como ajuste fino direto no HTML

### 7.5 Naming conventions

O padrão de nomenclatura é consistente e relativamente maduro:

- prefixo sys- para design system compartilhado
- prefixo employees- para contexto da página
- prefixo ga- para tema Gestão Avista
- prefixo emp- para alguns componentes de modal/toggle
- prefixo ops- para certos elementos de toolbar/card operacional

Esse padrão ajuda a separar escopo visual e responsabilidade.

## 8. Tipografia, tamanhos e fontes

### 8.1 Fonte declarada pelo design system

O design system declara Outfit como fonte sans principal via token:

- --sys-font-sans: Outfit, ui-sans-serif, system-ui, sans-serif

O vendor TailAdmin também importa Outfit do Google Fonts.

### 8.2 Fonte realmente renderizada

Na inspeção computada da página em execução, a maior parte da interface está renderizando em Inter, não em Outfit.

Valores medidos diretamente no navegador:

- body: Inter, 16px, 400, line-height 24px
- h1 do header: Inter, 20px, 700, line-height 28px
- título do hero: Inter, 24px, 700, line-height 28.8px
- texto de apoio do hero: Inter, 14px, 400, line-height 20.3px
- valor de KPI: Inter, 18.4px, 700, line-height 18.4px
- label Busca: Inter, 11px, 700, line-height 16.5px
- input de busca: Inter, 14px, 500, line-height 21px
- header da tabela: Inter, 11px, 600, line-height 20px
- célula da tabela: Inter, 13px, 500, line-height 20px
- botão Novo Colaborador: Outfit, 14px, 600, line-height 14px

### 8.3 Causa da divergência tipográfica

O arquivo styles.css contém uma regra global de body com:

- font-family: Inter, system-ui, -apple-system, sans-serif

Isso está sobrescrevendo a expectativa de Outfit na maior parte da renderização. Resultado prático:

- o sistema declara Outfit como fonte oficial
- a página roda majoritariamente em Inter
- alguns componentes específicos, como botão primário com classe font-outfit/sys-btn, ainda aparecem em Outfit

### 8.4 Leitura crítica dessa decisão

Essa divergência cria um cenário híbrido:

- identidade declarada: Outfit
- identidade percebida no conteúdo: Inter
- identidade pontual em CTAs: Outfit

Do ponto de vista de branding e consistência, isso é um detalhe importante. Não quebra a UI, mas mostra conflito de camadas tipográficas.

### 8.5 Escala tipográfica funcional da tela

Escala observada e/ou declarada:

- 10px em auxiliares muito finos dentro de modais
- 11px em labels, head de tabela e microcopy operacional
- 13px em corpo compacto da tabela
- 14px em inputs, botões e texto-base da página
- 16px na base do body renderizado
- 18px em KPIs e subtítulos maiores
- 20px no título principal do header
- 24px no título do hero

Isso caracteriza uma interface densa, operacional e orientada a produtividade, com forte compressão de conteúdo sem cair em ilegibilidade severa.

## 9. Medidas visuais e características computadas

Viewport inspecionado:

- largura: 880px
- altura: 679px
- devicePixelRatio: 1.25

Botão primário Novo Colaborador:

- fonte: Outfit
- tamanho: 14px
- peso: 600
- fundo: rgb(79, 70, 229)
- radius: 12px
- sombra dupla azul/índigo

Body:

- fonte: Inter
- fundo computado escuro global herdado do styles.css
- texto base: rgb(51, 65, 85)

Observação:

- embora o body global tenha fundo escuro em styles.css, o shell da aplicação recompõe a área principal com camadas claras, então a percepção final da página é de dashboard claro sobre infraestrutura de body escuro

## 10. Responsividade e comportamento adaptativo

### 10.1 Breakpoints encontrados

O CSS da página possui media queries confirmadas em pontos como:

- min-width: 640px
- max-width: 520px
- max-width: 420px
- min-width: 768px
- max-width: 767px

### 10.2 Estratégia responsiva

A estratégia não é simplesmente encolher a tabela. Ela combina:

- overflow horizontal controlado
- reestruturação de barras e grids
- adaptação de espaçamento
- densidade variável por breakpoint
- transformação conceitual da lista em card em telas menores, conforme texto explicativo da própria tela

### 10.3 Evidências de responsividade pensada

- filtro em faixa horizontal com scroll interno
- hero com empilhamento flexível xl e sm
- grids sm, md, lg, xl na visão agrupada
- modais com max-height e overflow-y auto
- tabela encapsulada em sys-table-wrap com scroll horizontal
- presença de regras dedicadas a breakpoints abaixo de 767px

### 10.4 Qualidade da abordagem

A abordagem responsiva da tela é operacional e pragmática. Ela não tenta esconder a complexidade do domínio. Em vez disso, redistribui a informação conforme o espaço disponível.

Esse é o comportamento correto para software interno de gestão com alto volume de dados.

## 11. Padrões de implementação frontend

### 11.1 DOM como fonte operacional rica

Cada linha de colaborador carrega data-* attributes com bastante informação:

- nome
- matrícula
- empresa
- status
- cargo normalizado
- payload completo serializado do colaborador

Isso permite que o JS:

- filtre sem nova consulta ao backend
- ordene no cliente
- abra modais com dados já disponíveis
- monte a visão agrupada reaproveitando os dados do DOM

É um padrão muito eficiente para SSR enriquecido.

### 11.2 Mistura de interações síncronas e assíncronas

A tela mistura três mecanismos:

- formulários POST tradicionais
- fetch para APIs JSON
- manipulação DOM local

Exemplos:

- adicionar/editar com form submission
- salvar metas com fetch POST JSON
- férias em lote com fetch
- filtros e ordenação totalmente client-side

### 11.3 Padrão de modal

Os modais seguem padrão relativamente consistente:

- wrapper fixed inset-0
- controle por hidden/remove hidden
- card central com sys-card
- backdrop separado
- footer com botões de ação
- conteúdo com scroll próprio quando necessário

### 11.4 Padrão de estado visual

Estados visuais encontrados:

- alert success, info, danger
- badge semântico
- CTA aberto/fechado
- card selecionado no KPI
- status por cores e chips
- toggles e checkboxes de permissão

### 11.5 Padrão de microinteração

Microinterações observadas:

- hover com sombra e leve translateY no CTA principal
- rotação de chevron no menu de importação
- sticky header da tabela
- animação pulse em estados que pedem atenção
- transições de hover em cards e linhas

## 12. Padrões de implementação backend para esta tela

### 12.1 View-model montado no servidor

A rota entrega um objeto stats bastante preparado, incluindo:

- total_active
- total_target
- vacancies
- total_away
- centers
- statuses
- targets_map

Isso mostra um backend orientado ao consumo direto da view, evitando lógica pesada de agregação no cliente.

### 12.2 Regras de negócio incorporadas à página

Regras de negócio detectadas:

- demitidos substituídos ainda aparecem no contexto certo
- afastados contam como demanda de cobertura
- férias entram no headcount efetivo
- demitidos não aparecem por padrão na lista principal
- metas por centro influenciam KPIs e saldo

### 12.3 Endpoints relacionados à página

Endpoints confirmados no entorno da tela:

- GET /employees
- POST /api/employees/targets
- GET /employees/candidates
- POST /employees/add
- GET /employees/{employee_id}
- POST /employees/{emp_id}/status
- POST /employees/{emp_id}/return
- POST /employees/{emp_id}/update
- POST /employees/import
- POST /employees/vacation
- POST /employees/vacation/bulk
- POST /api/employees/bulk-cost-center-all
- POST /api/employees/bulk-cost-center
- POST /api/employees/bulk-cost-center-from-file

Isso confirma que a página é um hub operacional completo, não uma simples listagem.

## 13. UX e linguagem de produto

### 13.1 Natureza da tela

A tela foi desenhada para operação administrativa real. Ela não tem linguagem de marketing nem comportamento de catálogo. Ela é um cockpit de cadastro e manutenção.

### 13.2 Sinais de software operacional maduro

- textos orientados a ação
- dados resumidos logo no topo
- filtros práticos
- atalhos para lote
- observações de negócio embutidas na UI
- várias rotinas administrativas reunidas na mesma página

### 13.3 Layout e densidade

A densidade visual é relativamente alta, mas controlada por:

- hierarquia tipográfica compacta
- cards bem delimitados
- bastante uso de whitespace entre blocos macro
- textos auxiliares em tamanho pequeno porém consistente

## 14. Observações importantes encontradas

### 14.1 Divergência de fonte entre design system e renderização real

Este é o principal achado técnico visual:

- o design system diz Outfit
- a maioria da página está em Inter
- botões específicos continuam em Outfit

Isso indica conflito entre camadas globais de CSS.

### 14.2 Hooks de interface aparentemente incompletos ou órfãos

O JavaScript referencia elementos como:

- visibleEmployeesCounter
- view-toggle-btn

Mas a busca no template indica que esses hooks aparecem no script e não na marcação principal localizada nesta análise. Isso sugere uma destas hipóteses:

- a feature existia e parte da UI foi removida sem limpar todo o JS
- a UI correspondente está em trecho não exibido no topo da página, mas não apareceu nos pontos de uso esperados
- há dívida técnica pequena de manutenção de script residual

Não parece crítico, mas merece nota.

### 14.3 Mistura de paradigmas sem problema imediato

A tela mistura:

- Alpine.js
- JS inline
- formulários clássicos
- fetch
- utilitários Tailwind
- classes de design system

Isso pode parecer heterogêneo, mas nesta página específica o resultado é funcional. O custo maior é manutenção e consistência, não desempenho imediato.

## 15. Avaliação técnica da arquitetura usada na página

### 15.1 Pontos fortes

- ótima performance de primeira renderização por SSR
- pouca dependência de framework pesado no cliente
- backend entrega dados já consolidados
- design system real, não improvisado
- boa separação entre base global e skin de página
- excelente adequação ao contexto operacional
- importações em lote e fluxos administrativos incorporados na mesma tela

### 15.2 Trade-offs

- JavaScript inline grande dentro do template dificulta escalabilidade
- a tipografia está inconsistente entre intenção do sistema e resultado real
- a mistura de padrões pode aumentar custo cognitivo para manutenção futura
- a tela concentra muitas responsabilidades de negócio

### 15.3 Classificação arquitetural prática

Se eu tivesse que classificar a página em uma frase, seria:

"Tela administrativa SSR avançada, com progressive enhancement, design system próprio e JavaScript operacional orientado ao DOM."

## 16. Inventário consolidado do que está sendo usado

### 16.1 Tecnologias

- Python
- FastAPI
- Jinja2
- SQLModel
- SQLAlchemy
- Pydantic
- Pandas
- OpenPyXL
- XLRD
- PostgreSQL via psycopg2-binary
- Tailwind CSS
- PostCSS
- Autoprefixer
- Alpine.js
- Lucide
- TailAdmin
- Vanilla JavaScript
- Fetch API
- Google Fonts via import do vendor

### 16.2 Ferramentas e padrões de frontend

- SSR com templates
- utilitários Tailwind no HTML
- CSS modular por camadas
- tokens de design globais
- classes contextuais da página
- data attributes como contrato entre HTML e JS
- modais baseados em classes hidden
- ordenação client-side
- filtro client-side
- agrupamento client-side reaproveitando DOM

### 16.3 Ferramentas e padrões de backend

- roteamento central em main.py
- sessão de banco via dependency injection
- construção de view-model no servidor
- endpoints REST auxiliares para operações específicas
- retorno HTML e JSON no mesmo módulo de aplicação

## 17. Conclusão final

A página /employees é uma tela administrativa robusta, com arquitetura pragmática e adequada ao contexto de operação interna. O conjunto tecnológico combina backend moderno em FastAPI com renderização server-side, dados consolidados no servidor e enriquecimento progressivo no cliente. Visualmente, a tela já opera sobre um design system consistente e uma linguagem de dashboard premium-operacional.

Em termos de maturidade, a página está acima do nível de CRUD simples. Ela funciona como uma central de gestão do quadro de colaboradores, reunindo cadastro, status, férias, substituições, metas, importações e manutenção operacional em uma única experiência.

O principal ponto de atenção encontrado não é estrutural, e sim de consistência visual: a tipografia oficial declarada pelo sistema é Outfit, mas a maior parte da renderização efetiva está em Inter por conta de um override global em styles.css. Fora isso, a arquitetura está coerente com o tipo de produto, e o layout foi claramente desenhado para uso real em rotina administrativa, não apenas para demonstração estética.

## 18. Fontes de evidência usadas nesta análise

Arquivos inspecionados:

- main.py
- templates/base_gestao_avista.html
- templates/employees.html
- static/css/pages/employees.css
- static/css/system-tokens.css
- static/styles.css
- package.json
- requirements.txt

Inspeções em runtime:

- leitura estrutural da página em execução em http://127.0.0.1:8000/employees
- captura de estilos computados de elementos-chave
- verificação do viewport renderizado
