# Work orders

**Who:** Engineers & Admins

Use this to carry out a repair once a work order has been opened for a device, from starting the repair through to returning the device to service.

A work order moves through **Open → In Progress → Completed** (outcome Repaired) or **Cancelled**. A device can only have one active work order at a time.

1. Open the work order from the queue (**Open WO**) or from its link on the equipment or dashboard.
2. Click **Start repair**. This sets the device to **In Repair** and adds you to the participants.
3. If another engineer joins in, they click **I'm working on this** to be added as a participant too.
4. As you work, use **Add remark** to log progress. Remarks are one of two kinds:
    - **Note** — a general update.
    - **Delay** — explains why the repair is taking long; delays surface on the dashboard.

    Remarks are append-only — once added, they can't be edited or removed.
5. When the repair is done, click **Complete…** and fill in:
    - **Fault category** (required) — Electrical, Battery / Power, Display / Monitor, Mechanical, Calibration, Software, Accessory / Probe, or Other.
    - Tick every engineer who worked on the repair.
    - An optional closing remark.
    - Click **Mark repaired & return to service**.

If the equipment turns out to have no fault, click **Cancel (no fault)** instead of completing it. This closes the work order, returns the device to **Working**, and closes any attached complaints as **No Fault Found**.

The detail page also shows a timeline, the attached complaints with confirmation badges (**Awaiting staff confirmation**, **Staff confirmed: Functional ✓**, **Staff reported: NOT functional ✗**), the remarks log, and the device's accessories with [fault actions](../equipment/accessory-faults.md).

<!-- screenshot: docs/assets/workorder-detail.png -->

## What happens next

Completing a repair returns the device to **Working**, closes its attached complaints as **Resolved**, and asks each reporter to confirm the equipment is actually working again.
