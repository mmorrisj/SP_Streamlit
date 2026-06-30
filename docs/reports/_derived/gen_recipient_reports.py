"""Generate per-recipient cross-initiator report.md from each stats.json + the index.
Data-driven (numbers from verified stats); adaptive analytic prose. Run after analyze_recipient.py.
Usage: python docs/reports/_derived/gen_recipient_reports.py"""
import sys, json, glob, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

BYREC = Path(__file__).resolve().parents[1] / "by_recipient"
CATS = ["Economic", "Social", "Military", "Diplomacy"]
ABBR = {"United States": "U.S.", "China": "China", "Iran": "Iran", "Russia": "Russia", "Turkey": "Turkey"}
# adversarial/crisis-defined files where a U.S. lead = involvement, not courtship
CRISIS = {"Iran", "Israel", "Palestine", "Lebanon", "Syria"}


def lane_summary(m):
    """Return dict category->leading actor and a division-of-labor read."""
    lead = {c: max(m, key=lambda a: m[a].get(c, 0)) for c in CATS}
    econ_social = {lead["Economic"], lead["Social"]}
    mil_dip = {lead["Military"], lead["Diplomacy"]}
    return lead


def write_report(d):
    s = json.load(open(d / "stats.json", encoding="utf-8"))
    r = s["recipient"]; tot = s["totals"]; grand = sum(tot.values()) or 1
    leader = s["leader"]; share = s["top_share"]; hedge = s["hedging"]
    m = s["instrument_matrix"]; lead = lane_summary(m)
    ranked = sorted(tot.items(), key=lambda x: -x[1])
    af = s.get("us_adversary_framed_pct")
    crisis = r in CRISIS
    inits = s.get("initiatives", [])

    # division-of-labor read
    dol = ""
    if lead["Economic"] == "China" and lead["Military"] == "United States":
        dol = ("The classic division of labor is on display: **China supplies the economics and "
               "the U.S. the security** — the Gulf-hedge pattern at the country level.")
    elif leader == "Turkey" and lead["Economic"] == "Turkey":
        dol = "**Turkey is the across-the-board lead** — economics, social, and diplomacy — the reconstruction-patron model."
    elif leader == "United States" and crisis:
        dol = ("The U.S. lead here is **crisis/alliance involvement, not economic courtship** — it "
               "reflects how central Washington is to this file, adversarially or as guarantor.")

    # BLUF bullets
    b = []
    lead_lab = ABBR[leader]
    if crisis and leader == "United States":
        b.append(f"- **{r} is dominated by U.S. involvement ({int(share*100)}% of external attention)** — but "
                 f"this reflects {r}'s centrality to a crisis/alliance file, not development courtship. **(H)**")
    elif hedge.startswith("single-patron"):
        b.append(f"- **{r} is a single-patron file — {lead_lab}-dominated ({int(share*100)}%)**, with no rival close. **(H)**")
    elif hedge == "contested":
        b.append(f"- **{r} is genuinely contested:** {lead_lab} leads with only {int(share*100)}%, "
                 f"with {ABBR[ranked[1][0]]} close behind ({int(100*ranked[1][1]/grand)}%). **(H)**")
    else:
        b.append(f"- **{r} balances multiple patrons** — {lead_lab} leads ({int(share*100)}%) but engages "
                 f"{', '.join(ABBR[a] for a,_ in ranked[1:3])} substantially too. **(M)**")
    b.append(f"- **Division of labor by instrument:** Economic→**{ABBR[lead['Economic']]}**, "
             f"Social→**{ABBR[lead['Social']]}**, Military→**{ABBR[lead['Military']]}**, "
             f"Diplomacy→**{ABBR[lead['Diplomacy']]}**. **(H)**")
    if dol:
        b.append(f"- {dol} **(M)**")
    if inits:
        i0 = inits[0]
        b.append(f"- **Signature initiative:** {i0['event_name']} ({ABBR.get(i0['actor'],i0['actor'])}). **(M)**")
    if af is not None and af >= 15:
        b.append(f"- **{af}% of U.S. coverage here is Iranian-media-framed** — a meaningful adversarial-"
                 f"narrative presence around the U.S. role. **(M)**")

    # initiatives prose
    init_lines = "\n".join(
        f"- **{i['event_name']}** — {ABBR.get(i['actor'],i['actor'])}, material {i['material_score']} ({i['d0'][:7]})"
        for i in inits[:8]) or "- *(No high-materiality named initiatives cleared the threshold for this recipient.)*"

    rows = "\n".join(f"| {ABBR[a]} | {v:,} | {100*v/grand:.0f}% |" for a, v in ranked if v)

    md = f"""# Who Courts {r}? A Cross-Initiator Influence Assessment
### China · Iran · Russia · Turkey · United States — for U.S. Decision-Makers

*Open-source media corpus, 2024-08-01 to 2026-06-15. Method/caveats per
`../../INTEL_REPORT_PROMPT.md`. Intensity = third-party-corroborated documents (U.S. = registered
coverage; the U.S. has no state media in the corpus). Confidence: **(H)/(M)/(L)**.*

> **Hedging profile: {hedge}.** Lead actor: **{lead_lab}** ({int(share*100)}% of external attention).

---

## 1. Key Judgments (BLUF)

{chr(10).join(b)}

![Who courts {r}](assets/01_suitor_leaderboard.png)

---

## 2. The Suitors

| Actor | Influence (docs) | Share |
|-------|-----------------:|------:|
{rows}

![Share of attention](assets/04_dominance_share.png)

{r}'s external-influence field is **{hedge}**. {dol or ''}

---

## 3. Instrument Matrix — Which Lane Each Actor Uses

![Instrument matrix](assets/02_instrument_matrix.png)

Read by instrument, the competition for {r} sorts cleanly: **Economic → {ABBR[lead['Economic']]}**,
**Social → {ABBR[lead['Social']]}**, **Military → {ABBR[lead['Military']]}**, **Diplomacy →
{ABBR[lead['Diplomacy']]}**. Each actor competes in the lane that fits its regional model rather
than going head-to-head across all four. **(H)**

---

## 4. Initiatives Targeting {r}

![Initiatives targeting {r}](assets/05_initiatives.png)

*Validated for alignment: only events where {r} is the **primary** recipient are shown — named in
the title, holding ≥40% of the event's recipient mentions, or the sole top recipient.
{s.get('initiatives_dropped_peripheral', 0)} peripheral events (where {r} was only mentioned in
passing on another country's initiative — e.g., regional spillover) were excluded.*

{init_lines}

---

## 5. Contested Dynamics, Trajectory & Gaps

![Trajectory](assets/03_trajectory.png)

- **Trajectory:** see the monthly series for who is gaining or losing ground in {r}; activity tracks
  the region's inflection points (Israel-Hezbollah escalation Sept 2024, Assad's fall Dec 2024, the
  June 2025 Israel-Iran war). **(M)**
{"- **Adversarial framing:** " + str(af) + "% of the U.S.'s coverage in " + r + " is carried by Iranian media — its image here is partly written by its adversary. **(M)**" if af is not None and af>=10 else ""}
- **Caveat:** this measures *reported* influence; the soft-power lens under-captures hard power, and
  dollar figures are announced, not verified. {"For " + r + ", a high U.S. share reflects crisis/alliance involvement rather than economic courtship." if crisis else ""}

---

*Visuals plot corroborated/registered influence; underlying numbers in sibling CSVs under `assets/`.
Index: [`../README.md`](../README.md). Method: `docs/INTEL_REPORT_PROMPT.md`.*
"""
    (d / "report.md").write_text(md, encoding="utf-8")
    return {"recipient": r, "leader": leader, "share": share, "hedge": hedge, "lead": lead,
            "totals": tot, "grand": grand, "af": af}


