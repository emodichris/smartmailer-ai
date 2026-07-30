import requests
import base64
from msal import ConfidentialClientApplication


class GraphProvider:


    def __init__(
        self,
        tenant_id,
        client_id,
        client_secret,
        sender_email
    ):

        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender_email = sender_email



    def get_token(self):

        authority = (
            f"https://login.microsoftonline.com/"
            f"{self.tenant_id}"
        )


        app = ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret
        )


        result = app.acquire_token_for_client(
            scopes=[
                "https://graph.microsoft.com/.default"
            ]
        )


        return result["access_token"]



    def send_email(
        self,
        to_email,
        subject,
        html_body,
        text_body=None,
        attachments=None
    ):


        token = self.get_token()


        url = (
            f"https://graph.microsoft.com/v1.0/users/"
            f"{self.sender_email}/sendMail"
        )


        message = {

            "message": {

                "subject": subject,


                "body": {

                    "contentType": "HTML",

                    "content": html_body

                },


                "toRecipients": [

                    {

                        "emailAddress": {

                            "address": to_email

                        }

                    }

                ],
                "attachments": [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment["filename"],
                        "contentType": attachment.get("content_type") or "application/octet-stream",
                        "contentBytes": base64.b64encode(attachment["content"]).decode("ascii"),
                    }
                    for attachment in (attachments or [])
                ]

            }

        }


        headers = {

            "Authorization": f"Bearer {token}",

            "Content-Type": "application/json"

        }


        response = requests.post(
            url,
            json=message,
            headers=headers
        )


        if response.status_code != 202:

            raise Exception(
                response.text
            )


        return {

            "status": "sent",

            "provider": "graph",

            "recipient": to_email

        }
