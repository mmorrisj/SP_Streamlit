# MENA Theater Assessment — Cross-Actor Soft-Power Competition
### China · Iran · Russia · Turkey | Strategic Influence in the Middle East & North Africa

*Observation window 2024-08-01 → 2026-06-30 (23 full months). Open-source media corpus, 765K
documents; method, lineage, and scope per [`../../INTEL_REPORT_PROMPT.md`](../../INTEL_REPORT_PROMPT.md).
Unit of analysis: the **corroborated initiative** (named canonical event with ≥50% third-party
coverage from ≥3 independent outlets), not the article. Every figure's underlying numbers are
persisted as a sibling CSV in [`assets/`](assets/). Produced by a five-thread agentic
investigation with two-lens adversarial verification of every finding (57 findings: 38
workflow-verified, 19 re-verified inline; 0 refuted, 14 revised with corrections applied).*

---

## 1. Key Judgments

1. **Raw media volume inverts the truth of this theater.** Iran generates 138,060 scoped
   document-rows — 2× any rival — but 82% is its own state media, and only **7.6% of its 3,651
   extracted initiatives survive the corroboration gate** (≥50% third-party, ≥3 outlets), versus
   63–71% for China, Russia, and Turkey. At the high-material tier Iran holds 15 initiatives
   against Turkey's 119, Russia's 97, and China's 87 — an ~8× deficit. Iran is a narrative giant
   and an initiative dwarf. *(High confidence)*

2. **Turkey is the theater's largest credible influence actor.** It leads corroborated volume
   (57,674 docs), gated initiatives (1,416), and high-material slots, and it owns the corpus's
   highest-substance events — the Oct 2025 Gaza ceasefire architecture (Cairo signing: 1,199
   articles, 231 distinct outlets), the Jul 2025 PKK disarmament ceremony (95 outlets), and the
   Syria file, where it now holds **454 of 619 corroborated initiatives (73%)**. Its playbook
   converts conflict adjacency into mediation equity, then mediation equity into economics
   (the $7B Syria energy MOU; the Feb 2026 Saudi/Egypt normalization wave). *(High confidence)*

3. **China is the economic patron, and its money is concentrated and real — in Egypt.** China
   holds 275 corroborated economic initiatives (3× Russia, 17× Iran) and sweeps every qualifying
   civilian lane in Egypt, Kuwait, UAE, Saudi Arabia, and Bahrain. Its verifiable announced
   money clusters in the Suez Canal Economic Zone / Ain Sokhna corridor: **~$24B across ~27
   deals** after noise removal — a corridor whose Chinese-financed lineage AidData traces to a
   2009 China Eximbank/CDB credit for the TEDA zone. In 2026 China layered a new asset on top:
   an institutionalized US–Iran mediator role marketed to Gulf audiences (5 high-material
   mediation events, 28–64 outlets each). *(High confidence)*

4. **Russia is the structural loser of the window.** Five of its relationships decayed 64–88%
   from baseline (Syria 272→46 docs/mo, Turkey −88%, Egypt −64%, UAE −69%, Palestine −68%), its
   flagship Iran channel halved after the June 2025 war (cp 2025-08, z=3.45), and its
   high-material initiative pipeline shrank from 27/quarter (Q4-2024) to 3 (Q2-2026). What
   remains is narrow and physical: El Dabaa NPP in Egypt — the corpus's most durable project
   (37 events across 17 months) — Bushehr, BRICS convening, and a hedged Syria posture in which
   it is the only actor whose network bridges both the deposed Assad and successor al-Sharaa
   governments. *(High confidence)*

5. **The theater reset in Nov–Dec 2024, and the data timestamps it.** Fourteen of the fifty
   largest changepoints fall in those two months — all declines: the Lebanon ceasefire and
   Assad's fall ended the "Axis of Resistance" coverage regime (Iran→Yemen z=11.4, the sharpest
   break in the dataset — never replaced by any actor), killed the Astana venue within seven
   weeks, and opened the Syria vacuum that Turkey filled (11.5 → 21.7 corroborated
   initiatives/month). *(High confidence)*

