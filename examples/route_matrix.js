// One origin, several destinations, one date: the cheapest direct and the
// cheapest overall itinerary per route, from Kiwi.com's GraphQL responses.
//
// Verified live on 2026-10-29 from Barcelona on 10 December 2026.
// Node 18+ (global fetch). Set SCRAPINGBEE_API_KEY before running.
// Cost: 5 credits per route (classic proxy, JavaScript rendering).

const API = "https://app.scrapingbee.com/api/v1/";
const FEATURE = "featureName=SearchOneWayItinerariesQuery";

async function cheapest(origin, destination, date) {
  const target =
    `https://www.kiwi.com/en/search/results/${origin}/${destination}/${date}/no-return/` +
    "?sortBy=price";

  const params = new URLSearchParams({
    url: target,
    render_js: "true",
    wait: "8000",
    json_response: "true",
  });

  const res = await fetch(`${API}?${params}`, {
    headers: { Authorization: `Bearer ${process.env.SCRAPINGBEE_API_KEY}` },
  });
  if (!res.ok) throw new Error(`${destination}: ${res.status} ${await res.text()}`);
  const page = await res.json();

  // Several responses per search; the last one is the settled ranking.
  const calls = (page.xhr || []).filter((x) => (x.url || "").includes(FEATURE));
  if (!calls.length) throw new Error(`${destination}: no itinerary response captured`);
  const data = JSON.parse(calls[calls.length - 1].body).data.onewayItineraries;

  const rows = data.itineraries.map((it) => {
    const segs = it.sector.sectorSegments.map((s) => s.segment);
    return {
      eur: Number(it.priceEur.amount),
      direct: segs.length === 1,
      route: segs.map((s) => s.source.station.code).concat(segs.at(-1).destination.station.code).join(">"),
      carriers: [...new Set(segs.map((s) => s.carrier.name))].join("+"),
      selfTransfer: it.pnrCount > 1,
    };
  });

  const byPrice = rows.sort((a, b) => a.eur - b.eur);
  return {
    destination,
    found: data.metadata.itinerariesCount,
    cheapest: byPrice[0],
    cheapestDirect: byPrice.find((r) => r.direct) || null,
    credits: page.cost,
  };
}

async function main() {
  const origin = process.argv[2] || "barcelona-spain";
  const date = process.argv[3] || "2026-12-10";
  const destinations = process.argv.slice(4).length
    ? process.argv.slice(4)
    : ["lisbon-portugal", "porto-portugal", "vilnius-lithuania"];

  for (const dest of destinations) {
    const r = await cheapest(origin, dest, date);
    const c = r.cheapest;
    const d = r.cheapestDirect;
    console.log(
      `${dest.padEnd(20)} ${String(r.found).padStart(4)} found  ` +
        `cheapest EUR ${c.eur.toFixed(0).padStart(4)} ${c.route} ${c.carriers}` +
        `${c.selfTransfer ? " (self transfer)" : ""}  ` +
        (d ? `direct EUR ${d.eur.toFixed(0)} ${d.carriers}` : "no direct in first 10") +
        `  [${r.credits} credits]`
    );
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
