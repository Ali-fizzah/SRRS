# Security pass (task P6-T5)

What was checked, and which automated test keeps it true. Run them with `make test`.

## Role matrix

Every endpoint in plan §8 is called by every role, and by nobody signed in. The matrix in `backend/tests/integration/test_role_matrix.py` is copied from the plan, separately from the router code. A new route that is not in the matrix fails the test.

| Checked | Test |
|---|---|
| Each role gets only what §8 allows; others get 403, or 401 if not signed in | `test_role_matrix` |
| No route exists outside the matrix | `test_every_route_is_in_the_matrix` |
| The user who generated a batch cannot approve it (D13) | `test_generator_cannot_approve`, `test_generator_cannot_approve_through_the_api` |

## Passwords and sign-in

| Rule | Where |
|---|---|
| At least 12 characters, with a capital, a small letter and a digit | `app/auth/passwords.py`, applied when an admin creates or changes a user |
| Longer than bcrypt's 72 bytes is refused, never cut short | `app/schemas/auth.py` |
| 5 wrong passwords lock that email for 5 minutes (HTTP 429), and the lock is audit-logged | `app/auth/rate_limit.py`; change it with `REVREC_LOGIN_MAX_FAILURES`, `REVREC_LOGIN_LOCK_SECONDS` |
| One error message and similar timing for every failure, so emails cannot be discovered | `test_bad_credentials_get_one_generic_error`, `test_an_unknown_email_is_limited_the_same_way` |
| The session cookie is `HttpOnly` and `SameSite=Lax` | `test_session_cookie_cannot_be_read_by_page_scripts` |
| Password hashes never appear in a response | `test_password_hashes_never_leave_the_api` |

## Injection

| Checked | Test |
|---|---|
| Filter text is treated as text, including SQL and `LIKE` wildcards | `test_filters_treat_sql_as_plain_text` |
| Sorting accepts listed columns only | `test_sorting_only_accepts_listed_columns` |
| Uploaded text cannot run as a formula in an exported CSV | `csv_safe` in `app/api/listing.py`, with its tests |

## Limits to know about

- **The seeded admin password is public.** `make seed` uses `ChangeMe-Admin1` unless `REVREC_ADMIN_PASSWORD` is set, and the seed does not force a change. Set it before any real deployment.
- **The JWT secret has a development default.** Set `REVREC_JWT_SECRET` before any real deployment.
- **`REVREC_COOKIE_SECURE` is off by default**, because local development has no HTTPS. Turn it on when served over HTTPS.
- **The login lock lives in memory.** A restart clears it, and it would not be shared if the API ever ran as several processes.
- **Someone who knows an email can lock it for 5 minutes.** This is the accepted cost of counting per email: the account itself is not touched.
- **This is a developer's review, not a penetration test.**
