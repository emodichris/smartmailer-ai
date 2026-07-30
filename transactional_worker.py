"""Run the scheduled transactional sender worker: python transactional_worker.py."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from email_sender.sender import EmailSender
from email_verifier.verifier import verify_email_list
from services.recipient_name import recipient_variables
from services.redis_queue import RedisQueueError, TransactionalQueue, utc_now
from services.tenant_store import TenantStore, TenantStoreError
from services.transactional_email import TransactionalEmailError, build_message, decode_attachments


BATCH_SIZE = int(os.getenv("TRANSACTIONAL_BATCH_SIZE", "50"))
INTERVAL_SECONDS = int(os.getenv("TRANSACTIONAL_BATCH_INTERVAL_SECONDS", "300"))
POLL_SECONDS = int(os.getenv("TRANSACTIONAL_WORKER_POLL_SECONDS", "5"))


def process_job(queue: TransactionalQueue, store: TenantStore, job_id: str) -> None:
    job = queue.get(job_id)
    if not job or job.get("status") == "completed":
        return
    job["status"] = "processing"
    job["updated_at"] = utc_now()
    queue.save(job)
    try:
        provider_name, credentials = store.get_provider_connection(job["tenant_id"], job["connection_name"])
        sender = EmailSender(provider_name=provider_name, config=credentials)
        attachments = decode_attachments(job.get("attachments", []))
        recipients = queue.pop_recipients(job_id, BATCH_SIZE)
        if not recipients:
            job["status"] = "completed"
            job["updated_at"] = utc_now()
            queue.save(job)
            return
        for recipient in recipients:
            email = recipient["to_email"]
            try:
                if not verify_email_list([email])[0]["valid"]:
                    job["skipped"] += 1
                    continue
                variables = recipient_variables(email, {**job["variables"], **recipient.get("variables", {})})
                html_body, text_body = build_message(
                    html_body=job.get("html_body"), text_body=job.get("text_body"),
                    template_name=job.get("template_name"), variables=variables,
                    signature_name=job.get("signature_name"), signature_html=job.get("signature_html"),
                )
                sender.send(to_email=email, subject=job["subject"], html_body=html_body,
                            text_body=text_body, attachments=attachments)
                job["accepted"] += 1
            except Exception:
                job["failed"] += 1
        job["processed"] += len(recipients)
        job["updated_at"] = utc_now()
        if job["processed"] >= job["recipient_count"]:
            job["status"] = "completed"
            queue.delete_recipients(job_id)
        else:
            job["status"] = "queued"
            queue.schedule(job_id, time.time() + INTERVAL_SECONDS)
        queue.save(job)
    except (TenantStoreError, TransactionalEmailError, ValueError) as exc:
        job["status"] = "failed"
        job["last_error"] = str(exc)
        job["updated_at"] = utc_now()
        queue.save(job)
    finally:
        queue.finish_claim(job_id)


def main() -> None:
    if not 1 <= BATCH_SIZE <= 50:
        raise SystemExit("TRANSACTIONAL_BATCH_SIZE must be between 1 and 50.")
    if INTERVAL_SECONDS < 60:
        raise SystemExit("TRANSACTIONAL_BATCH_INTERVAL_SECONDS must be at least 60 seconds.")
    queue, store = TransactionalQueue(), TenantStore()
    queue.ping()
    print(f"Transactional worker started: {BATCH_SIZE} recipients every {INTERVAL_SECONDS} seconds.")
    while True:
        try:
            queue.recover_stale_claims(time.time() - 600)
            job_id = queue.claim_due(time.time())
            if job_id:
                process_job(queue, store, job_id)
            else:
                time.sleep(POLL_SECONDS)
        except RedisQueueError as exc:
            print(f"Redis unavailable: {exc}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
