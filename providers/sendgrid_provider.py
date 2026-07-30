from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail,
    Email,
    To,
    Content,
    Attachment,
    FileContent,
    FileName,
    FileType,
    Disposition,
)
import base64


class SendGridProvider:

    def __init__(
        self,
        api_key,
        sender_name,
        sender_email
    ):

        self.api_key = api_key
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

        message = Mail(

            from_email=Email(
                self.sender_email,
                self.sender_name
            ),

            to_emails=To(
                to_email
            ),

            subject=subject,

            plain_text_content=Content(
                "text/plain",
                text_body or ""
            ),

            html_content=Content(
                "text/html",
                html_body
            )

        )

        for attachment in attachments or []:
            message.add_attachment(Attachment(
                FileContent(base64.b64encode(attachment["content"]).decode("ascii")),
                FileName(attachment["filename"]),
                FileType(attachment.get("content_type") or "application/octet-stream"),
                Disposition("attachment"),
            ))


        try:

            sg = SendGridAPIClient(
                self.api_key
            )

            response = sg.send(
                message
            )


            return {

                "status": "sent",

                "provider": "sendgrid",

                "recipient": to_email,

                "code": response.status_code

            }


        except Exception as e:

            raise Exception(
                str(e)
            )
