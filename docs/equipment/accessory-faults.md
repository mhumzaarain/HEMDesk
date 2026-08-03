# Accessory faults & replacement

**Who:** Engineers & Admins

Use this when an accessory fitted to a device fails and needs to be marked faulty, repaired, or replaced.

Fault handling happens on an active work order for the device — see the work order page (Complaints & Repairs). From there:

1. **Mark faulty** — one click, no extra fields.
2. **Repair** — enter the required "What was done," which returns the unit to **Working**.
3. **Replace…** — enter the required **Reason** and an optional new serial number. This condemns the old unit, takes one from backup stock, and creates the new unit's record.

!!! warning
    **Replace…** fails with "No backup stock available — restock this type first" if the accessory type has zero units in store.

## Condemning an accessory outright

If an accessory fails and won't be replaced, you can condemn it without going through a work order:

1. From the equipment detail page, click **Condemn…** next to the accessory.
2. Enter a **Reason**.
3. Confirm.

The accessory's record is preserved.

**What happens next:** Every action — mark faulty, repair, replace, condemn — is logged as an accessory event. The equipment detail page shows all-time replacement counts (for example, "3× ECG cable…"). Replacements feed the dashboard's accessory panel and the inventory's restock strip.
