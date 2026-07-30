import smtplib
import ssl
import mimetypes

from email.message import EmailMessage

from providers.base_provider import BaseProvider


class SMTPProvider(BaseProvider):

    def __init__(
        self,
        host,
        port,
        username,
        password,
        sender_name,
        sender_email
    ):

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender_name = sender_name
        self.sender_email = sender_email


    def send_email(
        self,
        to_email,
        subject,
        html_body,
        text_body=None,
        attachments=None
    ):

        message = EmailMessage()

        message["From"] = (
            f"{self.sender_name} <{self.sender_email}>"
        )

        message["To"] = to_email

        message["Subject"] = subject


        if text_body:

            message.set_content(
                text_body
            )


        message.add_alternative(
            html_body,
            subtype="html"
        )

        for attachment in attachments or []:
            content_type = attachment.get("content_type") or "application/octet-stream"
            maintype, subtype = content_type.split("/", 1)
            message.add_attachment(
                attachment["content"],
                maintype=maintype,
                subtype=subtype,
                filename=attachment["filename"],
            )


        with smtplib.SMTP(
            self.host,
            self.port
        ) as server:

            server.starttls(
                context=ssl.create_default_context()
            )


            server.login(
                self.username,
                self.password
            )


            server.send_message(
                message
            )


        return {
            "status": "sent",
            "provider": "smtp",
            "recipient": to_email
        }