6. **The dominant early-warning complex for H2 2026 is a four-way mediation race around the
   US–Iran/Hormuz crisis.** Iran's corroborated initiative flow quadrupled (98 in Q2-2026, 11
   high-material — from a 0–1/quarter baseline) behind a genuine, third-party-attested pivot to
   GCC détente and Lebanon ceasefire brokerage; China institutionalized the US–Iran broker role;
   and Turkey pre-positioned on the Tehran file at cp Nov-2025 (z=3.95, Fidan's Tehran visit →
   the Jan 2026 Ankara US–Iran trilateral, 95 outlets) — **the only true lead indicator found in
   the dataset**. Caveat: Iran's flagship "Iran-Brokered" Lebanon ceasefire event carries
   credit-claiming naming; its top underlying headline is "Iraq-Iran Diplomatic Engagement."
   *(Moderate-to-high confidence)*

7. **The four networks are wired differently, and the wiring is the strategy.** China is
   institution-wired (organizations carry 47% of top-node weight; brokerage funnels through an
   Egyptian megaproject corridor: Madbouly–SCZONE–CSCEC–New Administrative Capital). Turkey is
   leader-wired (Erdoğan + Gaza + the Öcalan/PKK file; its hidden brokers are its Cairo embassy
   and Egyptian industrial satellite cities). Russia is project-wired (nuclear plants as network
   anchors). Iran is person- and religion-wired: **195 religious entities (8.9% of its
   footprint) — an order of magnitude above Turkey (33) and two above Russia/China** — with the
   Red Crescent as the highest-betweenness organization in any actor's network. The region's
   most contested intermediary is Oman's FM Badr al-Busaidi, present in all four actors'
   networks. *(Moderate-to-high confidence)*

8. **There is no sequencing playbook to exploit for warning.** All four actors' category series
   co-move at lag 0 (correlations collapse by lag 1), so monthly media data gives no 1–3 month
   "diplomacy precedes economics" signal. Cross-actor structure is the usable signal instead:
   China–Russia move together region-wide (mean r=+0.246, permutation p=0.001) while
   China–Turkey are the competing pair — Turkey's Saudi surge came precisely as China cooled
   there (r=−0.43, the strongest anti-correlation measured). *(Moderate confidence)*

---

## 2. How to Read the Numbers

