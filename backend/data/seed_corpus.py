"""Demo municipal corpus for first 30% — supports supported / missing / conflict demos."""

from __future__ import annotations

SEED_SOURCES = [
    {
        "code": "acte-oficiale",
        "name": "Acte oficiale Primăria Chișinău",
        "url": "https://www.chisinau.md/ro/acteoficiale",
        "type": "documents",
        "category": "Transparency & Municipal Projects",
        "priority": "P0",
    },
    {
        "code": "transparenta",
        "name": "Portalul Transparenței",
        "url": "https://www.chisinau.md/ro/transparenta",
        "type": "portal",
        "category": "Transparency & Municipal Projects",
        "priority": "P0",
    },
    {
        "code": "dgaurf",
        "name": "Direcția Generală Arhitectură, Urbanism și Relații Funciare",
        "url": "https://dgaurf.md/",
        "type": "portal",
        "category": "Architecture, Green Spaces & Urban Utilities",
        "priority": "P0",
    },
    {
        "code": "help-chisinau",
        "name": "help.chisinau.md — asistență medicală și socială",
        "url": "https://help.chisinau.md/",
        "type": "services",
        "category": "Healthcare",
        "priority": "P1",
    },
    {
        "code": "ghiseu-unic",
        "name": "Ghișeul Unic Primăria Chișinău",
        "url": "http://chisinau.md",
        "type": "contacts",
        "category": "Transparency & Municipal Projects",
        "priority": "P0",
    },
    {
        "code": "pretura-botanica",
        "name": "Pretura sectorului Botanica",
        "url": "https://botanica.md/",
        "type": "contacts",
        "category": "District pretura",
        "priority": "P0",
    },
]

TOPIC_LINKS = [
    {
        "topic_ro": "autorizatie construire",
        "topic_ru": "разрешение на строительство",
        "url": "https://dgaurf.md/ro/regulatory",
        "contact_label": "DGAURF — Cadrul normativ",
        "contact_value": "https://dgaurf.md/ro/regulatory",
    },
    {
        "topic_ro": "transparenta",
        "topic_ru": "прозрачность",
        "url": "https://www.chisinau.md/ro/transparenta",
        "contact_label": "Portal Transparență",
        "contact_value": "https://www.chisinau.md/ro/transparenta",
    },
    {
        "topic_ro": "contact general",
        "topic_ru": "общий контакт",
        "url": "http://chisinau.md",
        "contact_label": "Ghișeul Unic",
        "contact_value": "+373 22 20 15 05 · primaria@pmc.md",
    },
    {
        "topic_ro": "sanatate",
        "topic_ru": "здоровье",
        "url": "https://help.chisinau.md/",
        "contact_label": "help.chisinau.md",
        "contact_value": "https://help.chisinau.md/",
    },
    {
        "topic_ro": "mobilitate",
        "topic_ru": "мобильность",
        "url": "https://mobilitatechisinau.md/",
        "contact_label": "Mobilitate Chișinău",
        "contact_value": "https://mobilitatechisinau.md/",
    },
    {
        "topic_ro": "pretura botanica contact",
        "topic_ru": "претура ботаника контакт",
        "url": "https://botanica.md/",
        "contact_label": "Pretura Botanica",
        "contact_value": "str. Teilor 10 · 022 76-75-75 · pretura.botanica@pmc.md",
    },
    {
        "topic_ro": "pretura centru contact",
        "topic_ru": "претура центр контакт",
        "url": "https://www.chisinau.md/",
        "contact_label": "Pretura Centru",
        "contact_value": "str. Columna 147 · 022 22-26-32 · pretura.centru@pmc.md",
    },
    {
        "topic_ro": "pretura buiucani contact",
        "topic_ru": "претура буюканы контакт",
        "url": "https://www.chisinau.md/",
        "contact_label": "Pretura Buiucani",
        "contact_value": "str. Ion Creangă 4/2 · 022 74-94-40 · pretura.buiucani@pmc.md",
    },
    {
        "topic_ro": "pretura ciocana contact",
        "topic_ru": "претура чокана контакт",
        "url": "https://www.chisinau.md/",
        "contact_label": "Pretura Ciocana",
        "contact_value": "str. Mircea cel Bătrân 4/2 · 022 31-55-91 · pretura.ciocana@pmc.md",
    },
    {
        "topic_ro": "pretura rascani contact",
        "topic_ru": "претура рышкановка контакт",
        "url": "https://www.chisinau.md/",
        "contact_label": "Pretura Râșcani",
        "contact_value": "str. Kiev 147A · 022 44-01-12 · pretura.rascani@pmc.md",
    },
]

