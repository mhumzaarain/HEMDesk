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

Nobody picks a category when *lodging* a complaint. The **engineer** picks it,
at the end of the job. They pick it on the form that completes a work order —
see [Work orders](../complaints/work-orders.md). The category drives the fault
breakdown on the dashboard and in the monthly report. It also helps the AI
assistant find similar past repairs.

HEMDesk ships with these eight. They are listed here in the order they appear
in the engineer's dropdown.

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

Some faults fit none of the eight. Engineers should choose **Other** for those.
They should then describe the fault in the remarks.

### The Slug box

The form for a fault category has a box labelled **Slug**. Read this before you
add your first category. It is the only part of the form that needs explaining.

A slug is a short internal code. It is written in small letters, numbers and
hyphens — for example `water-ingress`. HEMDesk uses this code to remember which
category a repair was given. Every completed repair points at the code. It does
not point at the words you typed.

**You normally leave the box empty.** When you click **Save**, HEMDesk works
the code out from the name. It makes the name small and turns each space into a
hyphen. So `Water ingress` becomes `water-ingress`.

Three of the eight categories HEMDesk ships with have an underscore in their
code: `electronic_boards`, `display_monitor` and `accessory_probe`. The other
five are single words. An underscore and a hyphen work the same way here, so
the difference does not matter.

**The code is set once and never changes.** It is set the first time you save
the category. If you open the category again later, the code is still shown,
but as plain text you cannot type in. This is what makes renaming a category
safe. The repairs point at the code, and the code stays put, so a rename cannot
break the link to them.

You never need the code anywhere else. Engineers, the dashboard and the reports
all show the name. The code is only ever seen here in the admin site.

### Adding a fault category

1. Open the admin site from the **Admin** link at the bottom of the sidebar.
2. Under **Maintenance**, next to **Fault categories**, click **Add**. A form
   opens with four boxes: **Name**, **Slug**, **Description** and **Sort
   order**.
3. In **Name**, type what engineers will see in the dropdown, e.g.
   `Water ingress`.
4. Leave **Slug** empty. HEMDesk fills it in for you when you save.
5. In **Description**, type one line saying plainly what kind of fault belongs
   here. The engineer reads this line under the dropdown on the repair
   completion form.
6. In **Sort order**, type a number. The number decides where the category
   sits in the engineer's dropdown. Lower numbers appear first. The eight
   categories HEMDesk ships with are numbered 10, 20, 30 and so on up to 80, so
   pick a number that puts yours where you want it.
7. Click **Save**.

You are taken back to the list of fault categories. A message at the top
confirms the category was added. Your new category is in the list, in the place
its sort order gives it. Engineers can choose it straight away. Nothing needs
restarting.

Sometimes HEMDesk will not accept the category. The form comes back instead,
with everything you typed still in it, and a message in red saying what is
wrong. Nothing has been created at that point. The next section covers both
reasons this happens.

### When HEMDesk will not accept a new category

Two things can go wrong when HEMDesk works the code out from your name. It
tells you about each one on the form.

**The name gives a code that another category already uses.** Capitals and
punctuation are ignored when the code is worked out. So `battery`, `Battery`
and `Battery!` all give the same code: `battery`. Two categories cannot share a
code. So if a category called `Battery` already exists, typing `battery` or
`Battery!` is refused.

*What you will see:* the form comes back, with a message under **Name**. The
message tells you which category already uses that code.

*What to do:* choose a properly different name. For example, type
`Battery / charging` instead of `battery`. Then click **Save** again.

**The name gives no code at all.** Some names leave nothing for HEMDesk to
build a code from. A name written in a script such as Urdu or Arabic is one
case. A name made only of punctuation is another.

*What you will see:* the form comes back, with a message under **Slug**. The
message asks you to type a code yourself.

*What to do:* type a code into the **Slug** box. Use small letters, numbers and
hyphens only — for example `water-ingress`. Then click **Save** again. Your
name is kept exactly as you typed it. Only the code is different.

### Renaming or removing a fault category

Open **Maintenance → Fault categories**. Click the category you want. You can
edit its **Name**, **Description** and **Sort order**. Then click **Save**.

Renaming is safe. The new name appears straight away on every repair already
recorded against that category. It appears in the dashboard's fault chart too.

Deleting is different. You can only delete a category while no repair has used
it. Once a repair has used it, HEMDesk refuses to delete it. It shows you an
error page listing the work orders that hold the category. If you no longer
want a category that repairs have used, rename it. Do not try to delete it.

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
| Departments | Add, edit, delete while nothing uses it | Delete one that still has equipment or people |
| Users | Add, edit, delete | — |
| Fault categories | Add, edit, delete while no repair has used it | Delete one a repair has used (rename it instead) |
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