**The corroboration doctrine.** This corpus is Middle Eastern media reporting, not a ledger of
activity. It over-indexes on Iranian state media (82 Iran-geofocus outlets; the top 8 sources by
volume are all Iranian). Every magnitude in this report is therefore computed on the
**third-party-corroborated basis** (coverage not from the initiator's own media ecosystem) and,
wherever possible, at the **initiative grain** (`analytics.initiative_ledger`): distinct named
canonical events, gated at ≥50% third-party share and ≥3 independent outlets, weighted by an
LLM materiality score (1–10). Raw volume appears only as contrast.

**The gate is asymmetric — and that asymmetry is itself a finding but also a limit.** Only Iran
(82 outlets) and marginally China (2) have domestic media ingested; Russia and Turkey have
zero. Their near-perfect corroboration shares are corpus composition, not validation. The valid
cross-actor claims are therefore: (a) Iran's footprint is overwhelmingly self-manufactured
(directly measured), and (b) magnitudes for all four are comparable only on the corroborated
basis. Where a finding could be a composition artifact, the verification pass tested it by
excluding recipient-side and aligned outlets; survival is noted in place.

![Provenance quadrant](assets/01_provenance_quadrant.png)
*Fig 1 — Every Iranian relationship sits in the projection zone (corroborated share 0.05–0.26);
every China/Russia/Turkey relationship sits above 0.69. The y-axis is the honest denominator
for everything that follows. (High confidence; n=63 relationships ≥200 docs.)*

![Corroborated leaderboard](assets/02_corroborated_leaderboard.png)
*Fig 2 — On the corroborated basis the ranking inverts: Turkey 57,674 > China 44,760 > Russia
40,985 > Iran 20,748. Iran's raw lead (138K) is 85% self-reported.*

![Initiative gate](assets/03_initiative_gate.png)
*Fig 3 — The initiative funnel: total extracted → corroborated (≥50% third-party, ≥3 outlets) →
high-material (score ≥6). Iran: 3,651 → 277 → 15. Turkey: 2,014 → 1,416 → 119.*

---

## 3. The Influence Market: Four Models, Four Lanes

All four actors are diplomacy-led on the corroborated doc basis (47–69%), so the signature is
in the second instrument and in what survives to the initiative grain:

- **China builds.** Instrument over-representation vs. theater average: Industrial 2.6×,
  Technology 2.5×, Education 2.0×, Infrastructure 1.6× — ratios that *strengthen* when all
  Iran-geofocus outlets are excluded. 275 corroborated economic initiatives. Note the
  dependency: 71% of China's industrial coverage is Egypt-focused.
- **Turkey delivers and mediates.** Aid/Donation 14.8% of mix (1.4×, n=7,340 docs) and Conflict
  Resolution 1.3× — robust to excluding aligned Qatari and Iranian outlets.
- **Iran and Russia talk.** Both over-index on negotiations/bilateral-commitment subcategories;
  Russia's non-diplomatic corroborated base is 17–28% of its ledger vs China's 38–46%.
- **Iran's distinctive lane — religious/social projection — is real but almost entirely
  self-reported** (see §5 and the Arbaeen quantification in §6).

![Category signature](assets/04_category_signature.png)
*Fig 4 — Category mix of third-party docs. The doc-level "diplomacy convergence" partially
reflects multi-category counting; initiative-grain shares confirm China holds the largest
non-diplomatic corroborated base. (Verification note: the apparent systematic doc-to-initiative
diplomacy rise is mostly a measurement artifact and is not used as a finding.)*

**Concentration.** Doc-level Lorenz/HHI suggests Russia is the most focused actor (HHI 0.19,
38% of its third-party docs on Iran) — but verification showed 78% of Russia→Iran "third-party"
docs are Iran's own recipient-side outlets; stripped of recipient media Russia's HHI falls to
0.12, and **at the initiative grain concentration is nearly flat across all four actors
(~0.11–0.12)**. The honest statement: no actor holds a portfolio the others don't contest.

![Lorenz](assets/09_concentration_lorenz.png)
*Fig 5 — Doc-basis concentration, shown with its bias caveat. Use initiative-grain HHI for
cross-actor claims.*

**Empirical blocs.** Ward clustering of recipients by who-engages-them-on-what (third-party
profile vectors, k=3 by silhouette) yields three interpretable blocs that partly confirm and
partly correct the assumed map *(moderate confidence)*:

| Bloc | Members | What defines it | Surprise |
|---|---|---|---|
| **Turkey's arena** | Syria, Palestine, Israel, Libya, Cyprus | Turkey:Diplomacy 33–46% of each profile | **Israel clusters here** — the bloc captures "where Turkey sets the agenda," including adversarially |
| **China's economic Gulf+Egypt** | Egypt, Saudi Arabia, UAE, Kuwait, Bahrain, Jordan, Yemen, Iran-as-recipient | China leads Economic+Social lanes | **Yemen lands here** — Iran's channel collapsed and China is the nominal residual leader of an abandoned market |
| **Iran–Turkey diplomatic corridor** | Iraq, Lebanon, Oman, Qatar, Turkey-as-recipient | Mediation-channel traffic | **Oman and Qatar cluster with the corridor, not their GCC peers** — the Muscat/Doha channel function dominates their profiles |

![Competitive heatmap](assets/05_competitive_heatmap.png)
*Fig 6 — Corroborated intensity by recipient × actor, rows grouped by empirical bloc. No cell
column is empty: no MENA recipient is a single-patron market (max patron HHI 0.48, Palestine).*

**Head-to-head lanes** (55 recipient×category lanes with ≥300 third-party docs): China sweeps
every qualifying civilian lane in Egypt, Kuwait, UAE, Saudi Arabia (Economic 53–74%, Social
53–65%); Turkey wins Diplomacy in Iraq (53%), Israel (50%), Palestine (65%), Jordan (44%) and
every civilian lane in Syria and Libya; Iran holds only legacy-proxy ground (Lebanon Diplomacy);
**Russia wins almost nothing civilian outside fellow-initiator states** — its regional offer has
narrowed to Iran, Turkey, and the Syrian military file. *(High confidence)*

---

## 4. Contested Terrain, Collisions, and Handoffs

**Egypt is the premier contested market.** Third-largest corroborated-initiative base (624),
top-4 on quarter-by-category collision cells. China leads on initiative count (333, 53%) and
every civilian lane; Russia leads per-initiative weight (El Dabaa); Turkey leads momentum
(Economic docs 40→77/mo into 2026-H1; 18 agreements signed Feb 2026; the 2026 Business Forum
with Erdoğan and el-Sisi, 75 outlets). *(High confidence)*

**The Syria handoff is the cleanest substitution event in the data** *(high confidence)*:

![Syria substitution](assets/06_syria_substitution.png)
*Fig 7 — Iran: ~198 → 15 → 8 third-party docs/mo (−95%, zero-doc months by 2026). Turkey:
doubled through 2025 (233→477/mo), still ~5.5× Russia in 2026-H1, with a civilian mix (post-2025:
Diplomacy 4,883 / Social 1,935 / Economic 1,545 / Military 218 docs) and 327 corroborated
initiatives launched vs 49 pre-Assad. Russia decayed in two steps but did not exit.*

**Three subtler dynamics** *(moderate-to-high confidence)*:
- **Russia→Turkey rotation on the Iran file.** After the Jun 2025 war, Russia→Iran suffered the
  dataset's largest single-relationship drop (−370 docs/mo; Moscow's muted wartime support is
  directly visible), while Turkey→Iran surged at cp Nov-2025 — verified as independently
  corroborated (90–103 distinct non-Iranian outlets/month in Jan–Apr 2026), not an Iranian-media
  artifact. Ankara is building itself into the West's channel to Tehran.
