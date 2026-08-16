# Four-class strict relation ground truth

This is a derived benchmark. The original 28-row strict GT is unchanged.

- Original strict GT SHA-256: `83b082a0e196c964cbfd565690898a1cac8fe346801317cab2c711ab31d19064`
- Four-class GT SHA-256: `6ba234b9678df60110ef7efdc4c55cb68e1c50adbf01ce32c0006a87239ea0de`
- Oracle pairs: 28
- Resolved for type/exact evaluation: 27
- Unresolved dependency rows: 1

## Resolved distribution

- CONTRIBUTES_TO: 21
- MODIFIES: 1
- CONTRASTS_WITH: 1
- REFERENCES: 4

## Manually reviewed REFERENCES

- `gw150914_detection_EV_000007` → `gw150914_detection_EV_000010`; cue: **shown in Fig. 1**. EV-7 explicitly points to the Figure 1 node EV-10.
- `gw150914_detection_EV_000018` → `gw150914_detection_EV_000020`; cue: **(see Fig. 3)**. EV-18 explicitly points to the Figure 3 node EV-20.
- `gw150914_detection_EV_000022` → `gw150914_detection_EV_000019`; cue: **These interferometry techniques**. EV-22 explicitly back-refers to the interferometry enhancements introduced in EV-19.
- `gw150914_detection_EV_000022` → `gw150914_detection_EV_000021`; cue: **These interferometry techniques**. EV-22 explicitly back-refers to the immediately preceding optical techniques in EV-21.

## DEPENDS_ON review

- `gw150914_detection_EV_000014` / `gw150914_detection_EV_000015`: **unresolved**. The edge represents computational use of the chirp-mass equation, not a condition, premise, limitation, or scope modification. Per policy it remains unresolved.
