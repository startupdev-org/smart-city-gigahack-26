# CivicAI — Surse de date (Anexa 1 oficială)

Corpusul **definit** al challenge-ului. Extrase din `Annex 1_ List of Data Sources.pdf` → [`anexa.txt`](./anexa.txt).

Crawler-ul folosește **doar** aceste domenii (allowlist). Nu se indexează web-ul liber.

---

## Categorii oficiale (Anexa 1)

### Transparency & Municipal Projects

| URL | Priority |
|-----|----------|
| http://chisinau.md | P0 |
| https://www.chisinau.md/ro/transparenta | P0 |
| https://suburbii.chisinau.md/ | P1 |
| https://proiecte.chisinau.md/ | P1 |

### Urban Mobility

| URL | Priority |
|-----|----------|
| https://mobilitatechisinau.md/ | P1 |
| https://rtec.md/ | P1 |
| https://autourban.md/ro/rute/suburbane | P2 |
| https://exdrupo.md/ | P2 |

### Architecture, Green Spaces & Urban Utilities

| URL | Priority |
|-----|----------|
| https://dgaurf.md/ | P0 |
| https://dglca.md/ | P1 |
| https://autosalubritate.md/informatie-de-contact/ | P1 |
| https://www.acc.md/ | P2 |
| https://agsv.md/diagrama-defrisare-curatare-a-arborilor-2/ | P2 |

### Education

| URL | Priority |
|-----|----------|
| https://chisinauedu.dgets.md/ | P1 |
| https://detsriscani.md/ | P2 |
| https://detsciocana.educ.md/ | P2 |
| https://detscentru.md/ | P2 |
| https://buiucanidets.md | P2 |
| https://detsbotanica.md | P2 |
| https://educatieonline.md/ | P2 |
| https://extrascolar.md/ | P2 |
| https://egradinita.md/ | P2 |
| https://escoala.chisinau.md/ | P2 |

### Healthcare

| URL | Priority |
|-----|----------|
| https://dgams.md/ | P1 |
| https://help.chisinau.md/ | P1 |
| https://amt-botanica.md/ | P2 |
| https://amt-centru.md/ | P2 |
| https://amtbuiucani.md/ | P2 |
| https://amt-ciocana.md/ | P2 |
| http://amtriscani.md/ | P2 |

### District Administration

| URL | Priority |
|-----|----------|
| https://www.botanica.md/ | P2 |
| https://chisinaucentru.md/ | P2 |
| https://ciocana.md/ | P2 |
| https://rascani.md/ | P2 |
| https://preturabuiucani.md/ | P2 |

### Services (Commerce, Tourism, Investment, Youth)

| URL | Priority |
|-----|----------|
| https://comert.chisinau.md/ | P1 |
| https://visit.chisinau.md/ | P1 |
| https://invest.chisinau.md/ | P1 |
| https://proiecte.chisinau.md/ro/pv-289-startup-pentru-tineri-si-migranti | P2 |
| https://e-tineret.md/ | P2 |

### Other Public Services

| URL | Priority |
|-----|----------|
| http://www.infocom.md/ | P2 |
| https://liftservice.md/ | P2 |

**Total Anexa 1:** 42 URL-uri.

---

## Seed demo (primele 30% — deja în DB)

Folosite de `python -m backend.scripts.init_db`:

| Document | Scenariu |
|----------|----------|
| Regulamentul autorizării construcțiilor (DGAURF) | Normal + termen **30 zile** |
| Dispoziția Primarului 412/2025 | Conflict — termen **20 zile** |
| Ghidul cetățeanului — Certificate și Autorizații | Pași + navigare |
| Contacte Ghișeul Unic | Contact / next-action |
| help.chisinau.md | Healthcare |

---

## Mapping topic → URL (navigare must-have)

| Topic RO | Topic RU | URL |
|----------|----------|-----|
| autorizatie construire | разрешение на строительство | https://dgaurf.md/ |
| transparenta | прозрачность | https://www.chisinau.md/ro/transparenta |
| contact general | общий контакт | http://chisinau.md |
| sanatate | здоровье | https://help.chisinau.md/ |
| mobilitate | мобильность | https://mobilitatechisinau.md/ |
| educatie | образование | https://chisinauedu.dgets.md/ |
| comert | торговля | https://comert.chisinau.md/ |
| lifturi | лифты | https://liftservice.md/ |

---

## Strategie crawl

1. **P0** acum (transparenta, chisinau.md, dgaurf) + seed demo  
2. **P1** după RAG stabil  
3. **P2** volum suplimentar  

Allowlist = toate domeniile din Anexa 1.