- **Saudi Arabia: Turkey up exactly as China cools** (r=−0.43, strongest anti-correlation
  measured). Turkey's Feb 2026 surge (z=4.23; 305 third-party docs incl. 125 from 16
  Saudi-focus outlets — recipient-side validation) is materially anchored (Riyadh investment
  forum, $2B solar deal).
- **Lebanon: collective disengagement, then a re-entry race.** All four actors collapsed 66–82%
  after the Nov 2024 ceasefire (z=3.0–6.1, survives excluding Lebanese outlets). In 2026-H1 Iran
  rebounded hardest (to 240 docs/mo, 74% Diplomacy — its ceasefire-brokerage role), with a
  synchronized China+Turkey re-entry in Apr 2026. **Yemen was never re-entered by anyone**: after
  the z=11.4 break it is now the region's least patron-concentrated market on both metrics.

---

## 5. Actor & Network Structure

*(All network findings rest on structure — ranks, betweenness-vs-degree gaps, shares — not raw
size, which is Iran-inflated. Entity linkage caveat in §8.)*

**Four wiring diagrams** *(high confidence)*:

| Actor | #1 hub | Person share of top-30 weight | Signature broker (betweenness ≫ degree) |
|---|---|---|---|
| China | Foreign Ministry (wdeg 145) | 25% — institution-wired | PM Madbouly, SCZONE's Gamal El-Din, CSCEC, New Administrative Capital — a narrow Egyptian megaproject corridor |
| Iran | FM Araghchi (wdeg 850, 3,309 docs) | 66% — person-wired | Ilam Province / Iran–Iraq border / Interior Min. Momeni — the pilgrimage corridor (⚠ 87–94% self-reported; brokerage largely evaporates in a corroborated-only graph) |
| Russia | El Dabaa NPP among top nodes | project-wired | **Both Assad (post-fall, from Moscow) and al-Sharaa** bridge its network — hedged base-retention diplomacy |
| Turkey | Gaza Strip (wdeg 572) + Erdoğan (506) | leader-wired | Cairo ambassador Salih Mutlu Şen (bc rank 3 vs wdeg rank 23); 10th-of-Ramadan & 6th-of-October industrial cities — where Turkish manufacturers cluster in Egypt |