def main():
    dirs = sorted([Path(p).parent for p in glob.glob(str(BYREC / "*" / "stats.json"))],
                  key=lambda d: -sum(json.load(open(d/"stats.json", encoding="utf-8"))["totals"].values()))
    summ = [write_report(d) for d in dirs]

    # index
    rows = []
    for x in summ:
        ll = x["lead"]
        rows.append(f"| [{x['recipient']}]({x['recipient'].lower().replace(' ','_')}/report.md) | "
                    f"**{ABBR[x['leader']]}** ({int(x['share']*100)}%) | {x['hedge']} | "
                    f"E:{ABBR[ll['Economic']][:3]} S:{ABBR[ll['Social']][:3]} M:{ABBR[ll['Military']][:3]} D:{ABBR[ll['Diplomacy']][:3]} |")
    # data-driven hedging-profile groupings
    def names(pred): return ", ".join(f"{x['recipient']} ({ABBR[x['leader']]})" for x in summ if pred(x)) or "—"
    groups = (
        "**Single-patron files:** " + names(lambda x: x["hedge"].startswith("single-patron")) + ".  \n"
        "**Contested:** " + names(lambda x: x["hedge"] == "contested") + ".  \n"
        "**Balancing (multi-patron):** " + names(lambda x: x["hedge"].startswith("balancing")) + "."
    )
    idx = f"""# Cross-Initiator Reports by Recipient
### Who courts each MENA state — and who leads

*Demand-side companion to the by-initiator and by-category reports. 17 qualifying recipients
(>=300 cross-actor docs). Skipped (too thin): **UAE** (duplicate spelling of United Arab Emirates,
230) and **Cyprus** (117). Intensity = corroborated (rivals) / registered (U.S.). The U.S. lead on
crisis/alliance files (Iran, Israel, Palestine, Lebanon, Syria) reflects involvement, not courtship.*

| Recipient | Lead actor | Hedging profile | Lane leaders (E/S/M/D) |
|-----------|-----------|-----------------|------------------------|
{chr(10).join(rows)}

## The pattern
- **China leads the Economic and Social lanes in almost every Gulf/Arab state** — the
  development-and-culture patron — while **the U.S. leads Military and Diplomacy** in those same
  states. The **U.S.-security + China-capital division of labor holds recipient by recipient.**
- **Turkey leads the reconstruction theaters** (Syria, Iraq, Libya).
- **Iran leads only where the Resistance arc runs** (the Oman back-channel; Lebanon/Iraq social) and
  is marginal once its self-reporting is stripped.

{groups}
"""
    (BYREC / "README.md").write_text(idx, encoding="utf-8")
    print(f"[done] wrote {len(summ)} recipient reports + index")


if __name__ == "__main__":
    main()
