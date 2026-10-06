# 2-id Windows Apple Music Operator Worker

This worker uses the official Apple Music for Windows account-creation flow. Apple currently documents **Apple Music or Apple TV on Windows** as a supported way to create an Apple Account.

## Safety behavior

- One job at a time.
- An operator must explicitly claim and start every job.
- No CAPTCHA solving.
- No phone-verification bypass.
- No proxy/fingerprint rotation.
- No automatic success detection: the operator confirms what the official Apple UI shows.
- Passwords are never printed.
- Email OTP is transferred through the 2-id server encrypted at rest and consumed once.

## Setup

1. Windows 10/11 with the official Apple Music app installed.
2. Python 3.12+ and Windows OpenSSH client.
3. Run `install.ps1`.
4. Configure `.env` with the dedicated `TWOID_WORKER_KEY`.
5. Open an SSH tunnel:

   `powershell -File .\start-tunnel.ps1 -Server <server-host>`

6. Run `run.ps1`.

The production API remains bound to `127.0.0.1:18220`; the worker reaches it through the SSH tunnel instead of exposing it publicly.

## Job flow

1. Operator claims one pending job.
2. Worker opens Apple Music.
3. Operator navigates to Create New Apple Account and focuses each requested field.
4. Worker types the job values without printing the password.
5. If Apple requests email verification, the worker creates an email-OTP challenge.
6. The user submits the code via Telegram button **📧 ثبت کد ایمیل**.
7. Worker consumes the OTP once and continues.
8. Operator reports CREATED / PHONE_REQUIRED / ACTION_REQUIRED / FAILED.

This design intentionally stops instead of attempting to evade Apple security checks.