**The religious asymmetry is an order of magnitude and it is Iran's alone** *(high confidence)*:
Iran fields 195 religious entities carrying 8.9% of its entity-document footprint (Red Crescent
complex, Hajj Organization, Arbaeen infrastructure, clerical-educational exports like
Al-Mustafa); Turkey 33 (0.7%, Diyanet-centric); Russia and China effectively none of their own.
The Iranian Red Crescent is the highest-betweenness *organization* in any actor's network
(bc rank 4, outranking Iran's own Foreign Ministry) — humanitarian cover as structural glue
linking the diplomatic cluster to axis-of-resistance humanitarian channels (reach: Iraq,
Lebanon, Gaza/Palestine, Yemen).

**Contested intermediaries and shared venues** *(moderate-to-high confidence)*: 621 entities
(8.8%) appear in ≥2 initiators' networks. The most contested person is **Oman's FM Badr
al-Busaidi** (all four networks + the US file: Iran 717 docs, US 338, Russia 37, China 20,
Turkey 7) — the Muscat nuclear channel made him everyone's connector. Egypt's FM Abdelatty and
Syria's FM al-Shibani follow (Turkey out-engages Russia ~2.6:1 for post-Assad Damascus). The
Astana Process was the one venue Iran/Russia/Turkey co-inhabited — and it died within seven
weeks of Assad's fall (last mentions Dec 2024–Jan 2025, zero activity since). Sharm el-Sheikh
is Turkey's stage. **Transnational operators** (≥4-recipient corroborated reach): Turkey 167,
Iran 148, Russia 116, China 97 — and China's wide-reach assets are forums (FOCAC, BRICS), not
people. (Iran's precomputed "43% of wide-reach entities" collapses by 68% when self-reported
docs are excluded — retained only as a projection measure.)

---

## 6. The Initiative Ledger — What Was Actually Done

*(The report's evidentiary core: 3,601 gated initiatives; full ranked list with event IDs in
[`assets/10_initiative_ledger.csv`](assets/10_initiative_ledger.csv).)*

![Initiative ledger](assets/10_initiative_ledger.png)
*Fig 8 — The theater's highest-substance corroborated initiatives. Turkey's ceasefire
architecture and Russia's convening/nuclear anchors dominate the top tier; Iran appears once.*

**Four playbooks, quantified by initiative families** *(high confidence)*:

| Actor | Playbook | Anchor families (events / months of recurrence / third-party docs) |
|---|---|---|
| **Turkey** | Mediation equity → economics | Gaza ceasefire 62/18/2,044 · PKK disarmament 30/10/509 · Syria reconstruction 33/11/435 · Development Road 17/12/124 |
| **China** | Transactional projects | Suez Canal Economic Zone 23/15 · Mubarak Al-Kabeer Port (Kuwait) 15/11/172 · $4B Basra desalination · ~30 Egypt dollar deals |
| **Russia** | Institutions + concrete steel | BRICS 66/16/832 · **El Dabaa 37/17/495 — the corpus's most durable project** (pressure-vessel installation Nov 2025, 18 outlets) · Russia–Iran treaty 38/17/514 |
| **Iran** | Narrated presence | Arbaeen 199/18 — but only **204 of 3,973 docs (5.1%) third-party**; concrete corroborated activity is small-bore Iraq/Lebanon economics + one Houthi training program (27 outlets, corr 0.89) |

**The Arbaeen number is the cleanest single quantification of the bias this report controls
for**: a genuinely recurring activity whose apparent scale is manufactured almost entirely by
Iran's 82-outlet domestic ecosystem. Contrast El Dabaa (495/495 third-party) or Turkey's Gaza
mediation (2,044 third-party).

**Announced money is not transacted money** *(high confidence)*. Dollar-named corroborated
initiatives: Turkey $296B across 20 (dominated by aspirational targets — the $100B Gaza
compensation proposal, 7 outlets; the $53B OIC endorsement; a $30B Iran trade *target*); Russia
$91B across 9 (of which $75B is a single announced Iran NPP **triple-counted** across three
near-duplicate canonical events at 5–13 outlets each); China $75B across 49 — but China's are
transaction-shaped: the cleaned **Egypt-specific ~$23.7B/27 deals** includes doc-level verified
figures ($1.15B Ain Sokhna signing; $2.7B potash; $1.6B phosphate complex; $2B Saudi dollar-bond
issuance). Turkey's genuinely transactional deals are an order of magnitude below its
announcements ($7B Syria energy MOU, 27 outlets). **AidData cross-check (China):** no
same-project match for any 2024–26 headline project (expected — AidData ends 2023); the
meaningful corroboration is locational lineage — record 41017 (2009 Eximbank/CDB credit for the
TEDA Suez zone) documents two decades of Chinese financing under today's reported corridor.

**Durability must be read as family recurrence, not span**: the pipeline caps median event span
at 1 day (only 9 of 8,555 events span ≥30 days), so persistence = the same named initiative
recurring across canonical events, as tabulated above.

**Excluded as extraction noise** (verified mis-tags, removed from all top-tier claims): the
China–Nigeria $1B railway (Egypt mis-tag), the Norway-led $1.8B "Energy Valley" credited to
China, Zelensky–Putin Istanbul talks (venue ≠ recipient), BRICS-Indonesia expansion, an unnamed
Turkey→Iran "Peace Agreement Signing Ceremony," and similar framing artifacts. The "Iran-Brokered
Comprehensive Ceasefire in Lebanon" event is retained but flagged: its top underlying headline
attributes the engagement to Iraq–Iran diplomacy — Iranian credit-claiming naming.

---

## 7. Temporal Dynamics & Early Warning

![Tempo and changepoints](assets/07_tempo_changepoints.png)
*Fig 9 — Monthly corroborated tempo per actor with statistically detected changepoints (binary
segmentation, |z|≥2.5) against the trigger calendar.*

**The window divides into three regimes** *(high confidence)*:

1. **Nov–Dec 2024 mass reset.** 14 simultaneous declines: Iran loses Yemen (z=11.4), Palestine,
   Lebanon, Israel — the Axis-of-Resistance coverage regime ends; Russia loses its
   Syria-anchored channels (Russia→Turkey −81%, a Syria knock-on: the Astana/deconfliction
   channel died with Assad); Turkey doubles into the Syria vacuum.
2. **Jun 2025 Iran–Israel war reshuffle.** Turkey +1,113 docs/mo and China +585 accelerate into
   the aftermath; Russia→Iran takes the dataset's largest relationship drop; Turkey converts the
   Oct 2025 Gaza ceasefire into **33 high-material initiatives in Q4-2025 — the highest
   actor-quarter recorded** (next best: Russia's 27 in Q4-2024).
3. **2026-H1 US–Iran/Hormuz crisis → four-way mediation race** (Key Judgment 6). Iran's
   corroborated flow quadruples behind GCC détente and Lebanon brokerage; China institutionalizes
   the US–Iran broker role; Turkey's Nov-2025 Tehran pre-positioning is the one changepoint that
   *led* a crisis rather than following one.

![Narrative themes](assets/11_narrative_themes.png)
*Fig 10 — Semantically-clustered initiative families spanning ≥3 recipients. The live 2026
clusters (Hormuz mediation, US–Iran MOU, permanent-ceasefire brokerage) are the mediation race;
the durable ones (Arbaeen, Hejaz railway, Huawei ICT competitions) are standing campaigns.*

**H2-2026 watchboard** *(moderate confidence — leading-edge items by design)*:
- **Turkey's Hejaz Railway revival** (Syria–Jordan–Saudi corridor; first mention Jun 2 2026, 18
  outlets, corr 1.0) — infrastructure that would physically wire Turkey's Levant position into
  the Gulf.
- **Turkey–Egypt/Saudi economic normalization wave** (Economic docs 5→32/mo toward Riyadh,
  40→77/mo toward Cairo).
- **The reactivated Muscat channel** (Iran–Oman nuclear talks resurging after the mid-2025
  strike pause; al-Busaidi the pivot).
- **China's Libya re-entry** (cp Apr 2026, z=3.65; consulate reopening + strategic-partnership
  mechanism = the standard Chinese re-entry opening sequence).
