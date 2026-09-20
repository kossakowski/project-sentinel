# Independent review of the version-2 development corpus

Review date: 2026-09-20

## Scope

- I reviewed all 36 development cases against the resolved evaluation-only policy and the current `clarified_policy.py` prompt.
- I derived facts and urgency from each current article only. I used earlier reports only for incident identity and notification chronology.
- I did not inspect model outputs or make network, paid-provider, or production calls.
- This is an independent assistant review, not human approval.

## Review counts

| Check | Result |
|---|---:|
| Cases reviewed | 36/36 |
| Unique IDs | 36/36 |
| Verbatim provenance evidence fields | 108/108 |
| Valid prior, same-sequence `same_as` targets | 27/27 |
| Fetch chronology within sequences | 8/8 sequences |
| Production / synthetic cases | 31 / 5 |
| Initial annotation status | 30 provisional / 6 disputed |
| Status after accepted review resolution | 24 reviewed / 12 disputed |

## Case-specific findings and accepted resolution

| Case or group | Finding | Accepted resolution |
|---|---|---|
| `mc-scramble-pl-05` | Past-tense airport closures do not prove that danger or a protective alert ended. A definite `resolved` status is not supported by the current text. | Mark the case disputed rather than force a definite status. |
| `mc-rusinowo-01`, `mc-rusinowo-02` | The early headlines identify Russian drone material and neutralisation activity, but do not unambiguously establish the policy's Russian military-drone condition. This also makes the first qualifying notification point uncertain. | Mark both cases disputed. Keep notification labels explicitly conditional; do not manufacture a replacement initial notification through disputed rows. |
| `mc-tryncza-01`, `mc-tryncza-02`, `mc-tryncza-03` | The sources concern a drone flying at a festival, while the cited 1–4 rule is expressly for civilian or unknown ground finds. Detention also does not consistently prove that danger ended. | Mark all three cases disputed. |
| `mc-synth-escalation-02` | The source confirms a same-episode attack-capable incursion but does not state whether danger remains active. | Use `facts.status: unclear`. Retain urgency 9–10 and the update notification: a newly confirmed hostile incursion is critical, while unknown present resolution is not evidence of safety. |
| Corpus description | It said there were two synthetic controls although the corpus contains five: three existing controls and two newly added controls. | Describe five synthetic cases or two additional synthetic controls. |

The four original near-border reports correctly remain disputed because none states which side of the border was struck. The two new synthetic border controls supply an explicit Ukraine-side positive case and a same-incident translated confirmation without resolving the real-source ambiguity by assumption.

## Measurement limitation

Use this development corpus for controlled fact and urgency checks. Do not claim its notification metrics are reliable: disputed root cases make some later identity and notification labels unscorable. The held-out corpus remains the clean control for matching behavior.

## Recommendation

- The accepted status changes were applied and validated before inference.
- Preserve all 12 disputed cases as excluded or separately reported rather than treating them as consensus ground truth.
- The remaining 24 cases are recorded as independently assistant-reviewed, never human-approved.
