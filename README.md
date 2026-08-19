# 🇽🇰 Skaneri i Pronës dhe Investimeve në Kosovë

> Një vegël vendimmarrëse e bazuar në të dhëna që ndihmon njerëzit të vendosin **ku në Kosovë të blejnë pronë ose të investojnë në një biznes**, e ndërtuar tërësisht mbi të dhëna të hapura qeveritare.

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/status-hackathon%20build-success">
  <img alt="Të dhënat" src="https://img.shields.io/badge/të%20dhënat-ASKdata%20%2B%20World%20Bank-blue">
  <img alt="Licenca" src="https://img.shields.io/badge/licenca-MIT-lightgrey">
</p>

---

## Çfarë bën

Kosova ka statistika të pasura të hapura — investime sipas rajonit, fluks turistësh, çmime banesash dhe regjistrime biznesesh — por ato jetojnë në tabela të veçanta që janë të vështira për t'u lexuar bashkë. Kjo vegël i bashkon në një skaner të vetëm që u përgjigjet dy pyetjeve praktike:

- **Po blen pronë?** Cili nga 7 rajonet e Kosovës ka momentumin më të mirë për paratë, duke marrë parasysh trendet e çmimeve të banesave dhe rritjen e investimeve.
- **Po investon në biznes?** Cili sektor në cilën nga 38 komunat po rritet, është i pambuluar, ose ia vlen një shikim më nga afër.

Çdo renditje lidhet përsëri me numrat zyrtarë që qëndrojnë pas saj, dhe çdo rajon/sektor mban një përmbledhje të shkurtër hulumtimi të verifikuar. Është një **vegël skanimi, jo këshillë financiare** — një pikënisje për një bisedë, jo një rekomandim.

## Pse është ndryshe

- **Të dhëna reale, të drejtpërdrejta të hapura** — të marra direkt nga API-ja PxWeb e ASKdata dhe Banka Botërore, jo CSV të ngarkuara me dorë.
- **Tri-plus datasets vërtet të lidhura** — investimet, turizmi, banesat dhe regjistrimet e bizneseve ndajnë një çelës rajon/komunë dhe analizohen bashkë, jo thjesht shfaqen krah për krah.
- **I ndershëm nga dizajni** — mohimi i përgjegjësisë qëndron në vetë faqen, dhe asnjë analizë nuk publikohet pa u kontrolluar kundrejt numrave që përshkruan.

## Burimet e të dhënave

