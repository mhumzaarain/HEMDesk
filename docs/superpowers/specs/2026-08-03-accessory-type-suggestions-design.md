# Accessory Type Form: Equipment-Name Suggestions

**Date:** 2026-08-03
**Follow-up to:** #25 / #31 (accessory inventory)
**Status:** Approved by user (design discussed in session; option "suggest-as-you-type" chosen)

## Problem

`AccessoryType.equipment_name` is free text. That is deliberate — an
accessory type fits an equipment *model*, not a specific serialized unit,
and no equipment-model catalog exists. But free text invites typos and
inconsistent spellings ("SVM7523" vs "SVM 7523"), which would slowly
fragment the catalog.

## Design

Keep the field as free text; add browser-native suggestions sourced from
the equipment inventory:

- The type create/edit views build `equipment_name_options`: the distinct
  `name` + `manufacturer` + `model_number` combinations from `Equipment`,
  joined with single spaces (blank parts skipped), ordered alphabetically
  — e.g. "Patient Monitor Mindray uMEC 12". This matches the format the
  seed data already uses for `equipment_name`.
- `AccessoryTypeForm.equipment_name` widget gains
  `attrs={"list": "equipment-name-options"}`.
- The generic `templates/equipment/accessory_form.html` renders
  `<datalist id="equipment-name-options">` with those options, only when
  `equipment_name_options` is present in context (other users of the
  template are unaffected).
- Typing a value not in the list remains valid (devices not yet
  registered still need accessory types).

No model changes, no migration, no permission changes.

## Tests

- Type create page renders the datalist containing a registered
  equipment's name/manufacturer/model combination.
- Submitting an `equipment_name` NOT in the suggestions still creates the
  type (free text preserved).

## Out of scope

- An `EquipmentModel` entity / FK-based catalog (revisit only if the
  catalog gets messy in practice).
