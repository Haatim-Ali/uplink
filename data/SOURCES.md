# Where the demo's places and menus come from

The businesses, shelters and food programs are real places in Santa Cruz, CA, at their real addresses
(coordinates from OpenStreetMap). Menu items come from each business's own menu, checked October 2026.

**Simulated, not real:** each shelter's capacity, closing time, fridge, allergen rules, "last got food"
days and replies; the servings, weight and allergens per menu item (estimated); the drivers (fictional
people); travel times (straight-line). Nothing here describes how these organizations actually operate.

## Food businesses (`businesses.json`, `menus.json`)

| ID | Place | Address | Menu source |
| --- | --- | --- | --- |
| campus-cafe | Pizza My Heart | 1116 Pacific Ave | pizzamyheart.com/menu |
| tech-cafeteria | Zoccoli's Deli | 1534 Pacific Ave | zoccolis.com (menu page) |
| corner-bakery | Kelly's French Bakery | 402 Ingalls St | kellysfrenchbakery.com (items shown on the site) |
| lakeside-hotel | Jack O'Neill Restaurant, Dream Inn | 175 West Cliff Dr | jackoneillrestaurant.com/menus |
| north-market | Downtown Santa Cruz Farmers' Market | Cedar St & Church St (Wednesdays) | October produce; city of Santa Cruz market page |
| food-hall | Abbott Square Market | 725 Front St | Vendors' items as reported by Good Times and Lookout (India Gourmet, Pizzeria la Bufala, Luna's Borikén Bites, Daisuki) |
| campus-dining | UCSC John R. Lewis & College Nine Dining Hall | UC Santa Cruz | nutrition.sa.ucsc.edu, menu for Sunday, October 11, 2026 |
| grocer | New Leaf Community Market (Westside) | 1101 Fair Ave | Typical grocery and deli items (no published menu) |
| caterer | The Bagelry (Seabright) | 1636 Seabright Ave | bagelrysantacruz.com (dining and catering menus) |

## Shelters and food programs (`nonprofits.json`, `new_pantry.json`)

| ID | Place | Address |
| --- | --- | --- |
| harbor-house | Housing Matters | 115 Coral St |
| eastside-pantry | Salvation Army Santa Cruz Corps | 721 Laurel St |
| grace-kitchen | St. Francis Catholic Kitchen | 205 Mora St |
| riverside-family | Beach Flats Community Center | 133 Leibrandt Ave |
| northside-youth | Walnut Avenue Family & Women's Center | 303 Walnut Ave |
| valley-food-bank | Grey Bears | 2710 Chanticleer Ave |
| hope-pantry | UCSC SUA Food Pantry | East Field House, UC Santa Cruz |
| maple-pantry | Elm Street Mission (joins mid-run) | 117 Elm St |

The IDs are the original internal keys, kept so scenarios, tests and URLs don't change.
