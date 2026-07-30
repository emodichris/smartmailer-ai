import os
from dotenv import load_dotenv


load_dotenv()


EMAIL_PROVIDER = os.getenv(
    "EMAIL_PROVIDER",
    "smtp"
).lower()


EMAIL_CONFIG = {}


# ==========================
# HOSTINGER / SMTP
# ==========================

if EMAIL_PROVIDER == "smtp":

    EMAIL_CONFIG = {

        "host": os.getenv(
            "SMTP_HOST"
        ),

        "port": int(
            os.getenv(
                "SMTP_PORT",
                587
            )
        ),

        "username": os.getenv(
            "SMTP_USERNAME"
        ),

        "password": os.getenv(
            "SMTP_PASSWORD"
        ),

        "sender_name": os.getenv(
            "SENDER_NAME"
        ),

        "sender_email": os.getenv(
            "SENDER_EMAIL"
        ),

    }



# ==========================
# OFFICE365 SMTP
# ==========================

elif EMAIL_PROVIDER == "office365":

    EMAIL_CONFIG = {

        "username": os.getenv(
            "OFFICE365_USERNAME"
        ),

        "password": os.getenv(
            "OFFICE365_PASSWORD"
        ),

        "sender_name": os.getenv(
            "SENDER_NAME"
        ),

        "sender_email": os.getenv(
            "SENDER_EMAIL"
        ),

    }



# ==========================
# MICROSOFT GRAPH API
# ==========================

elif EMAIL_PROVIDER == "graph":

    EMAIL_CONFIG = {

        "tenant_id": os.getenv(
            "GRAPH_TENANT_ID"
        ),

        "client_id": os.getenv(
            "GRAPH_CLIENT_ID"
        ),

        "client_secret": os.getenv(
            "GRAPH_CLIENT_SECRET"
        ),

        "sender_email": os.getenv(
            "SENDER_EMAIL"
        ),

    }



# ==========================
# SENDGRID
# ==========================

elif EMAIL_PROVIDER == "sendgrid":

    EMAIL_CONFIG = {

        "api_key": os.getenv(
            "SENDGRID_API_KEY"
        ),

        "sender_name": os.getenv(
            "SENDER_NAME"
        ),

        "sender_email": os.getenv(
            "SENDER_EMAIL"
        ),

    }