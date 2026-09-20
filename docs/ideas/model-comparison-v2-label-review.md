# Clarified-policy v2 development-label review

## Scope and result

- This review covers only the 34 `development` cases copied from `model_comparison_first50.yaml`.
- The review used only each preserved article title/summary and the clarified policy. It did not use candidate-model outputs.
- The copy retains `version: 1` for the dataset envelope and adds root `policy_version: 2`.
- Every case remains either `provisional` or `disputed`; none is human-approved or marked `reviewed`.
- There are 7 incident sequences, 16 policy-pending cases, 18 disputed cases in total, and 16 provisional cases.
- Every case now has `expected.facts` with `attack_countries`, `protection`, and `status`, plus short direct-source excerpts in `provenance.evidence`.

`affected_countries` now means monitored countries with an explicitly reported local incident or protective response. It does not mean that those countries were attacked. `facts.attack_countries` separately records the country of an explicit hostile physical impact/incursion, including Ukraine.

## Pending operator choices

The following labels are intentionally not selected:

- `near_border_strike`: `awareness` = 5–6, `log_only` = 1–3, or `critical` = 9–10.
- `neutralised_drone`: `current_danger` = 1–4 or `original_severity` = 7–8.

Each affected case is `disputed`, has `expected.policy_pending: true`, retains its old v1 urgency/notification/critical values only as `placeholder_source: legacy_v1_annotation_not_an_operator_choice`, and stores the actual alternatives under `expected.proposed_labels`. A v2 run must refuse these placeholders until the operator chooses and the cases are relabelled.

Policy-dependent case IDs:

- `mc-border-train-01`
- `mc-border-train-02`
- `mc-border-train-03`
- `mc-border-train-04`
- `mc-rusinowo-01`
- `mc-rusinowo-02`
- `mc-rusinowo-03`
- `mc-rusinowo-04`
- `mc-rusinowo-05`
- `mc-rusinowo-06`
- `mc-rusinowo-07`
- `mc-rusinowo-08`
- `mc-rusinowo-09`
- `mc-rusinowo-10`
- `mc-rusinowo-11`
- `mc-rusinowo-12`

## Exact per-case review

In the “changes” column, fields not named are preserved from v1. The facts and evidence columns are additions in every row.