# Intentionally crafted for demo scenarios
SEED_DOCUMENTS = [
    {
        "source_code": "dgaurf",
        "title": "Pașaportul E-PERMIS — Autorizația de construire (DGAURF)",
        "url": "https://dgaurf.md/storage/about/administrative/pasaport-e-permis-ac.pdf",
        "language": "ro",
        "pages": [
            """REGULAMENTUL / Pașaportul E-PERMIS privind autorizarea construcțiilor în municipiul Chișinău
Sursă oficială: https://dgaurf.md/storage/about/administrative/pasaport-e-permis-ac.pdf
Cadrul normativ DGAURF: https://dgaurf.md/ro/regulatory

Capitolul 1. Dispoziții generale
Art. 1. Prezentul regulament stabilește procedura de eliberare a autorizației de construire pe teritoriul municipiului Chișinău.
Art. 2. Autorizația de construire se eliberează de Direcția Generală Arhitectură, Urbanism și Relații Funciare (DGAURF).
""",
            """Capitolul 2. Acte necesare
Secțiunea 2.1. Dosarul solicitantului
Pentru obținerea autorizației de construire, solicitantul depune următoarele acte:
1. Cerere tip, completată și semnată.
2. Buletinul de identitate al solicitantului (copie).
3. Extrasul din Registrul bunurilor imobile.
4. Certificatul de urbanism.
5. Proiectul de execuție, semnat de proiectant autorizat.
6. Avizele prevăzute în certificatul de urbanism.
""",
            """Capitolul 3. Termene
Secțiunea 3.2. Termenul de examinare
Cererea pentru eliberarea autorizației de construire se examinează în termen de 30 zile lucrătoare de la data înregistrării dosarului complet.
În cazul dosarelor incomplete, termenul începe să curgă de la data completării.
""",
            """Capitolul 4. Contact
Solicitanții pot depune dosarul la sediul DGAURF sau prin serviciile electronice ale Primăriei.
Informații suplimentare: https://dgaurf.md/ro/regulatory
Pașaport E-PERMIS (Autorizația de construire): https://dgaurf.md/storage/about/administrative/pasaport-e-permis-ac.pdf
""",
        ],
    },
    {
        "source_code": "acte-oficiale",
        "title": "Dispoziția Primarului nr. 412/2025 privind termenele de eliberare a autorizațiilor",
        "url": "https://www.chisinau.md/ro/acteoficiale",
        "language": "ro",
        "pages": [
            """DISPOZIȚIA PRIMARULUI nr. 412 din 15 martie 2025
Cu privire la optimizarea termenelor de eliberare a autorizațiilor de construire

Art. 1. Se stabilește că termenul de examinare a cererilor pentru autorizația de construire este de 20 zile lucrătoare de la înregistrarea dosarului complet.
Art. 2. Prevederile prezentei dispoziții se aplică începând cu data publicării.
Art. 3. Direcția Generală Arhitectură, Urbanism și Relații Funciare va asigura executarea prezentei dispoziții.
""",
        ],
    },
    {
        "source_code": "transparenta",
        "title": "Formulare de cereri — autorizații și certificate (Primăria Chișinău)",
        "url": "https://new.chisinau.md/ro/formulare-de-cereri-20428.html",
        "language": "ro",
        "pages": [
            """Ghidul cetățeanului privind certificatele și autorizațiile municipale
Formulare oficiale: https://new.chisinau.md/ro/formulare-de-cereri-20428.html

1. Autorizația de construire
Pașii pentru obținerea autorizației de construire:
Pasul 1. Obțineți certificatul de urbanism.
Pasul 2. Pregătiți proiectul de execuție.
Pasul 3. Colectați avizele necesare.
Pasul 4. Depuneți dosarul complet la DGAURF sau online.
Pasul 5. Ridicați autorizația după emitere.

2. Unde depuneți
Portalul Transparenței și Ghișeul Unic oferă orientare către serviciul competent.
Ghișeul Unic: tel. +373 22 20 15 05, email primaria@pmc.md, program L-V 09:00-16:00.
""",
        ],
    },
    {
        "source_code": "ghiseu-unic",
        "title": "Informații de contact — Primăria Municipiului Chișinău",
        "url": "http://chisinau.md",
        "language": "ro",
        "pages": [
            """Contacte oficiale Primăria Municipiului Chișinău

Adresa: BD. Ștefan cel Mare și Sfânt 83, MD-2012, Chișinău.

Ghișeul Unic:
Telefon: +373 22 20 15 05 / 20 16 97 / 20 15 13
Email: primaria@pmc.md
Program: Luni–Vineri 09:00–16:00 (pauză 12:00–13:00)

Serviciul de Presă:
Telefon: +373 22 20 17 08 / 20 17 09
Email: drp@pmc.md

Linia națională anticorupție: 080055555
""",
        ],
    },
    {
        "source_code": "help-chisinau",
        "title": "Servicii de asistență medicală și socială — help.chisinau.md",
        "url": "https://help.chisinau.md/",
        "language": "ro",
        "pages": [
            """Portalul help.chisinau.md oferă informații despre serviciile de asistență medicală și socială din municipiul Chișinău.
Cetățenii pot consulta lista instituțiilor medicale teritoriale (AMT) pe sectoare: Botanica, Centru, Buiucani, Ciocana, Râșcani.
Pentru programări și detalii, accesați https://help.chisinau.md/
""",
        ],
    },
    {
        "source_code": "pretura-botanica",
        "title": "Date de contact — Pretura sectorului Botanica",
        "url": "https://botanica.md/",
        "language": "ro",
        "pages": [
            """DATE DE CONTACT — Pretura sectorului Botanica (municipiul Chișinău)

Instituție: Pretura sectorului Botanica
Adresa: str. Teilor nr. 10, sectorul Botanica, Chișinău, Republica Moldova
Telefon / fax (anticameră): 022 76-75-75
Email: pretura.botanica@pmc.md
Site oficial: https://botanica.md/

Program de lucru (orientativ): Luni–Vineri, 08:00–17:00
Petiții și cereri: se depun la sediul preturii sau online prin portalurile Primăriei Chișinău.

Notă: aceste date de contact se referă la pretura de sector (administrație publică locală),
nu la anunțuri de concurs sau funcții vacante.
""",
        ],
    },
]
