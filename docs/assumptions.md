# Planning assumptions

**Project:** [Manufacturing Readiness & Shortage Intelligence](../README.md)

The results describe one synthetic planning case. The January 4, 2027 snapshot represents what a planner knows at the start of the eight-week horizon. Changing a receipt date, component revision, or purchasing lead time can change which orders have enough material.

| Subject | Rule used in the model | Why it matters |
| --- | --- | --- |
| Supply profile | The generator deliberately creates a mix of stock coverage, inbound dependence, and shortage exposure. SQL calculates each order's status from the resulting records. | The readiness rate describes this designed case. It cannot estimate how often shortages occur at a real factory. |
| Usable inventory | Remove quality-held units and protect existing order reservations before sharing free stock. Baseline supply is pooled by component and revision across locations. | A warehouse balance can include units unavailable to the order being planned. The baseline assumes access to pooled stock. |
| Incoming supply | Count open purchase orders on their expected receipt date. | A promised shipment can cover a future requirement while leaving the order exposed to delivery risk. |
| Engineering revision | Match the bill of materials and available supply by revision. Hypothetical engineering cutovers are separate simulations. | An available unit of a different revision cannot automatically fill a shortage. |
| Standard replenishment | Assume buyers place new orders for all missing units on the snapshot date and suppliers achieve the part master's lead time. | A blocked order can still have an on-time modeled start if new material can arrive in time. |
| Expediting | Charge 25% above the base unit cost. Multiply standard lead time by 0.65, round up to whole days, and allow at least one day. | A premium helps the schedule only when the earlier receipt changes the date the complete order can start. |
| Alternate supply | Require approval for the revision by the snapshot date. Use the quoted price and lead time up to the available quantity. Buy the balance from the primary source. | Qualification alone does not guarantee a faster arrival or enough units. |
| Factory and supplier capacity | Procurement scenarios omit shared supplier capacity, labor availability, and competition for production equipment. | A recovered start date is conditional on material availability. Production release requires a separate feasibility check. |

Compare purchasing strategies independently against the same shortages. Adding their benefits together would count the same order more than once. Likewise, the modeled value of missing units uses standard component costs. Estimating lost sales, profit, or contractual penalties would require additional information.

See the [supply manifest](../data/raw/supply_manifest.json), [disruption manifest](../data/raw/disruption_manifest.json), and [procurement scenario SQL](../sql/07_recovery_analysis.sql) for the underlying parameters.