| Case | Exact changes from v1 | Added facts | Direct source evidence | Rationale |
|---|---|---|---|---|
| `mc-border-train-01` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=unclear | “поблизу польського кордону, влучили у потяг до Варшави” | The source states a Russian drone strike near the Polish border but does not locate the impact on either side; Warsaw is only the train destination, and current danger is not stated. Alert severity remains an operator choice. |
| `mc-border-train-02` | added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=unclear | “Дрони РФ вдарили за кілометр від Польщі” | The strike is one kilometre from Poland, not explicitly on either side, and current danger is not stated. Its identity with the train strike is plausible but not conclusive, and alert severity remains an operator choice. |
| `mc-border-train-03` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=unclear | “Struck 1.2 Miles From NATO's Border” | The Russian-drone strike beside a train is the same physical episode as mc-border-train-01, but the report still places it only by the NATO border and gives no current status. Alert severity remains an operator choice. |
| `mc-border-train-04` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=unclear | “strike a gas station and passenger train near Ukraine’s border with Poland” | This report places the struck train and gas station near Ukraine’s border with Poland, but “near” still does not establish the side of the border or current danger. Alert severity remains an operator choice. |
| `mc-scramble-pl-01` | `urgency_min` `9` → `2`; `urgency_max` `10` → `3`; `notification` `initial` → `silent`; `critical` `true` → `false` | attack=[]; protection=unclear; status=active | “Rosyjskie drony blisko Polski” / “Alert dla dwóch województw!” / “Alert dla dwóch województw!” | “Alert dla dwóch województw” identifies a Polish protective response but does not say that residents were ordered to shelter or evacuate. The warning type is unclear, so this first vague report stays below the notification threshold. |
| `mc-scramble-pl-02` | `notification` `silent` → `initial` | attack=[]; protection=precaution; status=active | “polskie wojsko poderwało lotnictwo. Dwa lotniska wstrzymały pracę” / “Poranny alarm” | The explicit fighter scramble and airport closures are Polish precautions, not evidence of an attack in Poland. This is the first concrete threshold-level report and therefore sends the initial notification. |
| `mc-scramble-pl-03` | `urgency_min` `9` → `5`; `urgency_max` `10` → `6`; `critical` `true` → `false` | attack=[]; protection=precaution; status=active | “Polskie myśliwce pilnie poderwane” / “pilnie poderwane” | Fighter scrambling and airport closures are explicit precautions. “RCB bije na alarm” does not identify a resident order, so the report is not independently critical. |
| `mc-scramble-pl-04` | No v1 alert/identity field changed | attack=[]; protection=precaution; status=resolved | “Wojsko postawione w stan gotowości” / “Zagrożenie trwało godzinę” | The military readiness is a Polish precaution and “zagrożenie trwało godzinę” says it ended. It is same-episode coverage after the initial notification. |
| `mc-scramble-pl-05` | No v1 alert/identity field changed | attack=[UA]; protection=precaution; status=resolved | “російські дрони на заході України” / “У Польщі зранку закривали аеропорти Жешува й Любліна” / “зранку закривали аеропорти” | The physical attack is explicitly in western Ukraine, while Poland only closed two airports. That makes UA the attack country and PL the country taking a precaution. |
| `mc-scramble-pl-06` | `notification` `silent` → `update` | attack=[UA]; protection=official_warning; status=active | “Russian drones attack Ukraine” / “Air raid alerts were issued for residents of the Lublin and Podkarpackie regions” / “Air raid alerts were issued” | The summary explicitly says air-raid alerts were issued to residents in two Polish regions. This is the first unambiguous official resident warning and escalates the already-notified episode. |
| `mc-scramble-pl-07` | No v1 alert/identity field changed | attack=[UA]; protection=precaution; status=active | “Russian drones attack Ukraine” / “Poland scrambles fighter jets, temporarily closes airports” / “Poland scrambles fighter jets” | The syndicated title states a Polish scramble and airport closures during an attack in Ukraine, but no resident order or Polish incursion. It is a silent precautionary update. |
| `mc-rusinowo-01` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “elementy rosyjskiego drona” / “Zdetonowano elementy rosyjskiego drona” | The current text reports Russian-drone components on a Polish beach and their detonation, but not the route or a hostile Polish impact. Current-danger versus original-severity scoring remains an operator choice. |
| `mc-rusinowo-02` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “Rosyjski dron w Bałtyku” / “zostały wydobyte i zdetonowane przez wojsko” | The Rusinowo object and hazardous parts were secured and detonated, so the local Polish incident is resolved. The source does not itself establish a hostile impact or incursion route. |
| `mc-rusinowo-03` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “drona znalezionego na plaży w Rusinowie” / “wydobyło, zbadało i zneutralizowało” | The military says the Rusinowo drone elements were recovered and neutralised. This is the same resolved local incident; its alert band remains policy-dependent. |
| `mc-rusinowo-04` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “Dron znaleziony na plaży w Rusinowie” / “Dron znaleziony na plaży w Rusinowie” | The title is a retrospective prosecutor update about the drone found at Rusinowo and supplies no current danger. The same incident is clear, but its alert band remains policy-dependent. |
| `mc-rusinowo-05` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “rosyjski dron Gerbera 2” / “głowicę bojową, która została zneutralizowana” | The same recovered object is identified as a Russian Gerbera-2 whose warhead was neutralised. That supports resolved status without proving the route or hostile impact from this article. |
| `mc-rusinowo-06` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “Dron znaleziony w Rusinowie” / “miał głowicę bojową” | The title reports an investigative finding about the already-found Rusinowo drone and warhead, with no current danger stated. Alert severity remains policy-dependent. |
| `mc-rusinowo-07` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “rosyjski dron Gerbera 2” / “głowicę bojową, która została zneutralizowana” | The report repeats the Gerbera-2 identification and explicitly says the warhead was neutralised. It is a resolved same-incident report with a pending alert band. |
| `mc-rusinowo-08` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “dronie z Rusinowa” / “Nowe ustalenia śledczych” | The investigators’ later findings concern the same found Rusinowo object and report no current danger. Alert severity remains policy-dependent. |
| `mc-rusinowo-09` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “‘Russian drone’ found off Poland’s Baltic Sea” / “was carrying warhead” | This is English coverage of the same Russian drone found off Poland’s Baltic coast, described in the past tense. It gives no current danger or explicit hostile route. |
| `mc-rusinowo-10` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “Dron Gerbera 2 z głowicą bojową znaleziony w Rusinowie” / “znaleziony w Rusinowie” | Gerbera-2, a warhead, and Rusinowo identify the same recovered object. The report is retrospective, while alert severity remains an operator choice. |
| `mc-rusinowo-11` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=resolved | “a Russian Gerbera-2 drone found on a beach” / “was safely neutralised” | The prosecutors’ report ties the Russian Gerbera-2 and warhead to the same beach recovery and expressly says it was safely neutralised. |
| `mc-rusinowo-12` | label_status `provisional` → `disputed`; added `policy_pending: true`; operative values are legacy-v1 placeholders | attack=[]; protection=none; status=historical | “A drone found in Poland turned out to be a Russian Gerbera 2” / “turned out to be” | The title retrospectively identifies the drone found in Poland as a Russian Gerbera-2 with a warhead. It states neither a current danger nor the object’s route. |
| `mc-tryncza-01` | `urgency_max` `3` → `4` | attack=[]; protection=none; status=resolved | “Dron na dożynkach” / “Zatrzymano mężczyznę” | A drone at a Polish harvest festival and a detention are a concrete local incident, but no military origin or hostile physical attack is stated. The civilian/unknown-ground-drone band is 1–4. |
| `mc-tryncza-02` | `urgency_max` `3` → `4` | attack=[]; protection=none; status=historical | “Incydent z dronem na Dożynkach Prezydenckich w Tryńczy” / “Prokuratura wszczęła postępowanie” | The prosecutor investigation concerns the same Tryńcza festival drone. It is a retrospective local Polish incident with no military attack or protective order. |
| `mc-tryncza-03` | `urgency_max` `3` → `4` | attack=[]; protection=none; status=resolved | “Bezzałogowy statek powietrzny wleciał w zamkniętą strefę” / “policja zatrzymała mężczyznę” | The fuller report confirms the same drone entered a closed zone and that police detained a man. The local incident is resolved and remains in the 1–4 civilian/unknown band. |
| `mc-geran-analysis-01` | No v1 alert/identity field changed | attack=[]; protection=none; status=unclear | “rozwój turboodrzutowych wariantów rodziny Geran” | This is a technical analysis of existing Russian drone and Ukrainian interceptor capabilities, not a current incident. It has no monitored-country effect and remains routine. |
| `mc-geran-analysis-02` | No v1 alert/identity field changed | attack=[]; protection=none; status=unclear | “Gierań-5 wymusza nową generację interceptorów” | This is syndicated coverage of the same Defence24 technical analysis at the same publication time. It remains routine and silent. |
| `mc-assassination-01` | No v1 alert/identity field changed | attack=[]; protection=none; status=unclear | “искали исполнителей для слежки, убийств и диверсий в США и Европе” | The report alleges Russian intelligence recruitment for murders and sabotage, chiefly describing a US episode. It does not report a military physical incident or protective response in a monitored country. |
| `mc-assassination-02` | No v1 alert/identity field changed | attack=[]; protection=none; status=resolved | “FBI udaremniło zamach na życie prominentnego dysydenta” / “FBI udaremniło zamach” | The thwarted US dissident plot is resolved and has no concrete local incident in a monitored country. Its identity with mc-assassination-01 remains uncertain, so the label stays disputed. |
| `mc-assassination-03` | No v1 alert/identity field changed | attack=[]; protection=none; status=unclear | “network for assassinations and sabotage in the US and Europe” | The broad Bloomberg network headline reports no concrete monitored-country incident. Exact identity with mc-assassination-01 is uncertain, so the label stays disputed. |
| `mc-synth-escalation-01` | No v1 alert/identity field changed | attack=[UA]; protection=precaution; status=active | “rosyjskiego ataku na zachodnią Ukrainę” / “prewencyjnym poderwaniu polskich i sojuszniczych samolotów” / “podczas rosyjskiego ataku” | The title places the Russian attack in western Ukraine and the summary explicitly says Poland scrambled aircraft preventively without an airspace violation. Poland is affected only by the precaution. |
| `mc-synth-escalation-02` | No v1 alert/identity field changed | attack=[PL]; protection=precaution; status=active | “one attack-capable Shahed crossed into Poland” / “Air defence tracked it” / “no impact was reported” | The same alert now includes an explicit attack-capable Shahed incursion into Poland. That is an active Polish physical incident and a critical same-episode escalation. |
| `mc-synth-escalation-03` | No v1 alert/identity field changed | attack=[PL]; protection=official_warning; status=active | “нову хвилю щонайменше шести ударних дронів” / “наказала мешканцям Люблінщини перейти в укриття” / “Нова хвиля російських дронів” | The text says the prior episode ended before a new wave of strike drones over Lublin and a resident shelter order. This is a new critical Polish incident. |

## Sequence-level notification changes

- `poland-precautionary-scramble-2026-09-16`: `mc-scramble-pl-01` is now below 5 because “Alert” does not establish a resident order. `mc-scramble-pl-02` is therefore the first concrete precaution and changes to `initial`. `mc-scramble-pl-06` is the later explicit resident air-raid alert and changes to `update` at 9–10.
- `border-train-near-poland-2026-09-13`: all four alert labels remain pending. `same_as` is preserved for the true physical episode; `mc-border-train-02` remains disputed because the title-only identity evidence is not conclusive.
- `rusinowo-drone-recovery-2026-09-16`: all twelve alert labels remain pending. Their local Polish recovery remains separate from proof of a hostile Polish impact/incursion.
- `russian-assassination-network-2026-09-16`: the two uncertain cross-outlet identity labels remain disputed; the preserved `same_as` values are not promoted to approval.

## Review boundary

This annotation copy does not change the legacy fixture, runtime classifier prompt, runtime configuration, holdout fixture, provider settings, or production files. It records no inference result and makes no model-quality claim.
