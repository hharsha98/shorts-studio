"""Fixed on-screen copy that every company Short shares. A config cannot change these proof numbers.

The system is described only as a multi-agent system with LangGraph. Do not name an employer or an internal project on the card or in the narration.
"""

PROOF = {
    "en": {
        "kicker": "Built before",
        "badge": "REAL RESULT",
        "title": "A multi-agent system with LangGraph",
        "sub": "Already running in production",
        "facts": [
            {"value": "12", "label": "LLM agents working together"},
            {"value": "< 200 ms", "label": "retrieval over manuals and logs"},
            {"value": "On-prem", "label": "LLMs, for data protection"},
            {"value": "~78 %", "label": "of suggestions accepted at first review"},
        ],
        "source": "Source: candidate's CV. A real result there, not a figure for this company.",
        "line": "A multi-agent system with LangGraph that I built already runs in production.",
        "say": "A multi-agent system with Lang Graph that I built already runs in production.",
        "cue": "LangGraph",
    },
    "de": {
        "kicker": "Schon einmal gebaut",
        "badge": "ECHTES ERGEBNIS",
        "title": "Multi-Agenten-System mit LangGraph",
        "sub": "Bereits im Produktiveinsatz",
        "facts": [
            {"value": "12", "label": "KI-Agenten auf LLM-Basis"},
            {"value": "< 200 ms", "label": "Suche in Handbüchern und Logs"},
            {"value": "On-Premise", "label": "LLMs für den Datenschutz"},
            {"value": "~78 %", "label": "der Vorschläge im ersten Review angenommen"},
        ],
        "source": "Quelle: Lebenslauf des Bewerbers. Ein echtes Ergebnis dort, keine Zahl dieses Unternehmens.",
        "line": "Ein Multi-Agenten-System mit LangGraph, das ich gebaut habe, läuft bereits produktiv.",
        "say": "Ein Multi-Agenten-System mit Lang-Graph, das ich gebaut habe, läuft bereits produktiv.",
        "cue": "LangGraph",
    },
}

CLOSING_LINE = {"en": "Happy to explore it with you.", "de": "Mehr dazu gern im Gespräch."}

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

# Narration and on-screen copy must not say the idea came from a job advert.
FORBIDDEN = (
    "job posting", "job postings", "your posting", "your postings",
    "stellenanzeige", "stellenanzeigen", "eure ausschreibung", "ihrer ausschreibung",
    "ai idea sketch", "ki-ideenskizze",
)
