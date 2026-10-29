# Kiwi.com Scraper API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="REPLACE_WITH_SCREENSHOT_URL" alt="kiwi.com-scraper-api" />
  </a>
</p>

[![checks](https://github.com/ScrapingBee/kiwi.com-scraper-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/kiwi.com-scraper-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/kiwi.com-scraper-api.svg)](LICENSE)

Kiwi.com search pages do not contain flights. They contain five grey placeholder cards, and the itineraries arrive a few seconds later as GraphQL responses from `api.skypicker.com`. This [Kiwi.com scraper API](https://www.scrapingbee.com/scrapers/kiwi.com-scraper-api/) client skips the card markup entirely and reads those responses through [ScrapingBee](https://www.scrapingbee.com/), for 5 credits a search.

The repo is written as the list of problems we hit while building it, in the order we hit them, with the fix for each. Every output below is from runs on 2026-10-29 against Barcelona to Lisbon, 10 December 2026.

## Problem 1: the scrape "succeeds" and returns no flights

**Symptom.** You fetch `https://www.kiwi.com/en/search/results/barcelona-spain/lisbon-portugal/2026-12-10/no-return/` and get HTTP 200, the page title for Barcelona to Lisbon trips, and zero prices.

**Cause.** The HTML ships with `data-test="ResultCardPlaceholder"` skeletons. Prices are filled in by JavaScript after the GraphQL calls return.

**Watch out for Auto-Mode here.** With `mode=auto` ScrapingBee settled on the cheapest tier, 1 credit, because the page answered 200. A 200 with skeletons counts as success, so Auto-Mode never escalated to the JavaScript tier that would have produced data. Set the tier yourself on this site:

```python
params = {"url": url, "render_js": "true", "wait": "8000", "json_response": "true"}
```

`render_js=true` on the classic proxy pool costs 5 credits, and that was enough. No premium or stealth proxy was needed for any request in this repo.

## Problem 2: the cards render but their markup is a mess

**Symptom.** With rendering on, `ResultCardWrapper`, `ResultCardPrice` and `ResultCardStopPlace` show up as `data-test` hooks, but carriers are logos, times are split across nested spans, and baggage is a tooltip.

**Fix.** Ignore the DOM. `json_response=true` wraps the response in JSON and includes an `xhr` array: every request the browser made, with its URL, `post_data` and response `body`. The search results are the calls whose URL contains `featureName=SearchOneWayItinerariesQuery` (or `SearchReturnItinerariesQuery` for a return trip).

```python
calls = [x for x in payload["xhr"] if "featureName=SearchOneWayItinerariesQuery" in x["url"]]
data = json.loads(calls[-1]["body"])["data"]["onewayItineraries"]
```

One itinerary from that body, trimmed:

```json
{
  "price": {"roundedFormattedValue": "150 zł", "amount": "150"},
  "priceEur": {"amount": "34.076256"},
  "duration": 7500,
  "pnrCount": 1,
  "lastAvailable": {"seatsLeft": 3},
  "bagsInfo": {"includedCheckedBags": 0, "includedHandBags": 0, "includedPersonalItem": 1},
  "travelHack": {"isTrueHiddenCity": false, "isVirtualInterlining": false, "isThrowawayTicket": false},
  "sector": {"sectorSegments": [{"segment": {
    "source": {"station": {"code": "BCN", "name": "Barcelona El Prat"}, "localTime": "2026-12-10T18:00:00"},
    "destination": {"station": {"code": "LIS", "name": "Lisbon Portela"}},
    "carrier": {"name": "Ryanair", "code": "FR"},
    "code": "3078",
    "cabinClass": "ECONOMY"
  }}]}
}
```

That is more than the cards show: seats left at this fare, included bags by type, whether the trip is a self transfer (`pnrCount` above 1), and Kiwi's own flags for hidden city and throwaway ticketing.

## Problem 3: the same search returns different itineraries

**Symptom.** Four `SearchOneWayItinerariesQuery` responses in one capture, each with 10 itineraries, and they do not agree. Comparing their ids against the first response: 8, 8, 5 and 5 in common.

**Cause.** Kiwi re-sends the query while carriers are still answering and re-ranks each time.

**Fix.** Take the last response. That is the ranking the page settled on.

## Problem 4: prices come back in zloty, then in dollars

**Symptom.** The one way search returned `150 zł`. The return search a minute later returned `$63`.

**Cause.** `price` follows the market Kiwi assigns to the visitor's IP, and the classic pool exits from different countries. The request variables of the first run read `"currency": "pln", "market": "pl"`.

**Fix.** Compare on `priceEur`, which every itinerary carries regardless of market. Keep `price.roundedFormattedValue` only as a display string.

## Problem 5: only 10 results out of 115

**Symptom.** `metadata.itinerariesCount` says 115, the list has 10.

**Cause.** The query variables include `"limit": 10`. The page's "Load more" button re-sends the query with 20, then 30.

**Fix.** Click it inside the same render with a JavaScript scenario. It has no stable attribute, so find it by text:

```python
LOAD_MORE = "[...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Load more')?.click()"
steps = [{"wait": 7000}, {"evaluate": LOAD_MORE}, {"wait": 4000}, {"evaluate": LOAD_MORE}, {"wait": 4000}]
```

Measured: the captured queries went `10, 10, 10, 20, 30`, the last response held 30 itineraries, and the call still cost **5 credits**, because the clicks happen inside one rendered request. Add `?sortBy=price` to the URL and the first 30 are the 30 cheapest; `duration` and `quality` are the other sort values the page uses.

## The two scripts

[`examples/kiwi_flights.py`](examples/kiwi_flights.py) runs a one way search with two "Load more" clicks, then a return search, and flattens each itinerary into a row:

```
one way: 30 of 115 itineraries, 6 GraphQL rounds, 5 credits
  EUR    31.0  FR3078  18:00  125 min  stops 0  seats left 3
  EUR    42.0  U27682  10:00  130 min  stops 0  seats left None
  EUR    46.0  TP1033  12:35  120 min  stops 0  seats left None

return: 10 itineraries, cheapest EUR 54.0
  out: BCN-LIS Ryanair
  back: LIS-BCN Ryanair
```

[`examples/route_matrix.js`](examples/route_matrix.js) takes one origin and several destinations, and prints the cheapest itinerary and the cheapest direct flight for each:

```
lisbon-portugal       117 found  cheapest EUR   34 BCN>LIS Ryanair  direct EUR 34 Ryanair  [5 credits]
porto-portugal        115 found  cheapest EUR   50 BCN>OVD>OPO Vueling+Volotea (self transfer)  direct EUR 51 Vueling  [5 credits]
vilnius-lithuania     129 found  cheapest EUR   50 BCN>VNO Wizz Air  direct EUR 50 Wizz Air  [5 credits]
```

The Porto row is the kind of result Kiwi is known for: a self transfer through Oviedo on two airlines, one euro under the direct Vueling fare. `pnrCount` is what tells you that the two flights are separate bookings.

Kiwi identifies places by slug, not by IATA code: `barcelona-spain`, `lisbon-portugal`, `vilnius-lithuania`. The GraphQL variables show the internal ids (`City:barcelona_es`), but the URL wants the slug.

## Kiwi Tequila API, the Kiwi API, and this

The Kiwi.com API that developers usually mean is Tequila, Kiwi's partner platform for companies building booking products on its inventory. Access, terms and rate limits there are set by Kiwi.com. This repo does something narrower: it reads the public search page a traveller sees, which is the right source when the question is "what does Kiwi show for this route today" rather than "how do I sell Kiwi itineraries".

Neighbouring ScrapingBee endpoints: [flight scraper API](https://www.scrapingbee.com/scrapers/flight-api/), [fare scraper API](https://www.scrapingbee.com/scrapers/fare-api/), [Google Flights scraper](https://www.scrapingbee.com/scrapers/google-flights-scraper/), [Skyscanner scraper](https://www.scrapingbee.com/scrapers/skyscanner-api/), [Kayak scraper](https://www.scrapingbee.com/scrapers/kayak-api/), [MakeMyTrip scraper](https://www.scrapingbee.com/scrapers/makemytrip-api/).

Parameters used here are documented in the [HTML API reference](https://www.scrapingbee.com/documentation/) (`json_response`, `render_js`, `wait`, and the credit cost table) and the [JavaScript scenario](https://www.scrapingbee.com/documentation/js-scenario/) page. Plans and monthly credit volumes are on [ScrapingBee pricing](https://www.scrapingbee.com/pricing/); 1,000 free credits come with a new account.

## Budget

| Job | Requests | Credits |
|---|---|---|
| One route, one date, up to 30 itineraries | 1 | 5 |
| One route, every day of a 30 day window | 30 | 150 |
| 20 destinations from one origin, one date | 20 | 100 |

## Scope

Public search results only. Bookings, Kiwi.com Guarantee claims, saved searches, price alerts and anything else tied to an account sit behind a sign in, which is out of scope, and scraping under login credentials is prohibited by ScrapingBee's terms of service. The GraphQL responses are read as the page receives them; this repo does not call `api.skypicker.com` directly. Fares and seat counts move constantly, so store the fetch time with every row.

## FAQ

**Is there a Kiwi.com API?**
Kiwi.com runs Tequila for booking partners. For reading public search results, this repo captures the page's own GraphQL responses through ScrapingBee.

**Why does my Kiwi scraper return empty cards?**
The HTML holds placeholders until JavaScript loads the results. Render with `render_js=true` and wait, and do not rely on Auto-Mode, which accepted the 1 credit placeholder page as a success.

**How many credits does a Kiwi search cost?**
5 on the classic pool with JavaScript rendering, including up to two "Load more" clicks.

**Which currency are the prices in?**
`price` varies with the exit IP's market. `priceEur` is always euros.

**Does it handle return trips?**
Yes. Put the return date in place of `no-return` and read `SearchReturnItinerariesQuery`, whose items have `outbound` and `inbound` instead of `sector`.

## License

MIT. See [LICENSE](LICENSE).
