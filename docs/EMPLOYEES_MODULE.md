# AutoStop CRM Employees Module

This note captures the durable context for the `Сотрудники` workspace.

## What This Module Covers

- employee roster
- employee profile editing
- salary scheme and payroll totals
- salary ledger and payout flow
- active/all filtering
- month-based employee report

## Current Practical Truth

- the workspace is a master-detail layout
- salary flow opens from the employee list
- payout actions are part of the live UI and should be smoke-tested after deploys
- create mode must not overwrite the selected employee record
- month changes and destructive actions should not silently discard unsaved edits

## Repeated Verification Points

1. open the Employees workspace
2. open an employee salary card
3. verify payout/open-close actions
4. verify create mode opens a blank profile
5. verify active/all filtering after toggling an employee
6. verify month changes do not lose edits without confirmation

## Common Failure Modes

- salary button exists but route or API path is missing
- create mode accidentally reuses a stale employee ID
- active filter hides the toggled employee unexpectedly
- a month switch or delete action drops unsaved form changes

## Related Files

- `src/minimal_kanban/web_assets.py`
- `src/minimal_kanban/api/server.py`
- `src/minimal_kanban/services/card_service.py`
- `tests/test_api.py`
- `tests/test_web_assets.py`

