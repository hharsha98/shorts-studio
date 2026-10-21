"""Fixed on-screen copy that every company Short shares. A config cannot change these proof numbers.

The proof card names the plant that is already on the CV (Siemens AG, Amberg). Do not name an
internal project. Do not write MARA, SIPLACE, SMT, a salary, or a German CEFR level.
"""

PROOF = {
    "en": {
        "kicker": "Siemens AG, Amberg",
        "badge": "REAL RESULT",
        "title": "Built a multi-agent system with advanced RAG",
        "sub": "For industrial machines at a Siemens plant",
        "facts": [
            {"value": "73–88%", "label": "faster root-cause analysis"},
            {"value": "8–15 min", "label": "per fault, down from 30–120 min"},
            {"value": "16", "label": "machines in production"},
            {"value": "LangGraph", "label": "FastAPI · Pydantic AI · Langfuse"},
        ],
        "source": "Source: candidate's CV. A real result there, not a figure for this company.",
        "line": (
            "Built a multi-agent system with advanced RAG for industrial machines at a Siemens plant, "
            "LangGraph, FastAPI, Pydantic AI, Langfuse tracing, cutting root cause analysis by 73 to 88 percent, "
            "from 30 to 120 minutes down to 8 to 15 minutes per fault, on 16 machines in production."
        ),
        "say": (
            "Built a multi-agent system with advanced R-A-G for industrial machines at a Siemens plant, "
            "Lang-Graph, Fast A-P-I, Pydantic A-I, Lang-fuse tracing, cutting root cause analysis by "
            "73 to 88 percent, from 30 to 120 minutes down to 8 to 15 minutes per fault, on 16 machines in production."
        ),
        "cue": "LangGraph",
    },
    "de": {
        "kicker": "Siemens AG, Amberg",
        "badge": "ECHTES ERGEBNIS",
        "title": "Multi-Agenten-System mit Advanced RAG gebaut",
        "sub": "Für Industriemaschinen in einem Siemens-Werk",
        "facts": [
            {"value": "73–88 %", "label": "schnellere Ursachenanalyse"},
            {"value": "8–15 Min.", "label": "pro Störung, statt 30–120 Min."},
            {"value": "16", "label": "Maschinen im Produktivbetrieb"},
            {"value": "LangGraph", "label": "FastAPI · Pydantic AI · Langfuse"},
        ],
        "source": "Quelle: Lebenslauf des Bewerbers. Ein echtes Ergebnis dort, keine Zahl dieses Unternehmens.",
        "line": (
            "Gebaut: ein Multi-Agenten-System mit Advanced RAG für Industriemaschinen in einem Siemens-Werk, "
            "LangGraph, FastAPI, Pydantic AI, Langfuse-Tracing, das die Ursachenanalyse um 73 bis 88 Prozent "
            "verkürzt, von 30 bis 120 auf 8 bis 15 Minuten pro Störung, an 16 Maschinen im Produktivbetrieb."
        ),
        "say": (
            "Gebaut: ein Multi-Agenten-System mit Advanced R-A-G für Industriemaschinen in einem Siemens-Werk, "
            "Lang-Graph, Fast-A-P-I, Pydantic A-I, Lang-fuse-Tracing, das die Ursachenanalyse um 73 bis 88 Prozent "
            "verkürzt, von 30 bis 120 auf 8 bis 15 Minuten pro Störung, an 16 Maschinen im Produktivbetrieb."
        ),
        "cue": "LangGraph",
    },
}

CLOSING_LINE = {"en": "Happy to explore it with you.", "de": "Mehr dazu gern im Gespräch."}

# Short public links on the closing card. Keep them short so four lines still fit.
LINKS = [
    "agentic-systems-studio.com",
    "linkedin.com/in/hanumanthu1",
    "github.com/hharsha98",
    "huggingface.co/hharsha",
]

BADGES = {
    "en": [
        {"icon": "server", "text": "Local LLM"},
        {"icon": "eye", "text": "Read-only first"},
        {"icon": "lock", "text": "GDPR in mind"},
        {"icon": "user", "text": "Human decides"},
    ],
    "de": [
        {"icon": "server", "text": "Lokales LLM"},
        {"icon": "eye", "text": "Zuerst nur lesend"},
        {"icon": "lock", "text": "DSGVO im Blick"},
        {"icon": "user", "text": "Mensch entscheidet"},
    ],
}

METRICS_CHROME = {
    "en": {"title": "Pilot targets", "stamp": "ILLUSTRATIVE", "legend": ["Today (example)", "With assistant (target)"],
           "footnote": "Example values, not this company's data. To be measured in a pilot."},
    "de": {"title": "Pilotziele", "stamp": "BEISPIELWERTE", "legend": ["Heute (Beispiel)", "Mit Assistent (Ziel)"],
           "footnote": "Beispielwerte, keine Unternehmensdaten. Im Pilotprojekt zu messen."},
}

ARCH_TITLE = {"en": "How it could work", "de": "So könnte es funktionieren"}
PILOT_CHROME = {
    "en": {"title": "A first pilot", "sub": "Small, safe and measurable"},
    "de": {"title": "Ein erster Pilot", "sub": "Klein, sicher und messbar"},
}
AUTHOR = "Hanumanthu Harsha Vardhan"
GITHUB = "github.com/hharsha98"
VOICE_NOTE = {"en": "AI voice", "de": "KI-Stimme"}
CONCEPT = {"en": "Concept by", "de": "Konzept von"}
FOR_LINE = {"en": "An idea for {name}", "de": "Eine Idee für {name}"}
NOT_OFFICIAL = {
    "en": "A concept, not an official {name} project · illustrative numbers",
    "de": "Ein Konzept, kein offizielles Projekt von {name} · Beispielwerte",
}
CREDIT = {"en": "Images: {domain}", "de": "Bilder: {domain}"}

# Narration and on-screen copy must not say the idea came from a job advert,
# name an internal project, quote a salary, or state a German CEFR level.
FORBIDDEN = (
    "job posting", "job postings", "your posting", "your postings",
    "stellenanzeige", "stellenanzeigen", "eure ausschreibung", "ihrer ausschreibung",
    "ai idea sketch", "ki-ideenskizze",
    "mara", "siplace", "smt-maschine", "smt maschine", "smt-maschinen", "smt machines",
    "gehalt", "salary", "sprachniveau", "deutschkenntnisse", "cefr",
)