Të gjitha të dhënat janë të hapura dhe falas. Tabelat e ASKdata janë endpoint-e [PxWeb](https://www.scb.se/en/services/statistical-programs-for-px-files/px-web/) me API të drejtpërdrejtë (`GET` për metadata, `POST` me një JSON query për të dhënat).

| #   | Dataset-i                                                            | ID                 | Mbulimi       | Burimi                                      |
| --- | -------------------------------------------------------------------- | ------------------ | ------------- | ------------------------------------------- |
| 1   | Investimet sipas rajonit & kategorisë së investimit                  | `inv04.px`         | 2018–2024     | ASKdata — Investimet në Ndërrmarrje         |
| 2   | Vizitorët & netët e qëndrimit (vendas & të huaj) sipas rajonit       | `ht03.px`          | 2008–2025     | ASKdata — Turizmi & hotelet                 |
| 3   | Kapacitetet hoteliere sipas rajonit                                  | `ht02.px`          | 2017–2025     | ASKdata — Turizmi & hotelet                 |
| 4   | Indeksi i Çmimeve të Banesave (2018=100), Prishtina vs. pjesa tjetër | `IPBN02.px`        | 2018Q1–2026Q1 | ASKdata — Çmimet                            |
| 5   | Ndërmarrjet e regjistruara sipas komunës & sektorit                  | `enterprises03.px` | 2019Q1–2023Q4 | ASKdata — Regjistri statistikor i bizneseve |
| 6   | Rritja e BPV-së & IHD (% e BPV-së) — konteksti kombëtar              | —                  | më e fundit   | World Bank (`XKX`)                          |

**API bazë:** `https://askdata.rks-gov.net/api/v1/en/ASKdata/`
**World Bank:** `https://api.worldbank.org/v2/country/XKX/indicator/{kodi}?format=json`

## Si funksionon

```
ASKdata (PxWeb API) ─┐
World Bank API ──────┼──▶  Pipeline  ──▶  data.json  ──▶  Aplikacioni (listë e renditur + detaje + grafikë)
                     │   (merr, pastro,     (një formë
Harta e aliaseve ────┘    bashko, vlerëso)     e rënë dakord)
```

I gjithë ekipi ndërton kundrejt **një forme të vetme të rënë dakord të të dhënave** (kontrata e të dhënave më poshtë) që nga minuta e parë. Pipeline-i merr dhe ruan (cache) të dhënat live në disk; aplikacioni gjithmonë lexon vetëm skedarin e ruajtur, kështu që një API i ngadaltë ose i prishur në mes të demos nuk e rrëzon kurrë aplikacionin.

### Kontrata e të dhënave

```json
{
  "national": {
    "gdp_growth_pct": 4.2,
    "fdi_pct_gdp": 10.0,
    "last_updated": "2026-08-19"
  },
  "regions": [
    {
      "name": "Prishtinë",
      "aliases": ["Prishtina"],
      "coordinates": { "lat": 42.6629, "lon": 21.1655 },
      "investment_yoy_pct": 14.2,
      "tourism_gap_score": 0.82,
      "housing_bucket": "prishtina"
    }
  ],
  "housing": {
    "prishtina": { "index_2018_base": 100, "index_latest": 138 },
    "rest": { "index_2018_base": 100, "index_latest": 121 }
  },
  "business_sectors": [
    {
      "code": "I",
      "name": "Accommodation and food service",
      "by_municipality": {
        "Prishtinë": { "count_latest": 412, "growth_pct": 9.1 }
      }
    }
  ],
  "insights": {
    "Prishtinë": "Teksti i përmbledhjes...",
    "sector:I:Prishtinë": "Teksti i përmbledhjes..."
  }
}
```

> Emrat e fushave janë pjesë e kontratës. Nëse pipeline-i dërgon `investmentYoy` dhe aplikacioni pret `investment_yoy_pct`, ky është një bug i orës së fundit që nuk kushtonte asgjë të parandalohej që në fillim.

## Ekipi & përgjegjësitë

Ekipi punon **në paralel, jo në seri** — të gjithë ndërtojnë kundrejt kontratës së të dhënave-mostër menjëherë, dhe të dhënat reale futen afër fundit pa ndryshuar asgjë tjetër.

| Roli                               | Përgjegjës për                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **A — Të dhënat & Pipeline**       | Lidhet me ASKdata + World Bank, pastron dhe bashkon numrat, dërgon `data.json`-in real.                |
| **B — Aplikacioni / Frontend**     | Ekrani që njerëzit shohin — lista e renditur, pamja e detajeve, grafikët, slider-at dhe përzgjedhësit. |
| **C — Analiza & Insight-et me AI** | Formulat e vlerësimit dhe përmbledhjet hulumtuese të gjeneruara me AI e të verifikuara.                |
| **D — Dizajni, QA & Prezantimi**   | Sistemi vizual, testimi nga fillimi në fund, dhe prezantimi i demos.                                   |

<details>
<summary><strong>Ndarja e punës sipas rolit</strong></summary>

**A — Të dhënat & Pipeline**

- Konfirmo thirrjet reale të API-së; testo query-n e saktë PxWeb `POST` kundrejt secilës tabelë të ASKdata.
- Ndërto hartën e aliaseve të emrave rajon/komunë (Gjakovë vs. Gjakova, etj.).
- Merr dhe normalizo të dhënat e investimeve, turizmit dhe banesave në formën e rënë dakord; shto dy indikatorët e World Bank.
- Tërhiq tabelën e regjistrimit të bizneseve sipas sektorit (38 komuna); zëvendëso të dhënat-mostër me numra realë, të njëjtët emra fushash.

**B — Aplikacioni / Frontend**

- Ndërto guaskën statike (listë e renditur + panel detajesh) kundrejt të dhënave-mostër.
- Lidh rrugën e pronës: logjika e pragut të buxhetit, renditja e rajoneve, pamja interaktive e detajeve.
- Lidh rrugën e biznesit: përzgjedhësi i sektorit + pamja e komunës, slider-i i ripeshimit live, afërsia/distanca.
- Rregullo: tranzicionet, dark mode, pamja e tabelës e qasshme.

**C — Analiza & Insight-et me AI**

- Përcakto formulat e momentumit, hendekut të turizmit dhe rritjes së biznesit si funksione të shkurtra, të dokumentuara.
- Ndërto dhe testo template-in e përmbledhjes hulumtuese; dizajno një flamur anomalie të mbrojtshëm për çdo rajon.
- Gjenero dhe ruaj insight-et reale sapo të vijnë të dhënat; kontrollo çdo pohim kundrejt numrave të tij.
- Zgjidh gjetjen vërtet befasuese për të hapur prezantimin.

**D — Dizajni, QA & Prezantimi**

- Vendos paletën, specifikat e grafikëve dhe tabelën e koordinatave të 7 rajoneve.
- Drafto prezantimin dhe tekstin e mohimit të përgjegjësisë për në faqe.
- Testo nga fillimi në fund si përdorues për herë të parë; regjistro çdo gjë konfuze ose të prishur.
- Bëj një provë të plotë e të matur me kohë kundrejt aplikacionit real.

</details>

## Si të fillosh

> Përshtat komandat më poshtë me stack-un që përdor vërtet.

```bash
# 1. Klono
git clone https://github.com/<organizata-jote>/kosovo-investment-screener.git
cd kosovo-investment-screener

# 2. Ndërto skedarin e të dhënave (merr ASKdata + World Bank, shkruan data.json)
python pipeline/build_data.py        # ose: npm run build:data

# 3. Nis aplikacionin
npm install
npm run dev
```

Ndërsa pipeline-i është ende në zhvillim, aplikacioni punon kundrejt `sample_data.json` — e njëjta formë si skedari real — kështu që frontend-i nuk pret kurrë të dhënat.

## Përkufizimi i "të mbaruar" (Definition of done)

- Një i panjohur hap aplikacionin, kupton se për çfarë shërben brenda 10 sekondave, dhe gjen një insight të saktë e specifik pa iu treguar ku të shohë.
- Të dyja rrugët — blerja e pronës dhe investimi në biznes — funksionojnë nga fillimi në fund me të dhëna reale.
- Të paktën një gjetje është vërtet befasuese, jo thjesht "kryeqyteti është më i madhi".
- Mohimi i përgjegjësisë si vegël skanimi është i dukshëm në vetë faqen.
- Prezantimi hapet me atë gjetje, jo me një turne të veglës.

## Mohim përgjegjësie

Kjo është një **vegël skanimi dhe hulumtimi**, jo këshillë financiare, investuese ose ligjore. Shifrat vijnë nga burime zyrtare të hapura dhe mund të kenë vonesa ose rishikime. Verifiko gjithmonë kundrejt burimeve parësore para se të marrësh një vendim.

## Licenca

E publikuar nën Licencën MIT. Të dhënat u përkasin ofruesve përkatës — [Agjencia e Statistikave të Kosovës (ASK)](https://askdata.rks-gov.net) dhe [Banka Botërore](https://data.worldbank.org) — dhe përdoren sipas kushteve të tyre të të dhënave të hapura.