- **China→Iraq silence** after the $4B Basra desalination launch — an unexplained
  project-pipeline pause worth a collection question.
- **Decay watch:** Russia broadly (KJ4); Iran→Yemen still unreplaced; China→Saudi cooling.

---

## 8. Intelligence Gaps & Collection Priorities

**What this corpus cannot tell you.**
- **Russia's and Turkey's narrative projection is unmeasurable** — zero domestic-geofocus
  outlets ingested. We can measure what the region's media says about them, not what they say
  about themselves. *Collection priority #1: ingest RT Arabic/Sputnik Arabic and TRT/Anadolu
  Arabic feeds so the self-report metric works for all four actors.*
- **The corroboration gate binds only on Iran**, so gated cross-actor comparisons carry a
  composition asymmetry (flagged wherever material). Priority #2: curate
  `analytics.source_provenance_map` (~590 outlets) into initiator-aligned / recipient-aligned /
  neutral classes to make normalization exact.
- **Hard power is out of scope by design** and under-captured: Iran proxy logistics, Russian
  basing, Turkish drone diplomacy appear only as soft-power-adjacent shadows.
- **Monetary figures are announced, not verified** (24.8% populated, free-text); no in-window
  AidData overlap. Treat every dollar figure as a claim with an outlet count.
- **Pipeline gaps found during the run** (fix-worthy): `event_summaries.canonical_event_id` is
  100% NULL and `entities_mentioned` is empty — event→entity linkage had to be rebuilt in
  `analytics.event_entities`; `daily_event_mentions` is the only live event→doc bridge.
  Subcategory labels leak prompt enumeration prefixes (fixed via `analytics.subcat_clean`).
  UAE/Palestine name variants split aggregations (fixed via `analytics.recipient_alias`).
