/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

export type Locale = 'en' | 'es' | 'pt'

export const translations = {
  en: {
    // ── Sidebar ────────────────────────────────────────────
    section_navigation: 'Navigation',
    section_workspace: 'Workspace',
    section_environment: 'Environment',
    section_mode: 'Mode',
    nav_home: 'Home',
    nav_chat: 'Chat',
    nav_artifacts: 'Artifacts',
    select_workspace: 'Select workspace…',
    sign_out: 'Sign out',
    language: 'Language',

    // ── HomePage — Hero ────────────────────────────────────
    hero_subtitle: 'Deterministic text-to-SQL powered by your SAP semantic layer.',
    status_connecting: 'Connecting…',
    status_unreachable: 'Orchestrator unreachable',
    stat_workspaces: 'Workspaces',
    stat_conversations: 'Conversations',

    // ── HomePage — Config cards ────────────────────────────
    card_active_workspace: 'Active Workspace',
    card_not_selected: 'Not selected',
    card_environment: 'Environment',
    card_env_dev: 'Development',
    card_env_prod: 'Production',
    card_env_dev_desc: 'Safe sandbox — no prod impact',
    card_env_prod_desc: 'Live production data',
    card_sql_mode: 'SQL Mode',

    // ── HomePage — Mode metadata ───────────────────────────
    mode_flash_label: 'Flash',
    mode_flash_desc: 'Fastest · RAG-based retrieval',
    mode_precise_label: 'Precise',
    mode_precise_desc: 'Deterministic · Semantic IR',
    mode_smart_label: 'Smart',
    mode_smart_desc: 'Graph RAG · Catalog-driven',

    // ── HomePage — Onboarding guide ───────────────────────
    guide_title: 'New here? Your first question in four steps',
    guide_full: 'Full guide',
    guide_step1: 'Pick a Workspace',
    guide_step2: 'Choose dev or prod',
    guide_step3: 'Select a SQL mode',
    guide_step4: 'Open Chat and ask in plain language',
    guide_modes_prefix: 'Modes:',
    guide_modes_body: 'Flash (fastest) · Precise (deterministic — the default) · Smart (catalog-driven). Try "total net sales by region last quarter" or "top 10 customers by revenue".',

    // ── HomePage — Feature cards ───────────────────────────
    feature_chat_title: 'Chat',
    feature_chat_desc: 'Ask questions in natural language. Receive SQL-powered answers, auto-generated charts, and persistent conversation history per workspace.',
    feature_chat_tag1: 'Streaming responses',
    feature_chat_tag2: 'Auto charts',
    feature_chat_tag3: 'Persistent history',
    feature_artifacts_title: 'Artifacts',
    feature_artifacts_desc: 'Generate polished business documents and analytical reports — executive briefs, detailed analyses, and data-first tables — driven by live SAP data.',
    feature_artifacts_tag1: 'Executive brief',
    feature_artifacts_tag2: 'Detailed report',
    feature_artifacts_tag3: 'Proposal format',

    // ── HomePage — Platform capabilities ──────────────────
    cap_section_title: 'Platform Capabilities',
    cap_text_to_sql: 'Text-to-SQL',
    cap_knowledge_graph: 'Knowledge Graph',
    cap_semantic_layer: 'Semantic Layer',
    cap_hybrid_search: 'Hybrid Search',
    cap_sap_native: 'SAP Native',
    cap_auto_charts: 'Auto Charts',
    cap_ai_reports: 'AI Reports',

    // ── Thread (empty state + composer) ───────────────────
    thread_empty_title: 'What would you like to know?',
    thread_empty_subtitle: 'Ask anything about your SAP data — sales, inventory, finance, or operations.',
    thread_chip1: 'Top 10 customers by revenue',
    thread_chip2: 'Sales orders this month',
    thread_chip3: 'Pending purchase orders',
    thread_composer_ph: 'Ask a question about your data…',
    thread_composer_footer: 'Results are generated from your SAP data via the Onibex semantic layer.',
    thread_scroll_bottom: 'Scroll to bottom',

    // ── ChatSidebar ────────────────────────────────────────
    sidebar_new_chat: 'New Chat',
    sidebar_no_chats: 'No chats yet',
    sidebar_select_workspace: 'Select a workspace',

    // ── ChatPage ───────────────────────────────────────────
    chat_select_workspace: 'Select a workspace in the sidebar before asking a question.',

    // ── ArtifactsPage ─────────────────────────────────────
    artifact_type_sales: 'Sales Report',
    artifact_type_inventory: 'Inventory Report',
    artifact_type_executive: 'Executive Summary',
    artifact_type_financial: 'Financial Report',
    artifact_type_custom: 'Custom',
    artifact_format_brief: 'Executive Brief',
    artifact_format_detailed: 'Detailed Report',
    artifact_format_tables: 'Data Tables',
    artifact_format_proposal: 'Proposal Format',
    artifact_format_dashboard: 'Dashboard',
    artifact_step_name_q: "Let's create a new artifact! How would you like to name it?",
    artifact_step_name_ph: 'e.g. Q1 Sales Report, Inventory Overview…',
    artifact_step_purpose_q: "Who is the audience and what's the purpose of this document?",
    artifact_step_purpose_ph: 'e.g. For the executive team, Q1 review meeting…',
    artifact_step_data_q: 'What data should this document focus on? Be specific — this drives the queries.',
    artifact_step_data_ph: 'e.g. Top 10 customers by revenue, Q1 2024, broken down by region…',
    artifact_step_format_q: 'What format do you prefer?',
    artifact_step_format_ph: 'Type or pick one below…',

    // ── ArtifactChatCreator UI ─────────────────────────────
    artifact_back_gallery: 'Back to gallery',
    artifact_new_artifact_header: 'New Artifact',
    artifact_generating_msg: 'Perfect! Generating your "{name}" now…',
    artifact_error_recovery: 'Something went wrong. You can try again or adjust your answers above.',
    artifact_composer_hint: 'Enter to send · Shift+Enter for new line',

    // ── Thinking messages ──────────────────────────────────
    artifact_thinking_0: 'Querying your data sources…',
    artifact_thinking_1: 'Weaving the narrative together…',
    artifact_thinking_2: 'Distilling insights from raw rows…',
    artifact_thinking_3: 'Drafting the executive summary…',
    artifact_thinking_4: 'Asking your SAP tables for the story…',
    artifact_thinking_5: 'Structuring the analytical framework…',
    artifact_thinking_6: 'Mining the semantic layer for context…',
    artifact_thinking_7: 'Translating data into business language…',
    artifact_thinking_8: 'Calibrating the narrative tone…',
    artifact_thinking_9: 'Building the document architecture…',
    artifact_thinking_10: 'Cross-referencing your business metrics…',
    artifact_thinking_11: 'Aligning facts with strategy…',

    // ── ArtifactViewer header ──────────────────────────────
    artifact_back: 'Back',
    artifact_copy: 'Copy',
    artifact_copied: 'Copied',
    artifact_download_excel: 'Download Excel',
    artifact_edit: 'Edit',
    artifact_cancel: 'Cancel',
    artifact_regenerate: 'Regenerate',
    artifact_regenerating: 'Regenerating…',

    // ── Edit panel ─────────────────────────────────────────
    artifact_label_name: 'Name',
    artifact_label_format: 'Format',
    artifact_label_purpose: 'Purpose / Audience',
    artifact_label_data_focus: 'Data Focus',
    artifact_label_sql_override: 'SQL Override',
    artifact_label_sql_hint: '— leave unchanged to let AI regenerate SQL from params above',
    artifact_label_sql_ph: '-- Paste custom SQL here, or leave as-is to let the AI regenerate it',
    artifact_applying: 'Applying…',
    artifact_apply_regenerate: 'Apply & Regenerate',

    // ── Tabs / dataset ─────────────────────────────────────
    artifact_tab_document: 'Document',
    artifact_tab_data: 'Data',
    artifact_no_datasets: 'No datasets available for this artifact.',

    // ── Gallery ────────────────────────────────────────────
    artifact_gallery_title: 'Artifacts',
    artifact_all_types: 'All types',
    artifact_new_btn: 'New artifact',
    artifact_search_ph: 'Search artifacts…',
    artifact_empty_title: 'No artifacts yet',
    artifact_empty_desc: 'Click "New artifact" to generate your first document.',
    artifact_no_match: 'No artifacts match your search.',
    artifact_edited_prefix: 'Edited',

    // ── SqlResultsBlock ────────────────────────────────────
    results_table: 'Table',
    results_chart: 'Chart',
    results_copy_answer: 'Copy answer',
    results_copy: 'Copy',
    results_copied: 'Copied',
    results_copy_sql: 'Copy SQL',
    results_sql_query: 'SQL Query',
    results_showing_rows: 'Showing {shown} of {total} rows',
  },

  es: {
    // ── Sidebar ────────────────────────────────────────────
    section_navigation: 'Navegación',
    section_workspace: 'Espacio de trabajo',
    section_environment: 'Entorno',
    section_mode: 'Modo',
    nav_home: 'Inicio',
    nav_chat: 'Chat',
    nav_artifacts: 'Artefactos',
    select_workspace: 'Seleccionar espacio…',
    sign_out: 'Cerrar sesión',
    language: 'Idioma',

    // ── HomePage — Hero ────────────────────────────────────
    hero_subtitle: 'Text-to-SQL determinístico potenciado por tu capa semántica SAP.',
    status_connecting: 'Conectando…',
    status_unreachable: 'Orquestador no disponible',
    stat_workspaces: 'Espacios',
    stat_conversations: 'Conversaciones',

    // ── HomePage — Config cards ────────────────────────────
    card_active_workspace: 'Espacio activo',
    card_not_selected: 'Sin seleccionar',
    card_environment: 'Entorno',
    card_env_dev: 'Desarrollo',
    card_env_prod: 'Producción',
    card_env_dev_desc: 'Entorno seguro — sin impacto en producción',
    card_env_prod_desc: 'Datos reales de producción',
    card_sql_mode: 'Modo SQL',

    // ── HomePage — Mode metadata ───────────────────────────
    mode_flash_label: 'Flash',
    mode_flash_desc: 'Más rápido · Recuperación RAG',
    mode_precise_label: 'Preciso',
    mode_precise_desc: 'Determinístico · IR semántico',
    mode_smart_label: 'Smart',
    mode_smart_desc: 'Graph RAG · Basado en catálogo',

    // ── HomePage — Onboarding guide ───────────────────────
    guide_title: '¿Primera vez? Tu primera consulta en cuatro pasos',
    guide_full: 'Guía completa',
    guide_step1: 'Elige un espacio de trabajo',
    guide_step2: 'Selecciona dev o prod',
    guide_step3: 'Elige un modo SQL',
    guide_step4: 'Abre Chat y pregunta en lenguaje natural',
    guide_modes_prefix: 'Modos:',
    guide_modes_body: 'Flash (más rápido) · Preciso (determinístico — por defecto) · Smart (basado en catálogo). Prueba "ventas netas totales por región el último trimestre" o "top 10 clientes por ingresos".',

    // ── HomePage — Feature cards ───────────────────────────
    feature_chat_title: 'Chat',
    feature_chat_desc: 'Haz preguntas en lenguaje natural. Recibe respuestas con SQL, gráficos automáticos e historial de conversación por espacio de trabajo.',
    feature_chat_tag1: 'Respuestas en tiempo real',
    feature_chat_tag2: 'Gráficos automáticos',
    feature_chat_tag3: 'Historial persistente',
    feature_artifacts_title: 'Artefactos',
    feature_artifacts_desc: 'Genera documentos de negocio y reportes analíticos — resúmenes ejecutivos, análisis detallados y tablas de datos — impulsados por datos SAP.',
    feature_artifacts_tag1: 'Resumen ejecutivo',
    feature_artifacts_tag2: 'Reporte detallado',
    feature_artifacts_tag3: 'Formato propuesta',

    // ── HomePage — Platform capabilities ──────────────────
    cap_section_title: 'Capacidades de la plataforma',
    cap_text_to_sql: 'Text-to-SQL',
    cap_knowledge_graph: 'Grafo de conocimiento',
    cap_semantic_layer: 'Capa semántica',
    cap_hybrid_search: 'Búsqueda híbrida',
    cap_sap_native: 'SAP Nativo',
    cap_auto_charts: 'Gráficos automáticos',
    cap_ai_reports: 'Reportes con IA',

    // ── Thread (empty state + composer) ───────────────────
    thread_empty_title: '¿Qué te gustaría saber?',
    thread_empty_subtitle: 'Pregunta sobre tus datos SAP — ventas, inventario, finanzas u operaciones.',
    thread_chip1: 'Top 10 clientes por ingresos',
    thread_chip2: 'Órdenes de venta este mes',
    thread_chip3: 'Órdenes de compra pendientes',
    thread_composer_ph: 'Haz una pregunta sobre tus datos…',
    thread_composer_footer: 'Los resultados se generan a partir de tus datos SAP mediante la capa semántica Onibex.',
    thread_scroll_bottom: 'Ir al final',

    // ── ChatSidebar ────────────────────────────────────────
    sidebar_new_chat: 'Nuevo Chat',
    sidebar_no_chats: 'Sin chats aún',
    sidebar_select_workspace: 'Selecciona un espacio',

    // ── ChatPage ───────────────────────────────────────────
    chat_select_workspace: 'Selecciona un espacio de trabajo en el panel lateral antes de hacer una pregunta.',

    // ── ArtifactsPage ─────────────────────────────────────
    artifact_type_sales: 'Reporte de ventas',
    artifact_type_inventory: 'Reporte de inventario',
    artifact_type_executive: 'Resumen ejecutivo',
    artifact_type_financial: 'Reporte financiero',
    artifact_type_custom: 'Personalizado',
    artifact_format_brief: 'Resumen ejecutivo',
    artifact_format_detailed: 'Reporte detallado',
    artifact_format_tables: 'Tablas de datos',
    artifact_format_proposal: 'Formato propuesta',
    artifact_format_dashboard: 'Dashboard',
    artifact_step_name_q: '¡Vamos a crear un artefacto! ¿Cómo quieres llamarlo?',
    artifact_step_name_ph: 'ej. Reporte Q1, Resumen de inventario…',
    artifact_step_purpose_q: '¿Quién es la audiencia y cuál es el propósito del documento?',
    artifact_step_purpose_ph: 'ej. Para el equipo ejecutivo, reunión Q1…',
    artifact_step_data_q: '¿En qué datos debe enfocarse este documento? Sé específico.',
    artifact_step_data_ph: 'ej. Top 10 clientes por ingresos, Q1 2024, por región…',
    artifact_step_format_q: '¿Qué formato prefieres?',
    artifact_step_format_ph: 'Escribe o selecciona una opción abajo…',

    artifact_back_gallery: 'Volver a galería',
    artifact_new_artifact_header: 'Nuevo Artefacto',
    artifact_generating_msg: '¡Perfecto! Generando tu "{name}" ahora…',
    artifact_error_recovery: 'Algo salió mal. Puedes intentarlo de nuevo o ajustar tus respuestas.',
    artifact_composer_hint: 'Enter para enviar · Shift+Enter para nueva línea',

    artifact_thinking_0: 'Consultando tus fuentes de datos…',
    artifact_thinking_1: 'Tejiendo la narrativa…',
    artifact_thinking_2: 'Destilando insights de los datos…',
    artifact_thinking_3: 'Redactando el resumen ejecutivo…',
    artifact_thinking_4: 'Preguntando a tus tablas SAP…',
    artifact_thinking_5: 'Estructurando el marco analítico…',
    artifact_thinking_6: 'Explorando la capa semántica…',
    artifact_thinking_7: 'Traduciendo datos a lenguaje de negocio…',
    artifact_thinking_8: 'Calibrando el tono narrativo…',
    artifact_thinking_9: 'Construyendo la arquitectura del documento…',
    artifact_thinking_10: 'Cruzando métricas de negocio…',
    artifact_thinking_11: 'Alineando hechos con estrategia…',

    artifact_back: 'Volver',
    artifact_copy: 'Copiar',
    artifact_copied: 'Copiado',
    artifact_download_excel: 'Descargar Excel',
    artifact_edit: 'Editar',
    artifact_cancel: 'Cancelar',
    artifact_regenerate: 'Regenerar',
    artifact_regenerating: 'Regenerando…',

    artifact_label_name: 'Nombre',
    artifact_label_format: 'Formato',
    artifact_label_purpose: 'Propósito / Audiencia',
    artifact_label_data_focus: 'Enfoque de Datos',
    artifact_label_sql_override: 'SQL Personalizado',
    artifact_label_sql_hint: '— déjalo igual para que la IA regenere el SQL automáticamente',
    artifact_label_sql_ph: '-- Pega SQL personalizado aquí, o déjalo como está para que la IA lo regenere',
    artifact_applying: 'Aplicando…',
    artifact_apply_regenerate: 'Aplicar y Regenerar',

    artifact_tab_document: 'Documento',
    artifact_tab_data: 'Datos',
    artifact_no_datasets: 'No hay conjuntos de datos disponibles para este artefacto.',

    artifact_gallery_title: 'Artefactos',
    artifact_all_types: 'Todos los tipos',
    artifact_new_btn: 'Nuevo artefacto',
    artifact_search_ph: 'Buscar artefactos…',
    artifact_empty_title: 'Sin artefactos aún',
    artifact_empty_desc: 'Haz clic en "Nuevo artefacto" para generar tu primer documento.',
    artifact_no_match: 'Ningún artefacto coincide con tu búsqueda.',
    artifact_edited_prefix: 'Editado',

    results_table: 'Tabla',
    results_chart: 'Gráfico',
    results_copy_answer: 'Copiar respuesta',
    results_copy: 'Copiar',
    results_copied: 'Copiado',
    results_copy_sql: 'Copiar SQL',
    results_sql_query: 'Consulta SQL',
    results_showing_rows: 'Mostrando {shown} de {total} filas',
  },

  pt: {
    // ── Sidebar ────────────────────────────────────────────
    section_navigation: 'Navegação',
    section_workspace: 'Espaço de trabalho',
    section_environment: 'Ambiente',
    section_mode: 'Modo',
    nav_home: 'Início',
    nav_chat: 'Chat',
    nav_artifacts: 'Artefatos',
    select_workspace: 'Selecionar espaço…',
    sign_out: 'Sair',
    language: 'Idioma',

    // ── HomePage — Hero ────────────────────────────────────
    hero_subtitle: 'Text-to-SQL determinístico alimentado pela sua camada semântica SAP.',
    status_connecting: 'Conectando…',
    status_unreachable: 'Orquestrador indisponível',
    stat_workspaces: 'Espaços',
    stat_conversations: 'Conversas',

    // ── HomePage — Config cards ────────────────────────────
    card_active_workspace: 'Espaço ativo',
    card_not_selected: 'Não selecionado',
    card_environment: 'Ambiente',
    card_env_dev: 'Desenvolvimento',
    card_env_prod: 'Produção',
    card_env_dev_desc: 'Ambiente seguro — sem impacto em produção',
    card_env_prod_desc: 'Dados reais de produção',
    card_sql_mode: 'Modo SQL',

    // ── HomePage — Mode metadata ───────────────────────────
    mode_flash_label: 'Flash',
    mode_flash_desc: 'Mais rápido · Recuperação RAG',
    mode_precise_label: 'Preciso',
    mode_precise_desc: 'Determinístico · IR semântico',
    mode_smart_label: 'Smart',
    mode_smart_desc: 'Graph RAG · Baseado em catálogo',

    // ── HomePage — Onboarding guide ───────────────────────
    guide_title: 'Primeira vez? Sua primeira consulta em quatro passos',
    guide_full: 'Guia completo',
    guide_step1: 'Escolha um espaço de trabalho',
    guide_step2: 'Selecione dev ou prod',
    guide_step3: 'Escolha um modo SQL',
    guide_step4: 'Abra o Chat e pergunte em linguagem natural',
    guide_modes_prefix: 'Modos:',
    guide_modes_body: 'Flash (mais rápido) · Preciso (determinístico — padrão) · Smart (baseado em catálogo). Experimente "vendas líquidas totais por região no último trimestre" ou "top 10 clientes por receita".',

    // ── HomePage — Feature cards ───────────────────────────
    feature_chat_title: 'Chat',
    feature_chat_desc: 'Faça perguntas em linguagem natural. Receba respostas com SQL, gráficos automáticos e histórico de conversa por espaço de trabalho.',
    feature_chat_tag1: 'Respostas em tempo real',
    feature_chat_tag2: 'Gráficos automáticos',
    feature_chat_tag3: 'Histórico persistente',
    feature_artifacts_title: 'Artefatos',
    feature_artifacts_desc: 'Gere documentos de negócio e relatórios analíticos — resumos executivos, análises detalhadas e tabelas de dados — impulsionados por dados SAP.',
    feature_artifacts_tag1: 'Resumo executivo',
    feature_artifacts_tag2: 'Relatório detalhado',
    feature_artifacts_tag3: 'Formato proposta',

    // ── HomePage — Platform capabilities ──────────────────
    cap_section_title: 'Capacidades da plataforma',
    cap_text_to_sql: 'Text-to-SQL',
    cap_knowledge_graph: 'Grafo de conhecimento',
    cap_semantic_layer: 'Camada semântica',
    cap_hybrid_search: 'Busca híbrida',
    cap_sap_native: 'SAP Nativo',
    cap_auto_charts: 'Gráficos automáticos',
    cap_ai_reports: 'Relatórios com IA',

    // ── Thread (empty state + composer) ───────────────────
    thread_empty_title: 'O que você gostaria de saber?',
    thread_empty_subtitle: 'Pergunte sobre seus dados SAP — vendas, inventário, finanças ou operações.',
    thread_chip1: 'Top 10 clientes por receita',
    thread_chip2: 'Pedidos de venda deste mês',
    thread_chip3: 'Ordens de compra pendentes',
    thread_composer_ph: 'Faça uma pergunta sobre seus dados…',
    thread_composer_footer: 'Os resultados são gerados a partir dos seus dados SAP via camada semântica Onibex.',
    thread_scroll_bottom: 'Ir para o final',

    // ── ChatSidebar ────────────────────────────────────────
    sidebar_new_chat: 'Novo Chat',
    sidebar_no_chats: 'Nenhum chat ainda',
    sidebar_select_workspace: 'Selecione um espaço',

    // ── ChatPage ───────────────────────────────────────────
    chat_select_workspace: 'Selecione um espaço de trabalho na barra lateral antes de fazer uma pergunta.',

    // ── ArtifactsPage ─────────────────────────────────────
    artifact_type_sales: 'Relatório de vendas',
    artifact_type_inventory: 'Relatório de inventário',
    artifact_type_executive: 'Resumo executivo',
    artifact_type_financial: 'Relatório financeiro',
    artifact_type_custom: 'Personalizado',
    artifact_format_brief: 'Resumo executivo',
    artifact_format_detailed: 'Relatório detalhado',
    artifact_format_tables: 'Tabelas de dados',
    artifact_format_proposal: 'Formato proposta',
    artifact_format_dashboard: 'Dashboard',
    artifact_step_name_q: 'Vamos criar um artefato! Como você quer chamá-lo?',
    artifact_step_name_ph: 'ex. Relatório Q1, Visão geral de inventário…',
    artifact_step_purpose_q: 'Quem é o público e qual é o propósito do documento?',
    artifact_step_purpose_ph: 'ex. Para a equipe executiva, reunião Q1…',
    artifact_step_data_q: 'Em quais dados este documento deve se concentrar? Seja específico.',
    artifact_step_data_ph: 'ex. Top 10 clientes por receita, Q1 2024, por região…',
    artifact_step_format_q: 'Qual formato você prefere?',
    artifact_step_format_ph: 'Digite ou selecione uma opção abaixo…',

    artifact_back_gallery: 'Voltar à galeria',
    artifact_new_artifact_header: 'Novo Artefato',
    artifact_generating_msg: 'Perfeito! Gerando seu "{name}" agora…',
    artifact_error_recovery: 'Algo deu errado. Você pode tentar novamente ou ajustar suas respostas.',
    artifact_composer_hint: 'Enter para enviar · Shift+Enter para nova linha',

    artifact_thinking_0: 'Consultando suas fontes de dados…',
    artifact_thinking_1: 'Tecendo a narrativa…',
    artifact_thinking_2: 'Destilando insights dos dados brutos…',
    artifact_thinking_3: 'Redigindo o sumário executivo…',
    artifact_thinking_4: 'Perguntando às suas tabelas SAP…',
    artifact_thinking_5: 'Estruturando o framework analítico…',
    artifact_thinking_6: 'Explorando a camada semântica…',
    artifact_thinking_7: 'Traduzindo dados em linguagem de negócio…',
    artifact_thinking_8: 'Calibrando o tom narrativo…',
    artifact_thinking_9: 'Construindo a arquitetura do documento…',
    artifact_thinking_10: 'Cruzando métricas de negócio…',
    artifact_thinking_11: 'Alinhando fatos com estratégia…',

    artifact_back: 'Voltar',
    artifact_copy: 'Copiar',
    artifact_copied: 'Copiado',
    artifact_download_excel: 'Baixar Excel',
    artifact_edit: 'Editar',
    artifact_cancel: 'Cancelar',
    artifact_regenerate: 'Regenerar',
    artifact_regenerating: 'Regenerando…',

    artifact_label_name: 'Nome',
    artifact_label_format: 'Formato',
    artifact_label_purpose: 'Propósito / Audiência',
    artifact_label_data_focus: 'Foco de Dados',
    artifact_label_sql_override: 'SQL Personalizado',
    artifact_label_sql_hint: '— deixe inalterado para a IA regenerar o SQL automaticamente',
    artifact_label_sql_ph: '-- Cole SQL personalizado aqui, ou deixe como está para a IA regenerar',
    artifact_applying: 'Aplicando…',
    artifact_apply_regenerate: 'Aplicar e Regenerar',

    artifact_tab_document: 'Documento',
    artifact_tab_data: 'Dados',
    artifact_no_datasets: 'Nenhum conjunto de dados disponível para este artefato.',

    artifact_gallery_title: 'Artefatos',
    artifact_all_types: 'Todos os tipos',
    artifact_new_btn: 'Novo artefato',
    artifact_search_ph: 'Buscar artefatos…',
    artifact_empty_title: 'Sem artefatos ainda',
    artifact_empty_desc: 'Clique em "Novo artefato" para gerar seu primeiro documento.',
    artifact_no_match: 'Nenhum artefato corresponde à sua pesquisa.',
    artifact_edited_prefix: 'Editado',

    results_table: 'Tabela',
    results_chart: 'Gráfico',
    results_copy_answer: 'Copiar resposta',
    results_copy: 'Copiar',
    results_copied: 'Copiado',
    results_copy_sql: 'Copiar SQL',
    results_sql_query: 'Consulta SQL',
    results_showing_rows: 'Mostrando {shown} de {total} linhas',
  },
} satisfies Record<Locale, Record<string, string>>

export type TranslationKey = keyof typeof translations.en
