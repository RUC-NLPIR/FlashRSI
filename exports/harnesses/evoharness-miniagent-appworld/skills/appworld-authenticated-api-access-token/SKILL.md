---
name: appworld-authenticated-api-access-token
description: >-
  AppWorld tasks whose app APIs require authentication. Use when an app API call
  returns HTTP 401 or its docs list a required access_token parameter, and after
  an app login call has returned an access_token.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [22cc237_1, 22cc237_2]
---
# AppWorld authenticated API calls: pass access_token explicitly

AppWorld app logins do not auto-authenticate later calls, and tokens are not
persisted across separate shell `execute` blocks. Capture the returned
`access_token` and pass it explicitly to every authenticated call.

## Workflow
1. Get the app credentials:
```python
creds = apis.supervisor.show_account_passwords(app_name="simple_note")
```
2. Call the app's login endpoint and capture the token:
```python
tok = apis.simple_note.login(
    username=creds["username"], password=creds["password"]
)["access_token"]
```
3. Pass the token explicitly to every authenticated call in the same script:
```python
apis.simple_note.show_account(access_token=tok)
apis.simple_note.search_notes(access_token=tok)
```

Do not rely on a previous login call to authenticate the persistent session.
If a later `execute` block still returns 401, re-run the login inside that same
block and reuse the fresh token there.

## When to apply
- Any AppWorld app endpoint returns 401 about a missing, invalid, or expired
  access token.
- The endpoint docs list a required `access_token` parameter.
- Observed for simple_note and venmo; the same explicit-token pattern applies
  to gmail, spotify, splitwise, todoist, amazon, phone, and file_system.

## Verification
Before answering, confirm the authenticated calls returned data rather than 401.
If any 401 remains, capture the token from that same script's login call and
re-issue the failed call with `access_token=tok`.