- **Absence of reporting ≠ absence of activity**, especially for closed actors and
  low-coverage recipients (Yemen, Libya, Cyprus).

**Watch questions for collectors:** Does Hejaz Railway progress past MOU? Does China's Basra
pipeline resume? Does Iran's GCC détente survive its first crisis test? Does Russia convert El
Dabaa milestones into any second Egyptian lane? Who staffs the US–Iran channel — Muscat, Ankara,
or Beijing?

---

## 9. Method & Verification Appendix

- **Data:** `analytics` schema rebuilt 2026-07 on the refreshed corpus (765K docs), window
  clamped to full months (2024-08-01 ≤ date < 2026-07-01). Derived objects and migration-ready
  DDL: [`../_derived/manifest.md`](../_derived/manifest.md); builders
  `build_analytics.py`, `build_theater.py`; charts `analyze_theater.py` (deterministic, seeded).
- **Process:** five parallel investigation threads (signature, competition, network, tempo,
  ledger) with raw SQL/embedding/graph access → every finding adversarially verified by two
  independent lenses (data-integrity re-query; bias-artifact attack) → completeness pass →
  synthesis. 57 findings survived: **0 refuted, 14 revised** (corrections applied in text —
  notably the Russia-concentration contamination, the doc-vs-initiative diplomacy artifact, the
  wide-reach entity correction, and the Iran "materiality inversion" reframed at initiative
  grain). 38 findings verified in-workflow; 19 (tempo/ledger) re-verified by direct re-query,
  every core number reproducing exactly.
- **Charts:** all magnitudes third-party-corroborated or gate-filtered; actor palette fixed
  (China `#C8102E`, Iran `#1B7A3D`, Russia `#1F4E9C`, Turkey `#E08A1E`); each figure's data in a
  sibling CSV for audit.
- **Related products:** per-initiator deep dives ([China](../china/report.md),
  [Iran](../iran/report.md), [Russia](../russia/report.md), [Turkey](../turkey/report.md),
  [U.S. relational](../united_states/report.md)), cross-actor
  [Economic](../by_category/economic/report.md) / [Military](../by_category/military/report.md) /
  [Social](../by_category/social/report.md) reports, and 17
  [by-recipient](../by_recipient/README.md) cards.
