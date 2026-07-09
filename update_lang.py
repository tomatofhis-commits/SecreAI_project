import json
import os

lang_dir = r"d:\SecreAI_Build\data\lang"

common_keys = [
    "thinking_level_label", 
    "thinking_min", "thinking_low", "thinking_mid", "thinking_high",
    "search_opt_tavily", "search_opt_integrated", "search_opt_grounding_3_1",
    "setting_group_gemini", "setting_group_openai", "setting_group_llama",
    "label_local_model_id", "label_ollama_endpoint",
    "tab_extensions_title", "extensions_group_api", "btn_fetching", "btn_fetch_success", "btn_fetch_ollama",
    "rtt_group_ollama", "search_limit_notice", "grounding_info_notice", "search_usage_grounding_short", "search_usage_grounding"
]

translations = {
    "ja": {
        "thinking_level_label": "思考レベル (3.1-flash-lite / 3.5-flash のみ):",
        "thinking_min": "最小", "thinking_low": "低", "thinking_mid": "中", "thinking_high": "高",
        "search_opt_tavily": "tavilyで検索しollamaで要約",
        "search_opt_integrated": "grounding + tavily をollamaで統合要約",
        "search_opt_grounding_3_1": "gemini-3.1-flash-liteのgrounding (思考最小)",
        "setting_group_gemini": " Gemini Settings ", "setting_group_openai": " OpenAI Settings ", "setting_group_llama": " Llama (Local Ollama) Settings ",
        "label_local_model_id": "Local Model ID:", "label_ollama_endpoint": "Ollama Endpoint:",
        "tab_extensions_title": "Extensions (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "取得中...", "btn_fetch_success": "取得完了！",
        "btn_fetch_ollama": "ローカルLLMのモデルリストを取得・更新",
        "rtt_group_ollama": " ローカルLLM 翻訳エンジン設定 ",
        "search_limit_notice": "※Tavilyの無料枠の上限は月間1000回です。Google Search選択時は「gemini-3.1-flash-lite」で固定されます。",
        "grounding_info_notice": "Google Grounding (Google Search) は月 5,000 プロンプトまで無料で利用可能です。",
        "search_usage_grounding_short": "Google (今月): {count}プロンプト",
        "search_usage_grounding": "Google (今月): {count} / 5000 ({month}月)"
    },
    "en": {
        "thinking_level_label": "Thinking Level (3.1-flash-lite / 3.5-flash only):",
        "thinking_min": "Minimal", "thinking_low": "Low", "thinking_mid": "Medium", "thinking_high": "High",
        "search_opt_tavily": "Search with tavily, summarize with ollama",
        "search_opt_integrated": "Integrated summary (grounding + tavily) with ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Minimal thinking)",
        "setting_group_gemini": " Gemini Settings ", "setting_group_openai": " OpenAI Settings ", "setting_group_llama": " Llama (Local Ollama) Settings ",
        "label_local_model_id": "Local Model ID:", "label_ollama_endpoint": "Ollama Endpoint:",
        "tab_extensions_title": "Extensions (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Fetching...", "btn_fetch_success": "Fetch Success!",
        "btn_fetch_ollama": "Fetch & Update Local LLM Models",
        "rtt_group_ollama": " Local LLM Translation Engine Settings ",
        "search_limit_notice": "*Tavily free tier is limited to 1,000 requests/month. Google Search is fixed to \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "Google Grounding (Google Search) is available for free up to 5,000 prompts per month.",
        "search_usage_grounding_short": "Google (This Month): {count} prompts",
        "search_usage_grounding": "Google (This Month): {count} / 5,000 ({month})"
    },
    "zh-CN": {
        "thinking_level_label": "思考级别 (仅限 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "最小", "thinking_low": "低", "thinking_mid": "中", "thinking_high": "高",
        "search_opt_tavily": "使用 tavily 搜索，ollama 总结",
        "search_opt_integrated": "综合总结 (grounding + tavily) 使用 ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (最小思考)",
        "setting_group_gemini": " Gemini 设置 ", "setting_group_openai": " OpenAI 设置 ", "setting_group_llama": " Llama (本地 Ollama) 设置 ",
        "label_local_model_id": "本地模型 ID:", "label_ollama_endpoint": "Ollama 端点:",
        "tab_extensions_title": "扩展 (实验性质)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "获取中...", "btn_fetch_success": "获取成功！",
        "btn_fetch_ollama": "获取并更新本地 LLM 模型列表",
        "rtt_group_ollama": " 本地 LLM 翻译引擎设置 ",
        "search_limit_notice": "*Tavily 免费额度为每月 1,000 次。选择 Google Search 时固定为 \"gemini-3.1-flash-lite\"。",
        "grounding_info_notice": "Google Grounding (Google Search) 每月最多可免费使用 5,000 次。",
        "search_usage_grounding_short": "Google (本月): {count} 次",
        "search_usage_grounding": "Google (本月): {count} / 5,000 ({month}月)"
    },
    "ko": {
        "thinking_level_label": "사고 레벨 (3.1-flash-lite / 3.5-flash 전용):",
        "thinking_min": "최소", "thinking_low": "낮음", "thinking_mid": "중간", "thinking_high": "높음",
        "search_opt_tavily": "tavily로 검색하고 ollama로 요약",
        "search_opt_integrated": "통합 요약 (grounding + tavily) ollama 사용",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (최소 사고)",
        "setting_group_gemini": " Gemini 설정 ", "setting_group_openai": " OpenAI 설정 ", "setting_group_llama": " Llama (로컬 Ollama) 설정 ",
        "label_local_model_id": "로컬 모델 ID:", "label_ollama_endpoint": "Ollama 엔드포인트:",
        "tab_extensions_title": "확장 기능 (실험적)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "가져오는 중...", "btn_fetch_success": "가져오기 성공!",
        "btn_fetch_ollama": "로컬 LLM 모델 목록 가져오기 및 업데이트",
        "rtt_group_ollama": " 로컬 LLM 번역 엔진 설정 ",
        "search_limit_notice": "*Tavily 무료 한도는 월 1,000회입니다. Google Search 선택 시 \"gemini-3.1-flash-lite\"로 고정됩니다.",
        "grounding_info_notice": "Google Grounding (Google Search)은 월 5,000회 프롬프트까지 무료로 사용 가능합니다.",
        "search_usage_grounding_short": "Google (이번 달): {count}회 프롬프트",
        "search_usage_grounding": "Google (이번 달): {count} / 5,000 ({month}월)"
    },
    "es": {
        "thinking_level_label": "Nivel de pensamiento (solo 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "Mínimo", "thinking_low": "Bajo", "thinking_mid": "Medio", "thinking_high": "Alto",
        "search_opt_tavily": "Buscar con tavily, resumir con ollama",
        "search_opt_integrated": "Resumen integrado (grounding + tavily) con ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Pensamiento mínimo)",
        "setting_group_gemini": " Configuración de Gemini ", "setting_group_openai": " Configuración de OpenAI ", "setting_group_llama": " Configuración de Llama (Ollama Local) ",
        "label_local_model_id": "ID del modelo local:", "label_ollama_endpoint": "Punto final de Ollama:",
        "tab_extensions_title": "Extensiones (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Obteniendo...", "btn_fetch_success": "¡Éxito!",
        "btn_fetch_ollama": "Obtener y actualizar lista de modelos de LLM local",
        "rtt_group_ollama": " Configuración del motor de traducción de LLM local ",
        "search_limit_notice": "*El límite de Tavily gratuito es de 1,000 solicitudes/mes. Google Search está fijado en \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "Google Grounding (Google Search) está disponible de forma gratuita hasta 5,000 prompts al mes.",
        "search_usage_grounding_short": "Google (Este mes): {count} prompts",
        "search_usage_grounding": "Google (Este mes): {count} / 5,000 ({month})"
    },
    "fr": {
        "thinking_level_label": "Niveau de réflexion (3.1-flash-lite / 3.5-flash uniquement):",
        "thinking_min": "Minimal", "thinking_low": "Bas", "thinking_mid": "Moyen", "thinking_high": "Haut",
        "search_opt_tavily": "Rechercher avec tavily, résumer avec ollama",
        "search_opt_integrated": "Résumé intégré (grounding + tavily) avec ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Réflexion minimale)",
        "setting_group_gemini": " Paramètres Gemini ", "setting_group_openai": " Paramètres OpenAI ", "setting_group_llama": " Paramètres Llama (Ollama Local) ",
        "label_local_model_id": "ID du modèle local:", "label_ollama_endpoint": "Point d'accès Ollama:",
        "tab_extensions_title": "Extensions (Expérimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Récupération...", "btn_fetch_success": "Succès!",
        "btn_fetch_ollama": "Récupérer et mettre à jour la liste des modèles LLM locaux",
        "rtt_group_ollama": " Paramètres du moteur de traduction LLM local ",
        "search_limit_notice": "*La limite gratuite de Tavily est de 1 000 requêtes/mois. Google Search est fixé à \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "Google Grounding (Google Search) est disponible gratuitement jusqu'à 5 000 requêtes par mois.",
        "search_usage_grounding_short": "Google (Ce mois-ci): {count} invites",
        "search_usage_grounding": "Google (Ce mois): {count} / 5 000 ({month})"
    },
    "de": {
        "thinking_level_label": "Denkstufe (nur 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "Minimal", "thinking_low": "Niedrig", "thinking_mid": "Mittel", "thinking_high": "Hoch",
        "search_opt_tavily": "Suchen mit tavily, zusammenfassen mit ollama",
        "search_opt_integrated": "Integrierte Zusammenfassung (grounding + tavily) mit ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Minimales Denken)",
        "setting_group_gemini": " Gemini-Einstellungen ", "setting_group_openai": " OpenAI-Einstellungen ", "setting_group_llama": " Llama (Lokales Ollama) Einstellungen ",
        "label_local_model_id": "Lokale Modell-ID:", "label_ollama_endpoint": "Ollama-Endpunkt:",
        "tab_extensions_title": "Erweiterungen (Experimentell)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Abrufen...", "btn_fetch_success": "Erfolg!",
        "btn_fetch_ollama": "Lokale LLM-Modellliste abrufen und aktualisieren",
        "rtt_group_ollama": " Lokale LLM-Übersetzungs-Engine-Einstellungen ",
        "search_limit_notice": "*Tavily-Freikontingent ist auf 1.000 Anfragen/Monat begrenzt. Google Search ist auf \"gemini-3.1-flash-lite\" festgelegt.",
        "grounding_info_notice": "Google Grounding (Google Search) ist bis zu 5.000 Prompts pro Monat kostenlos verfügbar.",
        "search_usage_grounding_short": "Google (Diesen Monat): {count} Prompts",
        "search_usage_grounding": "Google (Diesen Monat): {count} / 5.000 ({month})"
    },
    "it": {
        "thinking_level_label": "Livello di pensiero (solo 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "Minimo", "thinking_low": "Basso", "thinking_mid": "Medio", "thinking_high": "Alto",
        "search_opt_tavily": "Cerca con tavily, riassumi con ollama",
        "search_opt_integrated": "Riassunto integrato (grounding + tavily) con ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Pensiero minimo)",
        "setting_group_gemini": " Impostazioni Gemini ", "setting_group_openai": " Impostazioni OpenAI ", "setting_group_llama": " Impostazioni Llama (Ollama Locale) ",
        "label_local_model_id": "ID del modello locale:", "label_ollama_endpoint": "Endpoint Ollama:",
        "tab_extensions_title": "Estensioni (Sperimentale)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Recupero...", "btn_fetch_success": "Successo!",
        "btn_fetch_ollama": "Ottieni e aggiorna l'elenco dei modelli LLM locali",
        "rtt_group_ollama": " Impostazioni del motore di traduzione LLM locale ",
        "search_limit_notice": "*Il limite gratuito di Tavily è di 1.000 richieste/mese. Google Search è fisso su \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "Google Grounding (Google Search) è disponibile gratuitamente fino a 5.000 prompt al mese.",
        "search_usage_grounding_short": "Google (Questo mese): {count} prompt",
        "search_usage_grounding": "Google (Questo mese): {count} / 5.000 ({month})"
    },
    "pt": {
        "thinking_level_label": "Nível de raciocínio (apenas 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "Mínimo", "thinking_low": "Baixo", "thinking_mid": "Médio", "thinking_high": "Alto",
        "search_opt_tavily": "Pesquisar com tavily, resumir com ollama",
        "search_opt_integrated": "Resumo integrado (grounding + tavily) com ollama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Raciocínio mínimo)",
        "setting_group_gemini": " Configurações Gemini ", "setting_group_openai": " Configurações OpenAI ", "setting_group_llama": " Configurações Llama (Ollama Local) ",
        "label_local_model_id": "ID do modelo local:", "label_ollama_endpoint": "Ponto de extremidade Ollama:",
        "tab_extensions_title": "Extensões (Experimental)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Obtendo...", "btn_fetch_success": "Sucesso!",
        "btn_fetch_ollama": "Obter e atualizar lista de modelos de LLM local",
        "rtt_group_ollama": " Configurações do mecanismo de tradução de LLM local ",
        "search_limit_notice": "*O limite gratuito do Tavily é de 1.000 solicitações/mês. Google Search é fixo em \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "O Google Grounding (Google Search) está disponível gratuitamente para até 5.000 prompts por mês.",
        "search_usage_grounding_short": "Google (Este mês): {count} prompts",
        "search_usage_grounding": "Google (Este mês): {count} / 5.000 ({month})"
    },
    "ru": {
        "thinking_level_label": "Уровень мышления (только 3.1-flash-lite / 3.5-flash):",
        "thinking_min": "Минимальный", "thinking_low": "Низкий", "thinking_mid": "Средний", "thinking_high": "Высокий",
        "search_opt_tavily": "Поиск с tavily, резюме с ollama",
        "search_opt_integrated": "Интегрированное резюме (grounding + tavily) с оllama",
        "search_opt_grounding_3_1": "gemini-3.1-flash-lite grounding (Минимальное мышление)",
        "setting_group_gemini": " Настройки Gemini ", "setting_group_openai": " Настройки OpenAI ", "setting_group_llama": " Настройки Llama (локальный Ollama) ",
        "label_local_model_id": "ID локального модели:", "label_ollama_endpoint": "Конечная точка Ollama:",
        "tab_extensions_title": "Расширения (Экспериментально)", "extensions_group_api": " API / WebSockets ",
        "btn_fetching": "Получение...", "btn_fetch_success": "Успешно!",
        "btn_fetch_ollama": "Получить и обновить список локальных моделей LLM",
        "rtt_group_ollama": " Настройки локального движка перевода LLM ",
        "search_limit_notice": "*Бесплатный лимит Tavily — 1000 запросов в месяц. При выборе Google Search используется модель \"gemini-3.1-flash-lite\".",
        "grounding_info_notice": "Google Grounding (Google Search) предоставляется бесплатно до 5000 запросов в месяц.",
        "search_usage_grounding_short": "Google (В этом месяце): {count} запр.",
        "search_usage_grounding": "Google (В этом месяце): {count} / 5000 ({month})"
    }
}

for lang_code, trans in translations.items():
    file_path = os.path.join(lang_dir, f"{lang_code}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if "settings" not in data:
            data["settings"] = {}
            
        # 古いキーを削除
        data["settings"].pop("deprecation_notice", None)
        data["settings"].pop("search_opt_grounding_2_5", None)
        
        # 新しい値を格納
        for k, v in trans.items():
            data["settings"][k] = v
            
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
print("Dictionaries updated successfully!")
