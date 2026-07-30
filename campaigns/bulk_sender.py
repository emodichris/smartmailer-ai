from email_sender.sender import EmailSender
from settings.config import EMAIL_CONFIG, EMAIL_PROVIDER


class BulkSender:


    def __init__(self):

        self.sender = EmailSender(
            provider_name=EMAIL_PROVIDER,
            config=EMAIL_CONFIG
        )


    def send_campaign(
        self,
        contacts,
        subject,
        html_template,
        text_template=None
    ):

        results = []


        for contact in contacts:

            email = contact["email"]


            html_body = html_template.format(
                **contact
            )


            if text_template:

                text_body = text_template.format(
                    **contact
                )

            else:

                text_body = None



            try:

                result = self.sender.send(
                    to_email=email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body
                )


                results.append({

                    "email": email,
                    "status": "sent",
                    "result": result

                })


            except Exception as e:


                results.append({

                    "email": email,
                    "status": "failed",
                    "error": str(e)

                })


        return results