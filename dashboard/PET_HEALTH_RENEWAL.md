# Renewing a care follow-up (0.2.6-beta.2)

The interactive Health card offers a **New care / Nouveau soin** button for each
open follow-up. It opens the existing care form in renewal mode. The pet and
category are fixed; today's local HA date and the previous title are suggested.
Enter the actual event date, update the title if necessary, and enter new notes
and a next follow-up date only if applicable. No interval or date is inferred.
Cancel returns to ordinary entry without saving; the renewal replaces any
unsaved care form draft. The explicit save-and-close button submits one action.

The local `mova_nutripal.renew_pet_care` action targets exactly one global Pet
health tracking sensor. It accepts `previous_record_id`, `expected_due_date`
(the previous ISO due date as text), and `record` (the normal new care object).
The backend validates the open record, its expected due date, the pet/category,
the date ordering, duplicate records and the storage limit before writing once.
The old record retains its content and ID, with `completed` set to true; the new
record gets a new ID and remains open only if a next due date was supplied.
An already closed record is rejected; after an ambiguous response, refresh or
reload and check history before retrying. The existing correction action still
allows marking an old follow-up complete without creating another care event.
No storage schema, reminder automation, feeding or cloud behavior is changed.
