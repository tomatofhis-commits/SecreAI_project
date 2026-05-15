import json
import os

lang_dir = r"d:\SecreAI_Build\data\lang"

common_keys = [
    "deprecation_notice", "thinking_level_label", 
    "thinking_min", "thinking_low", "thinking_mid", "thinking_high",
    "search_opt_grounding_2_5", "search_opt_tavily", "search_opt_integrated", "search_opt_grounding_3_1",
    "setting_group_gemini", "setting_group_openai", "setting_group_llama",
    "label_local_model_id", "label_ollama_endpoint",
    "tab_extensions_title", "extensions_group_api", "btn_fetching", "btn_fetch_success", "btn_fetch_ollama"
]

translations = {
    "ja": {
        "deprecation_notice": "⚠  Gemini 2.5 シリーズ 終了予定日\nGemini 2.5 Flash: 2026年6月17日　／　Gemini 2.5 Flash-Lite: 2026年7月22日",
        "thinking_level_label": "思考レベル (3.1-flash-lite のみ):",
        "thinking_min": "最小", "thinking_low": "低", "thinking_mid": "中", "thinking_high": "高",
        "search_opt_grounding_2_5": "gemini-2.5-flash-liteのgrounding",
        "search_opt_tavily": "tavilyで検索しollamaで要約",
        "search_opt_integrated": "grounding + tavily をollamaで統合要約",
        "search_opt_grounding_3_1": "gemini-3.1-flash-liteのgrounding (思考最小)",
        "setting_group_gemini": " Gemini Settings ", "setting_group_openai": " OpenAI Settings ", "setting_group_llama": " Llama (Local Ollama) Settings ",
        "label_local_model_id": "Local Model ID:", "label_ollama_endpoint": "Ollama Endpoint:",
        "tab_extensions_title": "Extensions (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "取得中...", "btn_fetch_success": "取得完了！", "btn_fetch_ollama": "Ollamaのモデルリストを取得・更新"
    },
    "en": {
        "deprecation_notice": "⚠ Gemini 2.5 Series End of Life\nGemini 2.5 Flash: June 17, 2026 / Gemini 2.5 Flash-Lite: July 22, 2026",
        "thinking_level_label": "Thinking Level (3.1-flash-lite only):",
        "thinking_min": "Minimal", "thinking_low": "Low", "thinking_mid": "Medium", "thinking_high": "High",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Search with tavily, summarize with ollama",
        "search_opt_integrated": "Integrated summary (grounding + tavily) with ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Minimal thinking)",
        "setting_group_gemini": " Gemini Settings ", "setting_group_openai": " OpenAI Settings ", "setting_group_llama": " Llama (Local Ollama) Settings ",
        "label_local_model_id": "Local Model ID:", "label_ollama_endpoint": "Ollama Endpoint:",
        "tab_extensions_title": "Extensions (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Fetching...", "btn_fetch_success": "Fetch Success!", "btn_fetch_ollama": "Fetch & Update Ollama Models"
    },
    "zh-CN": {
        "deprecation_notice": "⚠ Gemini 2.5 系列停用日期\nGemini 2.5 Flash: 2026年6月17日 / Gemini 2.5 Flash-Lite: 2026年7月22日",
        "thinking_level_label": "思考级别 (仅限 3.1-flash-lite):",
        "thinking_min": "最小", "thinking_low": "低", "thinking_mid": "中", "thinking_high": "高",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "使用 tavily 搜索，ollama 总结",
        "search_opt_integrated": "综合总结 (grounding + tavily) 使用 ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (最小思考)",
        "setting_group_gemini": " Gemini 设置 ", "setting_group_openai": " OpenAI 设置 ", "setting_group_llama": " Llama (本地 Ollama) 设置 ",
        "label_local_model_id": "本地模型 ID:", "label_ollama_endpoint": "Ollama 端点:",
        "tab_extensions_title": "扩展 (实验性质)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "获取中...", "btn_fetch_success": "获取成功！", "btn_fetch_ollama": "获取并更新 Ollama 模型"
    },
    "ko": {
        "deprecation_notice": "⚠ Gemini 2.5 시리즈 종료 예정일\nGemini 2.5 Flash: 2026년 6月 17일 / Gemini 2.5 Flash-Lite: 2026년 7월 22일",
        "thinking_level_label": "사고 レベル (3.1-flash-lite 전용):",
        "thinking_min": "최소", "thinking_low": "낮음", "thinking_mid": "중간", "thinking_high": "높음",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "tavily로 검색하고 ollama로 요약",
        "search_opt_integrated": "통합 요약 (grounding + tavily) ollama 사용",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (최소 사고)",
        "setting_group_gemini": " Gemini 설정 ", "setting_group_openai": " OpenAI 설정 ", "setting_group_llama": " Llama (로컬 Ollama) 설정 ",
        "label_local_model_id": "로컬 모델 ID:", "label_ollama_endpoint": "Ollama 엔드포인트:",
        "tab_extensions_title": "확장 기능 (실험적)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "가져오는 중...", "btn_fetch_success": "가져오기 성공!", "btn_fetch_ollama": "Ollama 모델 목록 가져오기 및 업데이트"
    },
    "es": {
        "deprecation_notice": "⚠ Fin de vida de la serie Gemini 2.5\nGemini 2.5 Flash: 17 de junio de 2026 / Gemini 2.5 Flash-Lite: 22 de julio de 2026",
        "thinking_level_label": "Nivel de pensamiento (solo 3.1-flash-lite):",
        "thinking_min": "Mínimo", "thinking_low": "Bajo", "thinking_mid": "Medio", "thinking_high": "Alto",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Buscar con tavily, resumir con ollama",
        "search_opt_integrated": "Resumen integrado (grounding + tavily) con ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Pensamiento mínimo)",
        "setting_group_gemini": " Configuración de Gemini ", "setting_group_openai": " Configuración de OpenAI ", "setting_group_llama": " Configuración de Llama (Ollama Local) ",
        "label_local_model_id": "ID del modelo local:", "label_ollama_endpoint": "Punto final de Ollama:",
        "tab_extensions_title": "Extensiones (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Obteniendo...", "btn_fetch_success": "¡Éxito!", "btn_fetch_ollama": "Obtener y actualizar modelos de Ollama"
    },
    "fr": {
        "deprecation_notice": "⚠ Fin de vie de la série Gemini 2.5\nGemini 2.5 Flash : 17 juin 2026 / Gemini 2.5 Flash-Lite : 22 juillet 2026",
        "thinking_level_label": "Niveau de réflexion (3.1-flash-lite uniquement):",
        "thinking_min": "Minimal", "thinking_low": "Bas", "thinking_mid": "Moyen", "thinking_high": "Haut",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Rechercher avec tavily, résumer avec ollama",
        "search_opt_integrated": "Résumé intégré (grounding + tavily) with ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Réflexion minimale)",
        "setting_group_gemini": " Paramètres Gemini ", "setting_group_openai": " Paramètres OpenAI ", "setting_group_llama": " Paramètres Llama (Ollama Local) ",
        "label_local_model_id": "ID du modèle local:", "label_ollama_endpoint": "Point d'accès Ollama:",
        "tab_extensions_title": "Extensions (Expérimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Récupération...", "btn_fetch_success": "Succès!", "btn_fetch_ollama": "Récupérer et mettre à jour les modèles Ollama"
    },
    "de": {
        "deprecation_notice": "⚠ Lebensende der Gemini 2.5 Serie\nGemini 2.5 Flash: 17. Juni 2026 / Gemini 2.5 Flash-Lite: 22. Juli 2026",
        "thinking_level_label": "Denkstufe (nur 3.1-flash-lite):",
        "thinking_min": "Minimal", "thinking_low": "Niedrig", "thinking_mid": "Mittel", "thinking_high": "Hoch",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Suchen mit tavily, zusammenfassen mit ollama",
        "search_opt_integrated": "Integrierte Zusammenfassung (grounding + tavily) mit ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Minimales Denken)",
        "setting_group_gemini": " Gemini-Einstellungen ", "setting_group_openai": " OpenAI-Einstellungen ", "setting_group_llama": " Llama (Lokales Ollama) Einstellungen ",
        "label_local_model_id": "Lokale Modell-ID:", "label_ollama_endpoint": "Ollama-Endpunkt:",
        "tab_extensions_title": "Erweiterungen (Experimentell)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Abrufen...", "btn_fetch_success": "Erfolg!", "btn_fetch_ollama": "Ollama-Modelle abrufen und aktualisieren"
    },
    "it": {
        "deprecation_notice": "⚠ Fine della serie Gemini 2.5\nGemini 2.5 Flash: 17 giugno 2026 / Gemini 2.5 Flash-Lite: 22 luglio 2026",
        "thinking_level_label": "Livello di pensiero (solo 3.1-flash-lite):",
        "thinking_min": "Minimo", "thinking_low": "Basso", "thinking_mid": "Medio", "thinking_high": "Alto",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Cerca con tavily, riassumi con ollama",
        "search_opt_integrated": "Riassunto integrato (grounding + tavily) con ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Pensiero minimo)",
        "setting_group_gemini": " Impostazioni Gemini ", "setting_group_openai": " Impostazioni OpenAI ", "setting_group_llama": " Impostazioni Llama (Ollama Locale) ",
        "label_local_model_id": "ID del modello locale:", "label_ollama_endpoint": "Endpoint Ollama:",
        "tab_extensions_title": "Estensioni (Sperimentale)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Recupero...", "btn_fetch_success": "Successo!", "btn_fetch_ollama": "Ottieni e aggiorna i modelli Ollama"
    },
    "pt": {
        "deprecation_notice": "⚠ Fim da vida útil da série Gemini 2.5\nGemini 2.5 Flash: 17 de junho de 2026 / Gemini 2.5 Flash-Lite: 22 de julho de 2026",
        "thinking_level_label": "Nível de raciocínio (apenas 3.1-flash-lite):",
        "thinking_min": "Mínimo", "thinking_low": "Baixo", "thinking_mid": "Médio", "thinking_high": "Alto",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Pesquisar com tavily, resumir com ollama",
        "search_opt_integrated": "Resumo integrado (grounding + tavily) com ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Raciocínio mínimo)",
        "setting_group_gemini": " Configurações Gemini ", "setting_group_openai": " Configurações OpenAI ", "setting_group_llama": " Configurações Llama (Ollama Local) ",
        "label_local_model_id": "ID do modelo local:", "label_ollama_endpoint": "Ponto de extremidade Ollama:",
        "tab_extensions_title": "Extensões (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Obtendo...", "btn_fetch_success": "Sucesso!", "btn_fetch_ollama": "Obter e atualizar modelos Ollama"
    },
    "ru": {
        "deprecation_notice": "⚠ Окончание поддержки серии Gemini 2.5\nGemini 2.5 Flash: 17 июня 2026 г. / Gemini 2.5 Flash-Lite: 22 июля 2026 г.",
        "thinking_level_label": "Уровень мышления (только 3.1-flash-lite):",
        "thinking_min": "Минимальный", "thinking_low": "Низкий", "thinking_mid": "Средний", "thinking_high": "Высокий",
        "search_opt_grounding_2_5": "gemini-2.5-flash-lite grounding",
        "search_opt_tavily": "Поиск с tavily, резюме с ollama",
        "search_opt_integrated": "Интегрированное резюме (grounding + tavily) с ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Минимальное мышление)",
        "setting_group_gemini": " Настройки Gemini ", "setting_group_openai": " Настройки OpenAI ", "setting_group_llama": " Настройки Llama (локальный Ollama) ",
        "label_local_model_id": "ID локального модели:", "label_ollama_endpoint": "Конечная точка Ollama:",
        "tab_extensions_title": "Расширения (Экспериментально)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Получение...", "btn_fetch_success": "Успешно!", "btn_fetch_ollama": "Получить и обновить модели Ollama"
    }
}

for lang_code, trans in translations.items():
    file_path = os.path.join(lang_dir, f"{lang_code}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if "settings" not in data:
            data["settings"] = {}
        
        for k, v in trans.items():
            data["settings"][k] = v
            
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
print("Dictionaries updated successfully!")
