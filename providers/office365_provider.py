import smtplib

from email.message import EmailMessage


class Office365Provider:

    def __init__(
        self,
        username,
        password,
        sender_name,
        sender_email
    ):
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
            message.set_content(text_body)

        message.add_alternative(
            html_body,
            subtype="html"
        )

        for attachment in attachments or []:
            maintype, subtype = attachment.get("content_type", "application/octet-stream").split("/", 1)
            message.add_attachment(
                attachment["content"],
                maintype=maintype,
                subtype=subtype,
                filename=attachment["filename"],
            )


        with smtplib.SMTP(
            "smtp.office365.com",
            587
        ) as server:

            server.starttls()

            server.login(
                self.username,
                self.password
            )

            server.send_message(message)


        return {
            "status": "sent",
            "provider": "office365",
            "recipient": to_email
        }
