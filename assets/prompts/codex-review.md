Review the following travel plan artifacts for quality issues.

## Itinerary
$itinerary

## Restaurants
$restaurants

## Hotels
$hotels

## Check for
1. Pace balance: are any days overloaded (>6 POIs) or empty (<2 POIs)?
2. Route efficiency: does the daily ordering minimize backtracking?
3. Duplicate coverage: is any POI scheduled twice?
4. Restaurant relevance: is each restaurant near its day's POI region?
5. Hotel proximity: is each hotel near the evening activity area?
6. Missing coverage: any day without lunch or dinner?

For each issue found, output a JSON object with: ref (item name), verdict (accept/flag/reject), reason, suggestion.
