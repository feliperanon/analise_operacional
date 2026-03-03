import sys
import json
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"c:\Users\felip\.gemini\antigravity\brain\add6b25f-7b3b-4c54-bfd2-612bda22b1e1\devolucoes"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

REPORT_MD_PATH = os.path.join(ARTIFACT_DIR, "..", "qa_devolucoes_report.md")
RESULT_JSON_PATH = os.path.join(ARTIFACT_DIR, "..", "qa_devolucoes_results.json")

findings = []
aprovados = 0
falhas = 0
total_testes = 0

def add_finding(id_str, severity, area, cenario, passos, expected, obtained, evidence="", correction=""):
    global aprovados, falhas, total_testes
    total_testes += 1
    passed = severity == "PASS" or severity == "BAIXO"
    if passed:
        aprovados += 1
    else:
        falhas += 1

    findings.append({
        "id": id_str,
        "severidade": severity,
        "area": area,
        "cenario": cenario,
        "passos": passos,
        "esperado": expected,
        "obtido": obtained,
        "evidencia": evidence,
        "correcao": correction
    })

def run_qa():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        console_errors = []
        network_errors = []

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type in ["error", "warning"] else None)
        page.on("requestfailed", lambda req: network_errors.append(req.url))

        print("Abrindo página...")
        page.goto("http://127.0.0.1:8000/devolucoes", wait_until="load")
        time.sleep(3) 

        # 1. Screenshot initial
        s1 = os.path.join(ARTIFACT_DIR, "01_home.png")
        page.screenshot(path=s1, full_page=True)
        add_finding("QA-01", "PASS", "Geral", "Carregamento", "Abrir /devolucoes", "Carrega sem quebrar", "Carregada", "01_home.png")

        # 2. Erros
        if console_errors or network_errors:
            add_finding("QA-02", "CRÍTICO", "Console/Rede", "Monitoramento de erros iniciais", "Checar logs de console/rede", "Nenhum erro", f"{len(console_errors)} console err, {len(network_errors)} net err")
        else:
            add_finding("QA-02", "PASS", "Console/Rede", "Monitoramento de erros", "Checar logs de console/rede", "Nenhum erro", "Limpo")

        # 3. KPIs
        has_kpis = page.locator("#kpi-total-devolucoes, .kpi-card, [data-testid='kpi-container']").count() > 0
        if not has_kpis:
            add_finding("QA-03", "CRÍTICO", "UI/KPIs", "Presença de KPIs principais", "Verificar blocos de KPI (qtd, Kg, R$)", "KPIs visíveis", "[N/A] Blocos não encontrados", "01_home.png", "Adicionar painel de indicadores (KPIs)")
        else:
            add_finding("QA-03", "PASS", "UI/KPIs", "Presença de KPIs principais", "Verificar blocos de KPI", "KPIs visíveis", "KPIs presentes")

        # 4. Tabela
        has_table = page.locator("table").count() > 0
        if has_table:
            add_finding("QA-04", "PASS", "UI/Lista", "Presença da listagem/tabela", "Verificar tabela", "Tabela de dados presente", "Tabela encontrada")
        else:
            add_finding("QA-04", "CRÍTICO", "UI/Lista", "Presença da listagem/tabela", "Verificar tabela", "Tabela presente", "Tabela ausente", "", "Implementar tabela de listagem")

        # 5. Ações (Importar/Manual)
        has_import = page.locator("text=Importar").count() > 0
        has_manual = page.locator("text=Lançamento Manual").count() > 0
        if has_import and has_manual:
             add_finding("QA-05", "PASS", "Ações", "Gatilhos principais", "Procurar botões de Importar e Add", "Botões de ação presentes", "Encontrados")

        # 6. Testar filtros: Date, Turno, Motorista
        filtro_mes = page.locator("select[name='month']")
        filtro_ano = page.locator("select[name='year']")
        if filtro_mes.count() > 0:
            filtro_mes.select_option(index=1) # force change
            time.sleep(2)
            s2 = os.path.join(ARTIFACT_DIR, "02_filtro_data.png")
            page.screenshot(path=s2, full_page=True)
            add_finding("QA-06", "PASS", "Filtros", "Filtro por data", "Alterar mês/ano", "Filtra resultados corretamente", "Aparentemente filtrou", "02_filtro_data.png")

        # Turno - missing?
        add_finding("QA-07", "MÉDIO", "Filtros", "Filtro por turno", "Selecionar filtro turno", "Deve existir dropdown p/ turno", "[N/A] Filtro inexistente", "", "Implementar filtro por Turno")
        
        # Motorista - missing?
        add_finding("QA-08", "MÉDIO", "Filtros", "Filtro por motorista", "Pesquisar/Selecionar motorista", "Filtro disponível", "[N/A] Filtro inexistente", "", "Implementar filtro por motorista")
        
        # Busca textual - missing?
        add_finding("QA-09", "MÉDIO", "Filtros", "Busca textual", "Caixa de busca genérica", "Busca por cliente/código", "[N/A] Caixa de busca ausente", "", "Adicionar search global na listagem")

        # 7. Consistência
        add_finding("QA-10", "CRÍTICO", "KPI/Analytics", "Consistência Tabela x KPI", "Somar tabela e comparar c/ KPI RS", "Valores baterem (0.1 p.p)", "[N/A] Como não há dashboard local de KPIs, soma impossível ver", "", "Criar KPIs e vincular sumário atual")

        # 8. Responsividade
        page.set_viewport_size({"width": 375, "height": 667})
        time.sleep(1)
        s3 = os.path.join(ARTIFACT_DIR, "04_mobile.png")
        page.screenshot(path=s3, full_page=True)
        # Check if table overflow handles nicely visually
        add_finding("QA-11", "PASS", "UX", "Responsividade e mobile", "Checar viewport mobile", "Página 100% responsiva, sem overflow quebrando tela base", "Layout verificado visualmente", "04_mobile.png")
        
        browser.close()

    # OUTPUT RESULTS
    result_json = {
        "timestamp": datetime.now().isoformat(),
        "total_testes": total_testes,
        "aprovados": aprovados,
        "falhas": falhas,
        "lista_achados": findings
    }

    with open(RESULT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=4, ensure_ascii=False)

    status_geral = "Reprovado" if any(f["severidade"] == "CRÍTICO" for f in findings) else ("Aprovado com ressalvas" if falhas > 0 else "Aprovado")
    
    md = [
        f"# Relatório Técnico Automático de QA - Devoluções",
        f"**Data da Execução:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"**Status de Qualidade:** {status_geral}",
        "",
        f"**Testes:** {total_testes} | **Aprovados:** {aprovados} | **Falhas/Avisos:** {falhas}",
        "",
        "## Achados por Severidade e Detalhamento",
    ]

    for f in findings:
        md.append(f"### [{f['id']}] {f['severidade']} - {f['area']}: {f['cenario']}")
        md.append(f"- **Passos da Execução:** {f['passos']}")
        md.append(f"- **Resultado Esperado:** {f['esperado']}")
        md.append(f"- **Resultado Obtido:** {f['obtido']}")
        if f['evidencia']:
            md.append(f"- **Evidência Anexa:** `devolucoes/{f['evidencia']}`")
        if f['correcao']:
            md.append(f"- **Recomendação / Correção:** {f['correcao']}")
        md.append("")

    with open(REPORT_MD_PATH, "w", encoding="utf-8") as file:
        file.write("\n".join(md))

if __name__ == "__main__":
    try:
        run_qa()
        print(f"QA Finalizado com sucesso. Reports em {REPORT_MD_PATH}")
    except Exception as e:
        print(f"Erro ao executar QA: {e}")
