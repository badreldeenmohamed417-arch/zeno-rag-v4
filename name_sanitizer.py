#!/usr/bin/env python3
"""
Zeno RAG Readable Directory Naming Sanitizer
Converts Egyptian curriculum PDF filenames and metadata into standardized, human-readable directory names.
Examples:
  - "1ث شافعى نهائي.pdf" / "1_Sec_Arabic" -> "arabic_sec1"
  - "Physics_Arabic_2_Secondary_TR1.pdf" -> "physics_sec2"
  - "Chemistry_FR_Sec3.pdf" -> "chemistry_sec3"
  - "Deutsch_language_Sec3.pdf" -> "german_sec3"
"""
import re
import unicodedata

# Subject translation map - prioritized order
SUBJECT_MAP = {
    # Core Sciences
    "فيزياء": "physics", "physics": "physics",
    "كيمياء": "chemistry", "chemistry": "chemistry",
    "احياء": "biology", "أحياء": "biology", "biology": "biology",
    "جيولوجيا": "geology", "geology": "geology",
    "علوم": "science", "science": "science",

    # Math
    "رياضيات": "math", "رياضة": "math", "mathematics": "math", "math": "math",
    "احصاء": "statistics", "إحصاء": "statistics", "statistics": "statistics",
    "تطبيقة": "applied_math", "رياضة تطبيقية": "applied_math",

    # Humanities
    "تاريخ": "history", "history": "history",
    "جغرافيا": "geography", "geography": "geography",
    "فلسفة": "philosophy", "philosophy": "philosophy",
    "منطق": "logic", "logic": "logic",
    "عالم نفس": "psychology", "علم نفس": "psychology", "psychology": "psychology", "sociology": "sociology",

    # Religion / Azhar
    "دين": "religion", "تربية دینیة": "religion", "christian": "christian_religion", "اسلامي": "islamic_religion",
    "فقه": "fiqh", "حديث": "hadith", "تفسير": "tafseer", "توحيد": "tawheed", "شافعى": "fiqh_shafii", "مالكي": "fiqh_maliki", "حنافي": "fiqh_hanafi",

    # Specific Languages
    "الماني": "german", "اللغة الألمانية": "german", "deutsch": "german",
    "ايطالي": "italian", "اللغة الإيطالية": "italian", "italian": "italian",
    "اسباني": "spanish", "اللغة الإسبانية": "spanish", "spanish": "spanish",
    "فرنساوي": "french", "اللغة الفرنسية": "french", "french": "french",
    "انجليزي": "english", "اللغة الانجليزية": "english", "english": "english",
    "عربي": "arabic", "اللغة العربية": "arabic", "arabic": "arabic", "lisan": "arabic", "naho": "arabic_naho", "قصة": "arabic_story"
}

STAGE_MAP = {
    "1": "sec1", "1ث": "sec1", "sec1": "sec1", "1sec": "sec1", "1_sec": "sec1", "1_ثانوي": "sec1", "اولى_ثانوي": "sec1", "primary1": "sec1",
    "2": "sec2", "2ث": "sec2", "sec2": "sec2", "2sec": "sec2", "2_sec": "sec2", "2_ثانوي": "sec2", "ثانية_ثانوي": "sec2",
    "3": "sec3", "3ث": "sec3", "sec3": "sec3", "3sec": "sec3", "3_sec": "sec3", "3_ثانوي": "sec3", "ثالثة_ثانوي": "sec3"
}

def sanitize_to_readable_name(pdf_name: str, meta: dict = None) -> str:
    """
    Returns clean readable name e.g., 'arabic_sec1', 'physics_sec2', 'chemistry_sec3'.
    """
    raw = (pdf_name or "").lower()
    if meta:
        raw += " " + str(meta.get("stage", "")).lower()
        raw += " " + str(meta.get("subject", "")).lower()

    # Detect stage
    stage = "sec1"
    if any(k in raw for k in ["3ث", "sec3", "3_sec", "3sec", "3_ثانوي", "sec 3"]):
        stage = "sec3"
    elif any(k in raw for k in ["2ث", "sec2", "2_sec", "2sec", "2_ثانوي", "sec 2"]):
        stage = "sec2"
    elif any(k in raw for k in ["1ث", "sec1", "1_sec", "1sec", "1_ثانوي", "sec 1"]):
        stage = "sec1"

    # Detect subject
    subj = "general"
    for key, val in SUBJECT_MAP.items():
        if key in raw:
            subj = val
            break

    # Clean fallback if subject not found in map
    if subj == "general":
        clean_raw = re.sub(r'[^a-zA-Z0-9]', '_', pdf_name.replace('.pdf', ''))
        clean_raw = re.sub(r'_+', '_', clean_raw).strip('_').lower()
        if clean_raw:
            return f"{clean_raw[:20]}_{stage}"

    return f"{subj}_{stage}"

if __name__ == "__main__":
    test_cases = [
        "1ث شافعى نهائي.pdf",
        "Physics_Arabic_2_Secondary_TR1.pdf",
        "Chemistry_FR_Sec3.pdf",
        "Deutsch_language_Sec3.pdf",
        "History_Sec2_Tr1.pdf"
    ]
    for tc in test_cases:
        print(f"'{tc}' -> '{sanitize_to_readable_name(tc)}'")
