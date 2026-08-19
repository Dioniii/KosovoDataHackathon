# Pitch — Kosovo Property & Investment Screener

90-second spoken script, word for word. Numbers below are pulled directly from
`pipeline/data.json` (real ASKdata + World Bank data) — re-check them against that file
before presenting if the pipeline has been re-run since this was written, since a stale
number in the opening line would undercut the whole pitch.

## The script

> Right now, five of Kosovo's seven statistical regions show *falling* year-over-year
> investment — even though the national economy is growing 3.6% and foreign direct
> investment is running at 10% of GDP. That's not a national story, it's a regional one.
> And the sharpest pullback isn't in some overlooked corner of the country — it's in
> Prishtina. Investment there is down 14.5% year over year, at the exact same time that
> Prishtina has the single highest tourism-demand pressure of any region in Kosovo —
> visitor nights are growing faster than hotel capacity can keep up, more than anywhere
> else in the country. Capital is retreating from the capital, right where demand is
> outrunning supply the fastest.
>
> That's the kind of gap this tool is built to surface. It's for a diaspora Kosovar asking
> one of two questions: where should I look at buying property, or where should I look at
> starting a small business? To be clear up front — this is a screening tool, not financial
> or investment advice. It ranks regions and municipalities using public statistics as a
> starting point for your own research, not a recommendation, and that disclaimer is on
> the page itself, not buried in fine print.
>
> It's built on real, independently collected sources: ASKdata's investment-by-region
> survey, its tourism and hotel-capacity tables, its housing price index, and its business
> registration data — four separate statistical series, each with its own methodology, not
> one spreadsheet sliced four ways — plus World Bank data for national GDP growth and FDI.
>
> If we had more time, two things: AI-generated research briefs for every region and sector
> so each ranking comes with a written explanation, not just a number — that pipeline is
> built, just not filled in yet — and a real multi-year trend line instead of the two-point
> before/after view we're showing today.

## Anticipated judge question

**"How do you know this counts as combining 3+ data sources, and not one table dressed up
differently?"**

Answer: Investment, tourism/hotel capacity, housing prices, and business registrations are
each their own independently collected, independently structured survey inside ASKdata —
different methodologies, different collection cadences, different variable sets — not
filtered views of a single underlying table. On top of that, national GDP growth and FDI
come from an entirely separate source, the World Bank. The regional investment and tourism
numbers are joined together by region name (after resolving spelling mismatches like
"Gjakovë" vs. "Gjakova" across tables), which is what makes the Prishtina finding above
possible in the first place — it only exists because two genuinely separate datasets were
actually combined, not just displayed side by side.
