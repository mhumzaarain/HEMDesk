# Departments & reference data

**Who:** Admins

Use this when you are setting up HEMDesk for the first time, when a new ward or
department opens, or when you are wondering where one of the drop-down lists in
the app comes from and how to change it.

## How much setup does HEMDesk need?

Less than you might expect. **Departments are the only list you have to create
yourself.** Everything else is either built into the app or gets created during
normal day-to-day work.

| What | Who creates it | Where |
| --- | --- | --- |
| **Departments** | Admin | Admin site — this page |
| **User accounts** | Admin | Admin site — see [Managing user accounts](user-accounts.md) |
| **Equipment** | Engineers & Admins | In the app: [Register equipment](../equipment/register.md) |
| **Accessory types** | Engineers & Admins | In the app: [Accessories & stock](../equipment/accessories.md) |
| **Fault categories** | Admin | Admin site — see below |
| **Roles** | Nobody — built in | Fixed list: Staff, Biomedical Engineer, Admin |

So a realistic first-day setup is: create your departments, then create your
users. That's it — engineers can start registering equipment straight away.

## Creating a department

A department is a ward, unit, or area of the hospital that equipment belongs
to — ICU, Radiology, Emergency, and so on. Every device must belong to one, so
create these before registering equipment.

1. Open the admin site from the **Admin** link at the bottom of the sidebar
   (it takes you to `/admin/`). No link there? See
   [Who can do what](#who-can-do-what) — you need the Admin role.
2. Under **Equipment**, next to **Departments**, click **Add**.
3. Fill in:
    - **Name** — what people call it, e.g. `ICU`. This is what appears in
      drop-down lists and on reports, so use the name staff will recognise. It
      must be unique.
    - **Location** — optional, and free text. Somewhere to note where the
      department physically is, e.g. `Block A, Floor 2`.
4. Click **Save**.

The department is available immediately, with no restart or re-deploy needed.

!!! note
    Importing equipment from a spreadsheet can create departments for you.
    On the import screen there is a **Create missing departments** tick-box —
    with it ticked, any department named in your file that doesn't exist yet is
    created automatically. See [Import from Excel or CSV](../equipment/import.md).

### Renaming or removing a department

Open **Equipment → Departments**, click the one you want, edit it, and save.
Renaming is safe — equipment stays attached, because the link is not based on
the name.

Deleting is different. If any equipment or user still belongs to the
department, HEMDesk **refuses to delete it** and shows a protected-object
error. This is deliberate: it stops a device from silently losing its location.
To retire a department, first move its equipment elsewhere, then delete it.

## Fault categories

Nobody picks a category when *lodging* a complaint. It is chosen by the
**engineer**, at the end of the job, on the form that completes a work order —
see [Work orders](../complaints/work-orders.md). The category is what drives the
fault breakdown on the dashboard and in the monthly report, and it helps the AI
assistant find similar past repairs.

HEMDesk ships with these eight, listed here in the order they appear in the
engineer's dropdown:

| Name | Description |
| --- | --- |
| Electrical | Mains supply, power supply unit, wiring, fuses or switches failed |
| Electronic boards | A circuit board or module was repaired or replaced |
| Display / Monitor | Screen, touch panel or display output failed |
| Mechanical | A moving or structural part was damaged, repaired or replaced |
| Calibration | Calibration or adjustment was needed |
| Software | Firmware or software error, crash, freeze or update required |
| Accessory / Probe / Battery | A probe, sensor, cable, battery or charging circuit failed, not the main unit |
| Other | Anything not covered above — explain in the remark |

If a fault doesn't fit any of the eight, engineers should use **Other** and
describe it in the remarks.

### Adding a fault category

1. Open the admin site, and under **Maintenance**, next to **Fault
   categories**, click **Add**.
2. Fill in:
    - **Name** — what engineers see in the dropdown.
    - **Description** — one line saying plainly what kind of fault belongs
      here. This is what the engineer reads under the dropdown on the repair
      completion form.
    - **Sort order** — a number that decides where the category sits in the
      dropdown; lower numbers appear first.
3. Click **Save**.

There is a fourth box on the form, **Slug**. Leave it alone — the next section
explains what it is and the two occasions when HEMDesk will ask you to fill it
in yourself.

### The internal code

Alongside the name you type, each category carries a short **internal code** —
the **Slug** box on the form. It is a plain-text version of the name, in small
letters with hyphens instead of spaces: `Water ingress` becomes
`water-ingress`. HEMDesk fills it in for you as you type the name, so in normal
use you never touch it.

The code is how HEMDesk remembers, behind the scenes, which category a repair
was given. Every completed repair points at the code rather than at the words
you typed. **The code is set once, when the category is first saved, and never
changes afterwards** — that is exactly what makes renaming a category safe, and
why a rename shows up on every repair already recorded against it.

Two things can go wrong when the code is being worked out, and HEMDesk tells
you about both on the form rather than letting them through.

**Two categories cannot share a code.** Because the code ignores capitals and
punctuation, `battery`, `Battery` and `Battery!` all reduce to the same code,
`battery`. If you try to add a category whose name differs from an existing one
only in that way, HEMDesk refuses to save it and shows a message under **Name**
naming the category already using that code. Nothing is created. The remedy is
to pick a genuinely different name — `Battery / charging` rather than
`battery` — not to work around it.

**Some names produce no code at all.** A name written in a script that has no
plain-text equivalent — Urdu, Arabic, Chinese — or one made only of punctuation
leaves nothing for HEMDesk to build a code from. When that happens you get a
message under **Slug** asking you to type a code yourself. Put a short
description of the category in that box, in small letters, using only letters,
numbers and hyphens — for example `water-ingress` — and save again. The name
stays exactly as you wrote it, and the name is what engineers, the dashboard
and the reports show — the code is only ever seen here in the admin site.

### Renaming or removing a fault category

Open **Maintenance → Fault categories**, click the one you want, and edit its
**Name**, **Description**, or **Sort order**. Renaming is safe: the new name
appears immediately on every repair already recorded against it, including in
the dashboard's fault chart.

Deleting only works while no repair has used the category yet. Once a repair
has used it, HEMDesk refuses to delete it and names the work orders holding
it — rename it instead of trying to delete a used category.

## Who can do what

Everything a person sees and can do in HEMDesk comes from one setting: their
**Role**, which is Staff, Biomedical Engineer, or Admin. There is nothing else
to configure — no permission lists to tick, nothing to assign. If someone is
seeing too much or too little of the app, change their Role and nothing else.

Role **Admin** also grants access to the admin site itself, and is what makes
the **Admin** link appear at the bottom of the sidebar; Staff and Biomedical
Engineer do not get either. See [Managing user accounts](user-accounts.md).

## What you can and can't change in the admin site

The admin site deliberately locks down most records. Complaints, work orders,
and PPM visits are the hospital's maintenance history, so they are shown for
reference but cannot be added or edited by hand — they are only created by
people using the app properly, which keeps the history trustworthy.

| Section | You can | You cannot |
| --- | --- | --- |
| Departments | Add, edit, delete | — |
| Users | Add, edit, delete | — |
| Fault categories | Add, edit, delete | — |
| Equipment | Add, edit | Delete (condemn it in the app instead) |
| Accessory types | Add, edit | Delete |
| Service manuals | Add, edit, delete | — |
| Risk scoring settings | Edit the single settings record | Add a second one, delete it |
| Complaints, work orders, PPM schedules | View only | Add, edit, or delete |
| PPM records, remarks, status events, accessory events, audit log | View only | Change anything |

!!! warning
    Even where the admin site lets you edit something, prefer the app's own
    screens. The app enforces the workflow rules — status changes, history
    entries, stock counts — and the admin site does not. A device added
    through the admin site gets no entry in its own status history and no line
    in the audit log, so it will look different from every other device in the
    registry. Register equipment at **Equipment → Register**, or by
    [importing a spreadsheet](../equipment/import.md), instead.

!!! warning "Do not upload service manuals through the admin site"
    The admin site lets you add a **Service manual**, but it only files the
    record — it never starts the reading-and-indexing step. The manual sits at
    "processing" forever and the AI assistant never finds anything in it, with
    no error to tell you. Always upload manuals from the app's own
    [Manuals page](../ai/manuals.md), which does start that step.

In fact only four things can ever be deleted here: departments, users, fault
categories, and service manuals. Everything that forms part of the maintenance
history — equipment, complaints, work orders, remarks, PPM records, the audit
log — is permanent by design, and the app refuses to remove it however you
try. If a device should leave daily use, condemn it in the app rather than
looking for a delete button.

Even those four can refuse. A department or user that still has equipment,
complaints, or work orders attached cannot be deleted, and a fault category
that a repair has already used cannot be deleted either, so that nothing is
left pointing at a record that no longer exists.

**What happens next:** With your departments created, engineers can register
equipment against them, staff can lodge complaints, and the department filters
on the dashboard and reports start showing real data.
