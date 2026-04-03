# Ordnerstruktur — agentur_core

```
agentur_core/
│
├── README.md                          # Projektübersicht
├── SETUP_STAND_03042026.md            # Heutiger Stand
│
├── agenten/                           # Alle Agenten-Definitionen
│   ├── chef_agent/
│   │   ├── prompt.md
│   │   └── config.py
│   ├── app_agent/
│   ├── web_agent/
│   ├── design_agent/
│   ├── foto_agent/
│   ├── video_agent/
│   ├── research_marketing_agent/
│   ├── rechtsanwalt_agent/
│   └── finance_agent/
│
├── bibliothek/                        # Wissensbibliothek
│   ├── steckbrief_template.md         # Blanko Steckbrief v2.0
│   ├── transkripte/                   # Alle 70 Steckbriefe
│   │   ├── UID-20260403-001.md
│   │   ├── UID-20260403-002.md
│   │   └── ...
│   └── index.md                       # Übersicht aller Steckbriefe
│
├── workflows/                         # Prozesse & Abläufe
│   └── routing_logik.md               # Welches Modell für welche Aufgabe
│
├── infrastruktur/                     # Technische Docs
│   ├── railway_setup.md
│   └── env_variables.md
│
└── dna/                               # Nicht verhandelbare Regeln
    ├── QUALITAET.md                   # Nur echte Produkte, kein Sim
    ├── STIL.md                        # Design-Prinzipien
    └── AGENTEN_REGELN.md              # Was Agenten dürfen/nicht dürfen
```

---

## Anlegen auf GitHub

Geh auf github.com → `agentur_core` → klick **"creating a new file"**

Dann tipp den Pfad direkt ein, z.B.:
```
agenten/chef_agent/prompt.md
```

GitHub legt die Ordner automatisch an wenn du `/` tippst.
