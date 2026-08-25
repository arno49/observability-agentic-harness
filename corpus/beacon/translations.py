from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "中文",
    "es": "Español",
    "hi": "हिन्दी",
}

UI: dict[str, dict[str, str]] = {
    "en": {
        "page_title":        "Beacon — Clinical Trial Finder",
        "heading":           "# 🔦 Beacon — Rare Disease Clinical Trial Finder",
        "placeholder":       "Type your message and press Enter…",
        "send":              "Send",
        "new_search":        "New Search",
        "searching":         "Searching…",
        "search_complete":   "Search complete.",
        "status_searching":  "*Searching ClinicalTrials.gov — this may take a minute…*",
        "no_analysis":       "No analysis produced.",
        "api_error":         "API request failed: {exc}",
        "got_it":            "Got it — searching for trials now…",
    },
    "zh": {
        "page_title":        "Beacon — 临床试验查找器",
        "heading":           "# 🔦 Beacon — 罕见病临床试验查找器",
        "placeholder":       "输入消息并按回车…",
        "send":              "发送",
        "new_search":        "新搜索",
        "searching":         "搜索中…",
        "search_complete":   "搜索完成。",
        "status_searching":  "*正在搜索 ClinicalTrials.gov，请稍候…*",
        "no_analysis":       "未生成分析结果。",
        "api_error":         "API 请求失败：{exc}",
        "got_it":            "好的，正在为您搜索临床试验…",
    },
    "es": {
        "page_title":        "Beacon — Buscador de Ensayos Clínicos",
        "heading":           "# 🔦 Beacon — Buscador de Ensayos Clínicos para Enfermedades Raras",
        "placeholder":       "Escribe tu mensaje y presiona Enter…",
        "send":              "Enviar",
        "new_search":        "Nueva Búsqueda",
        "searching":         "Buscando…",
        "search_complete":   "Búsqueda completada.",
        "status_searching":  "*Buscando en ClinicalTrials.gov, esto puede tomar un minuto…*",
        "no_analysis":       "No se produjo ningún análisis.",
        "api_error":         "Solicitud de API fallida: {exc}",
        "got_it":            "Entendido, buscando ensayos ahora…",
    },
    "hi": {
        "page_title":        "Beacon — क्लिनिकल ट्रायल खोजक",
        "heading":           "# 🔦 Beacon — दुर्लभ रोग क्लिनिकल ट्रायल खोजक",
        "placeholder":       "अपना संदेश टाइप करें और Enter दबाएं…",
        "send":              "भेजें",
        "new_search":        "नई खोज",
        "searching":         "खोज रहे हैं…",
        "search_complete":   "खोज पूर्ण।",
        "status_searching":  "*ClinicalTrials.gov पर खोज हो रही है, एक मिनट लग सकता है…*",
        "no_analysis":       "कोई विश्लेषण नहीं बना।",
        "api_error":         "API अनुरोध विफल: {exc}",
        "got_it":            "समझ गया — अभी ट्रायल खोज रहे हैं…",
    },
}

_PRESERVE = (
    "NEVER translate or modify: hospital/facility names, drug/treatment names, "
    "sponsor names, principal investigator names, trial titles, NCT IDs, "
    "medical abbreviations (ALSFRS-R, FVC, SOD1, etc.), gene names, or any "
    "other proper nouns from the trial data. Keep all of these exactly as-is. "
    "If you are unsure whether something is a proper noun, leave it in English."
)

# Translated report field labels used in the RESEARCH_SYSTEM output format.
REPORT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "trial":      "Trial",
        "sponsor":    "Sponsor",
        "pi":         "Principal Investigator",
        "contact":    "Contact",
        "summary":    "Summary",
        "criteria":   "Qualification criteria",
        "link":       "Link",
        "not_listed": "Not listed",
        "eap":        "Expanded Access",
        "next_steps": "Next steps",
        "miles":      "mi",
    },
    "zh": {
        "trial":      "试验",
        "sponsor":    "申办方",
        "pi":         "主要研究者",
        "contact":    "联系方式",
        "summary":    "简介",
        "criteria":   "入组资格",
        "link":       "链接",
        "not_listed": "未列出",
        "eap":        "扩展访问",
        "next_steps": "后续步骤",
        "miles":      "英里",
    },
    "es": {
        "trial":      "Ensayo",
        "sponsor":    "Patrocinador",
        "pi":         "Investigador Principal",
        "contact":    "Contacto",
        "summary":    "Resumen",
        "criteria":   "Criterios de elegibilidad",
        "link":       "Enlace",
        "not_listed": "No disponible",
        "eap":        "Acceso Expandido",
        "next_steps": "Próximos pasos",
        "miles":      "mi",
    },
    "hi": {
        "trial":      "परीक्षण",
        "sponsor":    "प्रायोजक",
        "pi":         "प्रमुख अन्वेषक",
        "contact":    "संपर्क",
        "summary":    "सारांश",
        "criteria":   "पात्रता मानदंड",
        "link":       "लिंक",
        "not_listed": "सूचीबद्ध नहीं",
        "eap":        "विस्तारित पहुँच",
        "next_steps": "अगले कदम",
        "miles":      "मील",
    },
}


def _labels_directive(lang: str) -> str:
    if lang == "en":
        return ""
    lb = REPORT_LABELS[lang]
    return (
        f"Use these translated field labels in every trial entry of your report:\n"
        f"  Trial → {lb['trial']}\n"
        f"  Sponsor → {lb['sponsor']}\n"
        f"  Principal Investigator → {lb['pi']}\n"
        f"  Contact → {lb['contact']}\n"
        f"  Summary → {lb['summary']}\n"
        f"  Qualification criteria → {lb['criteria']}\n"
        f"  Link → {lb['link']}\n"
        f"  'Not listed' → {lb['not_listed']}\n"
        f"  'Expanded Access' (EAP label) → {lb['eap']}\n"
        f"  'Next steps' section heading → {lb['next_steps']}\n"
        f"  Distance unit 'mi' → {lb['miles']}\n"
    )


LANGUAGE_DIRECTIVE: dict[str, str] = {
    "en": "",
    "zh": (
        "IMPORTANT: You must respond ONLY in Simplified Chinese (简体中文). "
        "Translate only your own explanatory text — the words YOU write to the patient. "
        f"{_PRESERVE}\n"
        + _labels_directive("zh") + "\n"
    ),
    "es": (
        "IMPORTANTE: Debes responder ÚNICAMENTE en español. "
        "Traduce solo tu propio texto explicativo — las palabras que TÚ escribes al paciente. "
        f"{_PRESERVE}\n"
        + _labels_directive("es") + "\n"
    ),
    "hi": (
        "महत्वपूर्ण: आपको केवल हिन्दी में उत्तर देना है। "
        "केवल अपना स्वयं का व्याख्यात्मक पाठ अनुवाद करें — वे शब्द जो आप रोगी को लिखते हैं। "
        f"{_PRESERVE}\n"
        + _labels_directive("hi") + "\n"
    ),
}
