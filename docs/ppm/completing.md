# Completing due PPMs

**Who:** Engineers & Admins

Use this whenever you've carried out a planned preventive maintenance visit on a device, to record what was done and push its schedule forward.

1. Reach the due list from the **PPM schedule** card on the home page, or the PPM panel on the dashboard (there's no sidebar link). Both lead to the same PPM due list, split into **Overdue** and **Due soon** (next 30 days), with a department filter and a count of devices with no active schedule.
2. Find the device and click **Record PPM**.
3. Fill in the form:
    - **Date performed** — defaults to today; it can't be set in the future.
    - **Outcome** — **Passed**, **Passed with remarks**, or **Failed**. Choosing **Failed** reveals **"Open a work order for this fault"**.
    - Tick every engineer who performed the PPM.
    - **Remarks** — optional notes.
4. Submit to save the record.

!!! tip
    If the device failed the PPM and needs repair, tick **"Open a work order for this fault"** before submitting — this opens a work order in the same step instead of you having to lodge a complaint afterwards.

## What happens next

The PPM record is stored (append-only — it can't be edited or deleted afterwards), and the schedule's next due date advances by its interval, measured from the date performed.

Recording is blocked when:

- the schedule is inactive,
- the device is condemned, or
- the device has an active work order — complete or cancel it first (see [Work orders](../complaints/work-orders.md)).
