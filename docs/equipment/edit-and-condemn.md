# Edit & condemn equipment

**Who:** Engineers & Admins

Use edit to correct or update a device's details. Use condemn when a device is permanently retired from service.

## Edit

1. From the equipment detail page, click **Edit**.
2. The edit form reuses the same fields as registration.
3. Save your changes.

Status is never edited directly on this form — it changes only through workflows: a work order opening or completing, or condemning the device.

## Status model

- **Working → In Repair** — a repair (work order) starts.
- **In Repair → Working** — the repair is completed or cancelled.
- **Working / In Repair → Condemned** — permanent.

Condemned devices never change status again.

## Condemn

1. From the equipment detail page, click **Condemn…**.
2. Fill in the required **Remark** and **Condemned location**.
3. Click **Condemn permanently**.

!!! warning
    Condemning a device cannot be undone.

**What happens next:** Any active work order on the device is force-completed with outcome **Condemned**; all open complaints on the device are closed; the equipment record is preserved (nothing is deleted); no new complaints can be lodged against it.
