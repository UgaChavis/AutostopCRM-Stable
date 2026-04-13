# AutoStop CRM Agent Autofill Orchestration

Current card autofill is not a free-form browser agent. It is a small deterministic orchestration pipeline.

## Pipeline
1. `context builder`
   Reads `get_card_context(card_id)`.
   Collects:
   - card fields
   - description
   - vehicle
   - vehicle_profile
   - recent events
   - previous AI notes
   - AI log tail
   - a short related-card slice from `search_cards()` when VIN or stable vehicle context justifies it
2. `card analyzer`
   Extracts:
   - VIN
   - complaint
   - mileage
   - DTC
   - likely parts
   - waiting state
   - known vehicle facts
   - missing vehicle fields
   - likely maintenance cues
3. `scenario selector`
   Chooses one or more scenarios:
   - VIN enrichment
   - part lookup
   - maintenance lookup
   - DTC decode
   - fault research
   - normalization
4. `tool router`
   Calls only the bounded external tools needed for the selected scenarios, under a small per-run budget.
5. `result normalizer`
   Converts raw external results into short Russian operational notes and compact vehicle-profile patches.
6. `card writer`
   Applies safe `update_card()` changes:
   - keeps original text
   - appends only net-new `ИИ:` notes
   - patches `vehicle_profile` only where fields are missing
   - may improve top-level `vehicle` label when new facts are strong enough
7. `follow-up controller`
   Schedules the next check, skips unchanged cards, blocks duplicate active runs, and stops after the 4-hour window or the run limit.

## External Tools
- `decode_vin(vin)`
- `find_part_numbers(query, vehicle)`
- `estimate_price_ru(part_number, vehicle)`
- `decode_dtc(code, vehicle_context)`
- `search_fault_info(query, vehicle_context)`

## Tool Limits
- External request budget is reset per task.
- Budget is capped to a small number of calls per run.
- Only whitelisted domains and trusted sources are used.
- Results are normalized to compact structured payloads before card updates.

## Writer Rules
- Never delete manual prices, article numbers, phone numbers, VIN, or operator notes.
- Do not duplicate existing card text.
- Add only net-new short lines.
- Prefix AI additions with `ИИ:`.
- If certainty is low, write a short follow-up note for the next executor instead of fabricating facts.
- Reuse already confirmed `vehicle_profile` facts when building later searches.
- If a concrete part is found, prefer one compact line with OEM, analogs, and price orientation instead of a long paragraph.

## Scenario Rules

### VIN
- Trigger whenever VIN exists.
- Run before other external scenarios.
- Fill only missing `vehicle_profile` fields, but reuse VIN facts to improve part, maintenance, and fault lookups.

### Parts
- Trigger when the description implies a concrete part such as radiator, control arm, strut, bearing, pads, thermostat, pump, belt, chain, filters, plugs, battery.
- Expand common Russian part names into better search variants before external lookup.
- Add OEM or catalog numbers if found.
- Add Russian price orientation only if a good part number was found.

### Maintenance
- Trigger only on real maintenance cues, not on accidental substrings.
- Build a compact preliminary list of works and consumables.
- Include mileage-sensitive notes and known fluid capacities when present.

### DTC
- Decode the first detected DTC first.
- Add short meaning and first-check hints.

### Symptoms
- Use only when the card is not obviously in a waiting state.
- Add short diagnostic context, not a wall of text.

## Follow-Up Rules
- First pass runs immediately after enabling autofill.
- Later checks depend on change detection:
  - changed card -> faster revisit
  - unchanged card -> slower revisit
  - waiting state -> slower revisit
- Duplicate active processing for the same card is blocked.
- Old AI runs do not endlessly retrigger themselves.
- A board-context slice may be loaded again only when the card changed meaningfully.

## Operator Prompt Rules
- Mini-prompt influences scenario selection.
- It should be short and operational:
  - `Расшифруй VIN`
  - `Помоги с подбором радиатора`
  - `Собери ТО по пробегу`
- Prompt is guidance, not permission to overwrite manual facts.
