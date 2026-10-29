"""Kiwi.com flight search results, read from the page's own GraphQL traffic.

Verified live on 2026-10-29: Barcelona to Lisbon, one way on 10 December
2026 and return 10 to 14 December 2026.

The search page renders its result cards from api.skypicker.com/umbrella/v2/
graphql responses. With json_response=true ScrapingBee returns every XHR the
browser made, bodies included, so the itineraries arrive as JSON and no CSS
selector is involved.

Classic proxy with JavaScript rendering, 5 credits per search.
Set SCRAPINGBEE_API_KEY in your environment before running.
"""

import json
import os
import sys

import requests

API = "https://app.scrapingbee.com/api/v1/"
HEADERS = {"Authorization": f"Bearer {os.environ['SCRAPINGBEE_API_KEY']}"}

QUERIES = {
    "oneway": ("SearchOneWayItinerariesQuery", "onewayItineraries"),
    "return": ("SearchReturnItinerariesQuery", "returnItineraries"),
}


# Each GraphQL query asks for 10 itineraries. The "Load more" button re-sends
# it with limit 20, then 30. It has no stable attribute, so it is found by text.
LOAD_MORE = "[...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Load more')?.click()"


def search_url(origin, destination, depart, back=None, sort="price"):
    """Kiwi uses city slugs, not IATA codes: barcelona-spain, lisbon-portugal.

    sort is price, duration or quality (Kiwi's default "best" ranking).
    """
    tail = back or "no-return"
    return f"https://www.kiwi.com/en/search/results/{origin}/{destination}/{depart}/{tail}/?sortBy={sort}"


def fetch(url, pages=1):
    # The first GraphQL answer lands a few seconds after load and is refined
    # as more carriers report, so wait 7 seconds before touching the page.
    steps = [{"wait": 7000}]
    for _ in range(pages - 1):
        steps += [{"evaluate": LOAD_MORE}, {"wait": 4000}]
    params = {
        "url": url,
        "render_js": "true",
        "json_response": "true",
        "js_scenario": json.dumps({"strict": False, "instructions": steps}),
    }
    r = requests.get(API, headers=HEADERS, params=params, timeout=200)
    r.raise_for_status()
    return r.json()


def itineraries(payload, kind):
    """Pick the LAST response for the query.

    Earlier ones are partial rankings sent while carriers were still
    reporting, and after "Load more" the last one is also the longest.
    """
    feature, root = QUERIES[kind]
    calls = [x for x in payload.get("xhr", []) if f"featureName={feature}" in x.get("url", "")]
    if not calls:
        raise RuntimeError("no itinerary XHR captured; the page did not finish loading")
    data = json.loads(calls[-1]["body"])["data"][root]
    return data, len(calls)


def _segments(sector):
    out = []
    for s in sector["sectorSegments"]:
        seg = s["segment"]
        out.append(
            {
                "from": seg["source"]["station"]["code"],
                "to": seg["destination"]["station"]["code"],
                "depart_local": seg["source"]["localTime"],
                "arrive_local": seg["destination"]["localTime"],
                "carrier": seg["carrier"]["name"],
                "flight": f"{seg['carrier']['code']}{seg['code']}",
                "cabin": seg.get("cabinClass"),
            }
        )
    return out


def flatten(item, kind):
    legs = (
        {"out": _segments(item["sector"])}
        if kind == "oneway"
        else {"out": _segments(item["outbound"]), "back": _segments(item["inbound"])}
    )
    bags = item.get("bagsInfo") or {}
    return {
        "id": item["id"],
        # price follows the exit IP's market (PLN on one run, USD on the next).
        # priceEur is always euros, so compare on that.
        "price_eur": round(float(item["priceEur"]["amount"]), 2),
        "price_local": item["price"].get("roundedFormattedValue"),
        "duration_min": item["duration"] // 60,
        "stops": sum(len(l) for l in legs.values()) - len(legs),
        "seats_left": (item.get("lastAvailable") or {}).get("seatsLeft"),
        "checked_bags_included": bags.get("includedCheckedBags"),
        "self_transfer": item.get("pnrCount", 1) > 1,
        "hidden_city": (item.get("travelHack") or {}).get("isTrueHiddenCity"),
        "legs": legs,
    }


def search(origin, destination, depart, back=None, sort="price", pages=1):
    """5 credits whatever the page count: clicks happen inside one render."""
    kind = "return" if back else "oneway"
    payload = fetch(search_url(origin, destination, depart, back, sort), pages)
    data, rounds = itineraries(payload, kind)
    meta = data["metadata"]
    return {
        "credits": payload.get("cost"),
        "graphql_rounds": rounds,
        "total_on_kiwi": meta.get("itinerariesCount"),
        "best": meta["topResults"]["best"]["price"]["amount"],
        "cheapest": meta["topResults"]["cheapest"]["price"]["amount"],
        "fastest": meta["topResults"]["fastest"]["price"]["amount"],
        "results": [flatten(i, kind) for i in data["itineraries"]],
    }


if __name__ == "__main__":
    origin, destination = (sys.argv[1:3] if len(sys.argv) > 2 else ("barcelona-spain", "lisbon-portugal"))

    one = search(origin, destination, "2026-12-10", pages=3)
    print(
        f"one way: {len(one['results'])} of {one['total_on_kiwi']} itineraries, "
        f"{one['graphql_rounds']} GraphQL rounds, {one['credits']} credits"
    )
    for f in sorted(one["results"], key=lambda x: x["price_eur"])[:5]:
        leg = f["legs"]["out"][0]
        print(f"  EUR {f['price_eur']:>7}  {leg['flight']:<7} {leg['depart_local'][11:16]}  "
              f"{f['duration_min']} min  stops {f['stops']}  seats left {f['seats_left']}")

    rt = search(origin, destination, "2026-12-10", "2026-12-14")
    cheap = min(rt["results"], key=lambda x: x["price_eur"])
    print(f"\nreturn: {len(rt['results'])} itineraries, cheapest EUR {cheap['price_eur']}")
    for name, legs in cheap["legs"].items():
        print(f"  {name}: " + " > ".join(f"{s['from']}-{s['to']} {s['carrier']}" for s in legs))
