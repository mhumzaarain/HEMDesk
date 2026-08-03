# Accessories & stock

**Who:** Engineers & Admins

Use this to manage the accessory catalog, keep backup stock counts accurate, and attach physical accessories to devices.

There are two related concepts:

- An **accessory type** is a catalog entry — for example, "ECG cable" for "Patient Monitor Mindray uMEC 12" — with a backup-stock counter.
- An **accessory** is one physical unit fitted to one device.

## Accessory inventory

1. Open **Accessories** in the sidebar.
2. Each accessory type shows badges **In store: N** and **Fitted: N**.
3. A **Restock needed** strip at the top lists types currently at zero stock.
4. Use **Add type**, **Adjust stock**, or **Edit** as needed.

## Add a type

1. Click **Add type**.
2. Fill in:
      - **Name**
      - **Equipment name** — the device this accessory is for, autocompleted from existing equipment.
      - **Notes**
      - Initial stock quantity.
3. Save.

## Adjust stock

1. From the inventory list, click **Adjust stock** for a type.
2. Choose an **Action** (**Add to stock** / **Remove from stock**), enter a **Quantity**, and give a required **Reason**.
3. Save.

This is the only way stock changes by hand. Stock can never go below zero.

## Attach a unit to a device

1. From the equipment detail page, click **Attach accessory**.
2. Choose the **Accessory type**.
3. Optionally enter a **Serial number** — many accessories are not serialized.
4. **Take from backup stock** is ticked by default; untick it when you're cataloging a unit that's already fitted rather than issuing a new one from stock.
5. Add **Notes** if needed and save.

Taking from stock decrements the type's store count, and fails if stock is at zero.

**What happens next:** every stock adjustment and attachment is logged with its reason. When a type's store count hits zero it appears in the **Restock needed** strip on the inventory page, and replacement activity feeds the dashboard's accessory panel.
