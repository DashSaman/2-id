from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from pywinauto import keyboard


load_dotenv()


@dataclass
class Config:
    api_url: str
    worker_key: str
    apple_music_name: str


def config() -> Config:
    api = os.getenv("TWOID_API_URL", "http://127.0.0.1:18220").rstrip("/")
    key = os.getenv("TWOID_WORKER_KEY", "")
    if not key:
        raise RuntimeError("TWOID_WORKER_KEY is required")
    return Config(api, key, os.getenv("APPLE_MUSIC_APP_NAME", "Apple Music"))


class Client:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = httpx.Client(
            base_url=cfg.api_url,
            headers={"X-Worker-Key": cfg.worker_key},
            timeout=20,
        )

    def claim(self):
        r = self.http.post("/v1/worker/jobs/claim")
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def challenge(self, job_id: str):
        r = self.http.post(f"/v1/worker/jobs/{job_id}/challenge", json={"kind": "email_otp"})
        r.raise_for_status()
        return r.json()

    def poll_challenge(self, job_id: str, timeout_seconds: int = 600):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            r = self.http.get(f"/v1/worker/jobs/{job_id}/challenge")
            if r.status_code == 204:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()
        return None

    def result(self, job_id: str, status: str, code: str):
        r = self.http.post(
            f"/v1/worker/jobs/{job_id}/result",
            json={"status": status, "code": code},
        )
        r.raise_for_status()
        return r.json()


def launch_apple_music(app_name: str) -> None:
    ps = (
        "$a=Get-StartApps | Where-Object {$_.Name -eq '" + app_name.replace("'", "''") + "'} | "
        "Select-Object -First 1; if(-not $a){exit 2}; "
        "Start-Process ('shell:AppsFolder\\'+$a.AppID)"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Apple Music was not found. Install the official Apple Music app from Microsoft Store."
        )


def _escape_send_keys(value: str) -> str:
    mapping = {
        "{": "{{}",
        "}": "{}}",
        "+": "{+}",
        "^": "{^}",
        "%": "{%}",
        "~": "{~}",
        "(": "{(}",
        ")": "{)}",
    }
    return "".join(mapping.get(ch, ch) for ch in value)


def type_into_focused_field(label: str, value: str, secret: bool = False) -> None:
    shown = "[hidden]" if secret else value
    print(f"\nFocus the {label} field in Apple Music. Value: {shown}")
    input("Press Enter here when the field is focused...")
    keyboard.send_keys(_escape_send_keys(value), with_spaces=True, pause=0.025, vk_packet=True)


def show_order(job: dict) -> None:
    p = job["payload"]
    print("\n=== CLAIMED JOB ===")
    print("Order:", job["order_id"])
    print("Email:", p["email"])
    print("Name:", p["first_name"], p["last_name"])
    if p.get("region"):
        print("Region:", p["region"])
    if p.get("birthdate"):
        print("Birthdate:", p["birthdate"])
    print("Password is held in memory only and is never printed.")


def run_job(client: Client, job: dict, cfg: Config) -> None:
    job_id = job["job_id"]
    p = job["payload"]
    show_order(job)

    input("\nPress Enter to open Apple Music and begin this single job...")
    launch_apple_music(cfg.apple_music_name)
    print(
        "\nIn Apple Music choose Sign In -> Sign In -> Create New Apple Account. "
        "Do not continue through CAPTCHA, phone verification, or other security challenges automatically."
    )

    type_into_focused_field("email", p["email"])
    type_into_focused_field("password", p["password"], secret=True)
    type_into_focused_field("first name", p["first_name"])
    type_into_focused_field("last name", p["last_name"])

    if p.get("region"):
        print(f"\nSet the Apple Music region manually to: {p['region']}")
    if p.get("birthdate"):
        print(f"Set the birthdate manually to: {p['birthdate']}")

    while True:
        print(
            "\nWhat does the official Apple UI show now?\n"
            "  1) Email verification code requested\n"
            "  2) Account created successfully\n"
            "  3) Phone verification requested\n"
            "  4) CAPTCHA / additional human action required\n"
            "  5) Creation failed\n"
        )
        choice = input("Choice: ").strip()

        if choice == "1":
            client.challenge(job_id)
            print(
                "The user can now press '📧 ثبت کد ایمیل' in the Telegram bot. "
                "Waiting up to 10 minutes for the encrypted OTP..."
            )
            challenge = client.poll_challenge(job_id)
            if not challenge:
                client.result(job_id, "FAILED", "EMAIL_OTP_TIMEOUT")
                print("OTP timed out; order failed/refunded.")
                return
            type_into_focused_field("email verification code", challenge["value"], secret=True)
            continue

        if choice == "2":
            client.result(job_id, "CREATED", "WINDOWS_APP_CONFIRMED")
            print("Order marked CREATED.")
            return

        if choice == "3":
            client.result(job_id, "PHONE_VERIFICATION_REQUIRED", "PHONE_REQUIRED_BY_APPLE")
            print("Phone verification was required. Order stopped and refunded.")
            return

        if choice == "4":
            client.result(job_id, "ACTION_REQUIRED", "APPLE_HUMAN_CHALLENGE")
            print("Human/security challenge recorded. Order stopped and refunded.")
            return

        if choice == "5":
            code = input("Short failure code (no passwords/OTP): ").strip() or "APPLE_CREATION_FAILED"
            client.result(job_id, "FAILED", code[:80])
            print("Order failed/refunded.")
            return

        print("Invalid choice.")


def main() -> int:
    cfg = config()
    client = Client(cfg)
    print("2-id Windows Apple Music Operator Worker")
    print("This worker handles one job at a time and requires operator confirmation.")
    while True:
        cmd = input("\nEnter=claim next job, q=quit: ").strip().lower()
        if cmd == "q":
            return 0
        try:
            job = client.claim()
            if not job:
                print("No pending jobs.")
                continue
            run_job(client, job, cfg)
        except KeyboardInterrupt:
            print("\nInterrupted. The server lease will eventually make the job claimable again.")
        except Exception as exc:
            print("Worker error:", type(exc).__name__, str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
