# PPM schedules

**Who:** Engineers & Admins

Set this up when a device goes into service (or whenever its maintenance interval changes) so HEMDesk knows when it's next due for planned preventive maintenance (PPM).

1. Open the device's equipment detail page.
2. Click **Set schedule** (or **Edit schedule** if one already exists).
3. Choose an **Interval** — Monthly, Quarterly, Every 6 months, or Annual.
4. Set the **Next due** date.
5. Leave **Active** ticked, then save.

Each device can have only one PPM schedule. Condemned equipment can't be scheduled.

!!! note
    Untick **Active** to pause a schedule — for example, while a device is in long-term storage. This hides the device from the due list without deleting its PPM history; retick it and it reappears once its next due date arrives.

## What happens next

The device now shows up on the PPM due list once its next due date is overdue or within 30 days out. From there, engineers record each PPM as it's completed — see [Completing due PPMs](completing.md).
