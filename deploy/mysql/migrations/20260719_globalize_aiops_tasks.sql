-- AIOps is a shared operational dataset. Remove obsolete ownership metadata so
-- all authorized administrators see and operate the same task catalogue.
UPDATE report_tasks
SET scope_subject = NULL,
    scope_org_id = NULL,
    scope_regions_json = NULL
WHERE scope_subject IS NOT NULL
   OR scope_org_id IS NOT NULL
   OR scope_regions_json IS NOT NULL;
